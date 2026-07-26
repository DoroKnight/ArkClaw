import asyncio
import logging
from collections.abc import Callable

import pytest

from sjtuclaw.application.agent_loop import AgentLoop, CancellationToken
from sjtuclaw.application.context_manager import ContextManager
from sjtuclaw.domain.errors import ProviderError
from sjtuclaw.domain.events import AgentEvent, AgentEventType, LLMEvent, LLMEventType
from sjtuclaw.domain.models import (
    LLMRequest,
    ProviderCapabilities,
    ProviderContinuation,
    UserMessageCommand,
)
from sjtuclaw.domain.ports import LLMProvider
from sjtuclaw.infrastructure.llm.fake_provider import FakeProvider

type ProviderBuilder = Callable[[], LLMProvider]


@pytest.fixture
def provider_builder() -> ProviderBuilder:
    """Return the provider under test; future adapters can override this fixture."""

    return FakeProvider


def _request(
    content: str = "hello",
    *,
    continuation: ProviderContinuation | None = None,
) -> LLMRequest:
    return ContextManager().build_request(
        UserMessageCommand.create(content),
        continuation=continuation,
    )


async def _collect_turn(
    provider: LLMProvider,
    *,
    content: str = "hello",
    cancellation: CancellationToken | None = None,
    continuation: ProviderContinuation | None = None,
) -> list[AgentEvent]:
    agent = AgentLoop(provider, ContextManager())
    return [
        event
        async for event in agent.run(
            UserMessageCommand.create(content),
            cancellation=cancellation,
            continuation=continuation,
        )
    ]


def test_provider_identity_and_capabilities_are_stable(
    provider_builder: ProviderBuilder,
) -> None:
    async def scenario() -> None:
        provider = provider_builder()
        try:
            assert provider.name == provider.name == "fake"
            assert isinstance(provider.capabilities(), ProviderCapabilities)
            assert provider.capabilities() == provider.capabilities()
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_provider_normal_stream_contract(provider_builder: ProviderBuilder) -> None:
    async def scenario() -> None:
        provider = provider_builder()
        try:
            events = [event async for event in provider.generate_stream(_request())]
        finally:
            await provider.aclose()

        assert events
        assert events[-1].type is LLMEventType.COMPLETED
        assert all(event.type is LLMEventType.TEXT_DELTA for event in events[:-1])
        assert sum(
            event.type in {LLMEventType.COMPLETED, LLMEventType.ERROR}
            for event in events
        ) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "script",
    [
        (),
        (LLMEvent.text_delta("partial"),),
        (LLMEvent.completed(), LLMEvent.completed()),
        (LLMEvent.completed(), LLMEvent.text_delta("late")),
        (
            LLMEvent.failure("provider_error", "failed"),
            LLMEvent.text_delta("late"),
        ),
        (LLMEvent(type=LLMEventType.TOOL_CALL),),
        (LLMEvent(type=LLMEventType.ERROR),),
        (LLMEvent(type=LLMEventType.TEXT_DELTA, text=""),),
    ],
    ids=[
        "empty-stream",
        "early-eof",
        "duplicate-completed",
        "output-after-completed",
        "output-after-error",
        "missing-tool-call",
        "incomplete-error",
        "empty-text-delta",
    ],
)
def test_agent_loop_rejects_provider_contract_violations(
    script: tuple[LLMEvent, ...],
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(script=script)
        try:
            events = await _collect_turn(provider)
        finally:
            await provider.aclose()

        failure = next(
            event for event in events if event.type is AgentEventType.TURN_FAILED
        )
        assert failure.error_code == "invalid_provider_stream"
        assert AgentEventType.TURN_COMPLETED not in {event.type for event in events}

    asyncio.run(scenario())


def test_cancellation_closes_stream_without_closing_provider() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            response_text="reusable",
            chunk_size=20,
            delay_seconds=0.05,
        )
        token = CancellationToken()
        turn_task = asyncio.create_task(
            _collect_turn(provider, cancellation=token)
        )

        for _ in range(20):
            if provider.active_stream_count == 1:
                break
            await asyncio.sleep(0)
        assert provider.active_stream_count == 1

        token.cancel()
        cancelled_events = await asyncio.wait_for(turn_task, timeout=0.2)
        assert AgentEventType.TURN_CANCELLED in {
            event.type for event in cancelled_events
        }
        assert provider.active_stream_count == 0
        assert not provider.closed

        second_events = await asyncio.wait_for(
            _collect_turn(provider, content="second"),
            timeout=0.2,
        )
        assert second_events[-1].type is AgentEventType.TURN_COMPLETED
        assert not provider.closed
        await provider.aclose()

    asyncio.run(scenario())


def test_provider_can_be_reused_across_completed_turns() -> None:
    async def scenario() -> None:
        provider = FakeProvider(response_text="ok")
        try:
            first = await _collect_turn(provider, content="first")
            second = await _collect_turn(provider, content="second")
        finally:
            await provider.aclose()

        assert first[-1].type is AgentEventType.TURN_COMPLETED
        assert second[-1].type is AgentEventType.TURN_COMPLETED

    asyncio.run(scenario())


def test_provider_aclose_is_idempotent_and_closed_behavior_is_explicit() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        await provider.aclose()
        await provider.aclose()

        assert provider.closed
        with pytest.raises(ProviderError) as captured:
            _ = [event async for event in provider.generate_stream(_request())]
        assert captured.value.code == "provider_closed"

    asyncio.run(scenario())


def test_completed_turn_returns_continuation() -> None:
    async def scenario() -> None:
        continuation = ProviderContinuation("fake", b"state-1", version="1")
        provider = FakeProvider(response_text="ok", continuation=continuation)
        try:
            events = await _collect_turn(provider)
        finally:
            await provider.aclose()

        completed = next(
            event for event in events if event.type is AgentEventType.TURN_COMPLETED
        )
        assert completed.continuation is continuation

    asyncio.run(scenario())


def test_previous_continuation_reaches_next_provider_request() -> None:
    async def scenario() -> None:
        received: list[ProviderContinuation | None] = []
        continuation = ProviderContinuation("fake", b"state-1", version="1")

        def responder(request: LLMRequest) -> str:
            received.append(request.continuation)
            return "ok"

        provider = FakeProvider(
            responder=responder,
            continuation=continuation,
        )
        try:
            first = await _collect_turn(provider, content="first")
            first_completed = next(
                event
                for event in first
                if event.type is AgentEventType.TURN_COMPLETED
            )
            await _collect_turn(
                provider,
                content="second",
                continuation=first_completed.continuation,
            )
        finally:
            await provider.aclose()

        assert received == [None, continuation]

    asyncio.run(scenario())


def test_continuation_for_different_provider_is_rejected() -> None:
    async def scenario() -> None:
        continuation = ProviderContinuation("openai", b"state")
        provider = FakeProvider()
        try:
            events = await _collect_turn(provider, continuation=continuation)
        finally:
            await provider.aclose()

        failure = next(
            event for event in events if event.type is AgentEventType.TURN_FAILED
        )
        assert failure.error_code == "provider_continuation_mismatch"
        assert AgentEventType.TURN_COMPLETED not in {event.type for event in events}

    asyncio.run(scenario())


def test_provider_output_continuation_for_different_provider_is_rejected() -> None:
    async def scenario() -> None:
        continuation = ProviderContinuation("openai", b"state")
        provider = FakeProvider(continuation=continuation)
        try:
            events = await _collect_turn(provider)
        finally:
            await provider.aclose()

        failure = next(
            event for event in events if event.type is AgentEventType.TURN_FAILED
        )
        assert failure.error_code == "provider_continuation_mismatch"
        assert AgentEventType.TURN_COMPLETED not in {event.type for event in events}

    asyncio.run(scenario())


def test_failed_turn_does_not_commit_continuation() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            script=[
                LLMEvent.text_delta("partial"),
                LLMEvent.failure("provider_error", "failed"),
            ]
        )
        try:
            events = await _collect_turn(provider)
        finally:
            await provider.aclose()

        assert AgentEventType.TURN_FAILED in {event.type for event in events}
        assert AgentEventType.TURN_COMPLETED not in {event.type for event in events}
        assert all(event.continuation is None for event in events)

    asyncio.run(scenario())


def test_cancelled_turn_does_not_commit_continuation() -> None:
    async def scenario() -> None:
        continuation = ProviderContinuation("fake", b"not-committed")
        provider = FakeProvider(
            response_text="slow",
            delay_seconds=0.05,
            continuation=continuation,
        )
        token = CancellationToken()
        task = asyncio.create_task(
            _collect_turn(provider, cancellation=token)
        )
        for _ in range(20):
            if provider.active_stream_count == 1:
                break
            await asyncio.sleep(0)
        token.cancel()

        events = await asyncio.wait_for(task, timeout=0.2)
        await provider.aclose()

        assert AgentEventType.TURN_CANCELLED in {event.type for event in events}
        assert AgentEventType.TURN_COMPLETED not in {event.type for event in events}
        assert all(event.continuation is None for event in events)

    asyncio.run(scenario())


def test_continuation_state_is_excluded_from_repr_logs_and_sdk_types(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-provider-state"
    continuation = ProviderContinuation("fake", secret.encode(), version="1")
    request = _request(continuation=continuation)
    llm_event = LLMEvent.completed(continuation)
    agent_event = AgentEvent.completed("turn", "ok", continuation)
    caplog.set_level(logging.DEBUG)

    async def scenario() -> list[AgentEvent]:
        provider = FakeProvider()
        try:
            return await _collect_turn(
                provider,
                continuation=ProviderContinuation("openai", secret.encode()),
            )
        finally:
            await provider.aclose()

    mismatch_events = asyncio.run(scenario())

    assert secret not in repr(continuation)
    assert secret not in repr(request)
    assert secret not in repr(llm_event)
    assert secret not in repr(agent_event)
    assert "continuation=" not in repr(request)
    assert "continuation=" not in repr(llm_event)
    assert "continuation=" not in repr(agent_event)
    assert all(secret not in event.error_message for event in mismatch_events)
    assert secret not in caplog.text
    assert type(continuation.state) is bytes
    assert ProviderContinuation.__module__ == "sjtuclaw.domain.models"
