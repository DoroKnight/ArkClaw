from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import AsyncGenerator
from typing import cast

import pytest
from tests.fakes.deepseek_sdk import (
    FakeDeepSeekClientFactory,
    FakeDeepSeekScenario,
)

from sjtuclaw.config.provider_profiles import deepseek_profile
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.events import LLMEvent, LLMEventType
from sjtuclaw.domain.models import (
    DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    ApiProtocol,
    ChatMessage,
    CredentialId,
    LLMRequest,
    MessageRole,
    ProfileId,
    ProviderContinuation,
    ToolRisk,
    ToolSpec,
)
from sjtuclaw.infrastructure.llm.deepseek_provider import DeepSeekProvider
from sjtuclaw.infrastructure.llm.deepseek_sdk import (
    DeepSeekEvent,
    DeepSeekEventKind,
    DeepSeekFailureCode,
)

_FAKE_DEEPSEEK_KEY = "sk-deepseek-test-never-use"
_REASONING_SECRET = "hidden-reasoning-must-not-appear"


def _text(value: str = "hello") -> DeepSeekEvent:
    return DeepSeekEvent(
        kind=DeepSeekEventKind.TEXT_DELTA,
        text=value,
    )


def _completed() -> DeepSeekEvent:
    return DeepSeekEvent(
        kind=DeepSeekEventKind.COMPLETED,
        finish_reason="stop",
    )


def _store(
    credential_id: CredentialId = DEEPSEEK_DEFAULT_CREDENTIAL_ID,
) -> InMemorySecretStore:
    store = InMemorySecretStore()
    store.set_secret(credential_id, SecretValue(_FAKE_DEEPSEEK_KEY))
    return store


def _provider(
    factory: FakeDeepSeekClientFactory,
    *,
    profile_id: ProfileId | None = None,
    credential_id: CredentialId = DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    store: InMemorySecretStore | None = None,
) -> DeepSeekProvider:
    profile = deepseek_profile(
        "deepseek-v4-flash",
        profile_id=profile_id or ProfileId.new(),
        credential_id=credential_id,
    )
    return DeepSeekProvider(
        profile=profile,
        secret_store=store or _store(credential_id),
        timeout_seconds=30.0,
        max_retries=0,
        stream=True,
        client_factory=factory,
    )


def _request(
    *,
    continuation: ProviderContinuation | None = None,
    tools: tuple[ToolSpec, ...] = (),
) -> LLMRequest:
    return LLMRequest(
        instructions="Be brief.",
        messages=(
            ChatMessage(role=MessageRole.USER, content="hello"),
        ),
        tools=tools,
        max_output_tokens=128,
        continuation=continuation,
    )


async def _collect(
    provider: DeepSeekProvider,
    request: LLMRequest | None = None,
) -> list[LLMEvent]:
    return [
        event
        async for event in provider.generate_stream(
            request or _request()
        )
    ]


def test_deepseek_streams_text_and_replays_messages_only() -> None:
    async def scenario() -> None:
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(
                        DeepSeekEvent(kind=DeepSeekEventKind.METADATA),
                        _text("hel"),
                        _text("lo"),
                        _completed(),
                        DeepSeekEvent(kind=DeepSeekEventKind.METADATA),
                    )
                ),
            )
        )
        provider = _provider(factory)
        try:
            events = await _collect(provider)
        finally:
            await provider.aclose()

        assert [event.type for event in events] == [
            LLMEventType.TEXT_DELTA,
            LLMEventType.TEXT_DELTA,
            LLMEventType.COMPLETED,
        ]
        continuation = events[-1].continuation
        assert continuation is not None
        assert continuation.provider_name == "deepseek"
        assert _REASONING_SECRET not in repr(continuation)
        request = factory.clients[0].requests[0]
        assert request.model == "deepseek-v4-flash"
        assert request.max_tokens == 128
        assert request.messages[-1] == {
            "role": "user",
            "content": "hello",
        }
        assert provider.capabilities().protocol is ApiProtocol.CHAT_COMPLETIONS
        assert provider.capabilities().tools is False
        assert factory.network_request_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("failure_code", "expected"),
    [
        ("output_budget_exhausted", "output_budget_exhausted"),
        ("content_filtered", "content_filtered"),
        ("unsupported_capability", "unsupported_capability"),
        ("provider_unavailable", "provider_unavailable"),
        ("invalid_response", "invalid_response"),
    ],
)
def test_finish_failures_are_mapped_without_completion(
    failure_code: DeepSeekFailureCode,
    expected: str,
) -> None:
    async def scenario() -> None:
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(
                        _text("partial"),
                        DeepSeekEvent(
                            kind=DeepSeekEventKind.FAILED,
                            failure_code=failure_code,
                        ),
                    )
                ),
            )
        )
        provider = _provider(factory)
        try:
            events = await _collect(provider)
        finally:
            await provider.aclose()
        assert events[-1].type is LLMEventType.ERROR
        assert events[-1].error_code == expected
        assert all(
            event.type is not LLMEventType.COMPLETED for event in events
        )

    asyncio.run(scenario())


def test_unsupported_tools_fail_before_secret_or_client() -> None:
    class ExplodingStore(InMemorySecretStore):
        def get_secret(
            self,
            credential_id: CredentialId,
        ) -> SecretValue | None:
            del credential_id
            raise AssertionError("secret must not be read")

    async def scenario() -> None:
        factory = FakeDeepSeekClientFactory()
        provider = _provider(factory, store=ExplodingStore())
        tool = ToolSpec(
            name="unsafe",
            description="not supported",
            input_schema={"type": "object"},
            risk=ToolRisk.SAFE,
        )
        try:
            events = await _collect(
                provider,
                _request(tools=(tool,)),
            )
        finally:
            await provider.aclose()
        assert events[-1].error_code == "unsupported_capability"
        assert factory.create_count == 0

    asyncio.run(scenario())


def test_continuation_is_bound_to_profile_protocol_and_version() -> None:
    async def scenario() -> None:
        first_profile_id = ProfileId.new()
        first_factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(events=(_text(), _completed())),
            )
        )
        first = _provider(first_factory, profile_id=first_profile_id)
        try:
            first_events = await _collect(first)
        finally:
            await first.aclose()
        continuation = first_events[-1].continuation
        assert continuation is not None

        second_factory = FakeDeepSeekClientFactory()
        second = _provider(
            second_factory,
            profile_id=ProfileId.new(),
        )
        try:
            mismatch = await _collect(
                second,
                _request(continuation=continuation),
            )
            forged = await _collect(
                second,
                _request(
                    continuation=ProviderContinuation(
                        "deepseek",
                        (
                            b'{"adapter_version":"1",'
                            b'"profile_id":"builtin-deepseek-default",'
                            b'"protocol":"responses"}'
                        ),
                        version="1",
                    )
                ),
            )
        finally:
            await second.aclose()
        assert mismatch[-1].error_code == "invalid_continuation"
        assert forged[-1].error_code == "invalid_continuation"
        assert second_factory.create_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("after_partial_delta", [False, True])
def test_cancellation_closes_stream_and_preserves_cancelled_error(
    after_partial_delta: bool,
) -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        started = asyncio.Event()
        fake_scenario = FakeDeepSeekScenario(
            events=(_text("partial"), _completed()),
            iteration_started=started,
            iteration_gate=None if after_partial_delta else gate,
        )
        factory = FakeDeepSeekClientFactory((fake_scenario,))
        provider = _provider(factory)
        iterator = cast(
            AsyncGenerator[LLMEvent, None],
            provider.generate_stream(_request()),
        )
        if after_partial_delta:
            first = await anext(iterator)
            assert first.type is LLMEventType.TEXT_DELTA
            fake_scenario.iteration_gate = gate
        async def next_event() -> LLMEvent:
            return await anext(iterator)

        task = asyncio.create_task(next_event())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await iterator.aclose()
        await provider.aclose()
        assert provider.active_stream_count == 0
        assert factory.clients[0].closed
        assert all(stream.closed for stream in factory.clients[0].streams)
        assert not {
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task()
        }

    asyncio.run(scenario())


def test_stream_close_failure_blocks_until_cleanup_retry() -> None:
    async def scenario() -> None:
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(_text(), _completed()),
                    stream_close_failures=2,
                ),
                FakeDeepSeekScenario(events=(_text("next"), _completed())),
            )
        )
        provider = _provider(factory)
        first = await _collect(provider)
        blocked = await _collect(provider)
        recovered = await _collect(provider)
        await provider.aclose()

        assert first[-1].error_code == "provider_unavailable"
        assert blocked[-1].error_code == "provider_unavailable"
        assert len(factory.clients[0].requests) == 2
        assert recovered[-1].type is LLMEventType.COMPLETED

    asyncio.run(scenario())


def test_client_close_failure_blocks_credential_rotation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> tuple[list[LLMEvent], list[LLMEvent]]:
        credential_id = CredentialId.new()
        store = _store(credential_id)
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(_text(), _completed()),
                    client_close_failures=1,
                ),
                FakeDeepSeekScenario(events=(_text("rotated"), _completed())),
            )
        )
        provider = _provider(
            factory,
            credential_id=credential_id,
            store=store,
        )
        await _collect(provider)
        store.set_secret(credential_id, SecretValue("rotated-fake-key"))
        blocked = await _collect(provider)
        recovered = await _collect(provider)
        await provider.aclose()
        return blocked, recovered

    with caplog.at_level(logging.ERROR):
        blocked, recovered = asyncio.run(scenario())
    visible = caplog.text + repr(blocked) + repr(recovered)
    assert blocked[-1].error_code == "provider_unavailable"
    assert recovered[-1].type is LLMEventType.COMPLETED
    assert _FAKE_DEEPSEEK_KEY not in visible
    assert _REASONING_SECRET not in visible
    assert "Authorization" not in visible
    assert "Traceback" not in visible


def test_unknown_sensitive_failure_is_sanitized() -> None:
    async def scenario() -> list[LLMEvent]:
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    create_error=RuntimeError(
                        f"Authorization {_FAKE_DEEPSEEK_KEY} "
                        f"{_REASONING_SECRET}"
                    )
                ),
            )
        )
        provider = _provider(factory)
        try:
            return await _collect(provider)
        finally:
            await provider.aclose()

    events = asyncio.run(scenario())
    rendered = repr(events) + "".join(
        traceback.format_exception(
            RuntimeError,
            RuntimeError("safe"),
            None,
        )
    )
    assert events[-1].error_code == "provider_unavailable"
    assert _FAKE_DEEPSEEK_KEY not in rendered
    assert _REASONING_SECRET not in rendered


def test_aclose_interrupts_a_stream_stalled_after_first_delta() -> None:
    async def scenario() -> None:
        iteration_started = asyncio.Event()
        iteration_gate = asyncio.Event()
        close_started = asyncio.Event()
        fake_scenario = FakeDeepSeekScenario(
            events=(_text("first"), _completed()),
            iteration_started=iteration_started,
            stream_close_started=close_started,
        )
        factory = FakeDeepSeekClientFactory((fake_scenario,))
        provider = _provider(factory)
        iterator = cast(
            AsyncGenerator[LLMEvent, None],
            provider.generate_stream(_request()),
        )
        first = await anext(iterator)
        assert first.type is LLMEventType.TEXT_DELTA
        iteration_started.clear()
        fake_scenario.iteration_gate = iteration_gate

        async def next_event() -> LLMEvent:
            return await anext(iterator)

        next_task = asyncio.create_task(next_event())
        await iteration_started.wait()
        close_task = asyncio.create_task(provider.aclose())
        await close_started.wait()
        await close_task
        assert factory.clients[0].streams[0].closed
        await next_task
        await iterator.aclose()
        assert provider.active_stream_count == 0
        assert not {
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }

    asyncio.run(scenario())


def test_two_concurrent_requests_register_and_close_two_streams() -> None:
    async def scenario() -> None:
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        first_gate = asyncio.Event()
        second_gate = asyncio.Event()
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(_text("one"), _completed()),
                    iteration_started=first_started,
                    iteration_gate=first_gate,
                ),
                FakeDeepSeekScenario(
                    events=(_text("two"), _completed()),
                    iteration_started=second_started,
                    iteration_gate=second_gate,
                ),
            )
        )
        provider = _provider(factory)
        first_iterator = cast(
            AsyncGenerator[LLMEvent, None],
            provider.generate_stream(_request()),
        )
        second_iterator = cast(
            AsyncGenerator[LLMEvent, None],
            provider.generate_stream(_request()),
        )

        async def next_event(
            iterator: AsyncGenerator[LLMEvent, None],
        ) -> LLMEvent:
            return await anext(iterator)

        first_task = asyncio.create_task(next_event(first_iterator))
        second_task = asyncio.create_task(next_event(second_iterator))
        await first_started.wait()
        await second_started.wait()
        assert provider.active_stream_count == 2

        await provider.aclose()
        await first_task
        await second_task
        await first_iterator.aclose()
        await second_iterator.aclose()
        assert provider.active_stream_count == 0
        assert all(
            stream.closed
            for stream in factory.clients[0].streams
        )

    asyncio.run(scenario())


def test_aclose_serializes_with_request_initialization() -> None:
    async def scenario() -> None:
        create_started = asyncio.Event()
        create_gate = asyncio.Event()
        close_attempted = asyncio.Event()
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(_text(), _completed()),
                    create_started=create_started,
                    create_gate=create_gate,
                ),
            )
        )
        provider = _provider(factory)

        async def collect() -> list[LLMEvent]:
            return await _collect(provider)

        async def close() -> None:
            close_attempted.set()
            await provider.aclose()

        request_task = asyncio.create_task(collect())
        await create_started.wait()
        close_task = asyncio.create_task(close())
        await close_attempted.wait()
        assert not close_task.done()
        create_gate.set()
        await close_task
        await request_task
        assert provider.closed
        assert provider.active_stream_count == 0
        assert factory.clients[0].closed

    asyncio.run(scenario())


def test_cancellation_during_stream_close_is_retried_by_aclose() -> None:
    async def scenario() -> None:
        close_started = asyncio.Event()
        close_gate = asyncio.Event()
        fake_scenario = FakeDeepSeekScenario(
            events=(_text(), _completed()),
            stream_close_started=close_started,
            stream_close_gate=close_gate,
        )
        factory = FakeDeepSeekClientFactory((fake_scenario,))
        provider = _provider(factory)
        request_task = asyncio.create_task(_collect(provider))
        await close_started.wait()
        request_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request_task
        close_gate.set()
        await provider.aclose()
        assert provider.active_stream_count == 0
        assert factory.clients[0].closed

    asyncio.run(scenario())


def test_cancellation_during_client_close_is_retried() -> None:
    async def scenario() -> None:
        close_started = asyncio.Event()
        close_gate = asyncio.Event()
        fake_scenario = FakeDeepSeekScenario(
            events=(_text(), _completed()),
        )
        factory = FakeDeepSeekClientFactory((fake_scenario,))
        provider = _provider(factory)
        await _collect(provider)
        fake_scenario.client_close_started = close_started
        fake_scenario.client_close_gate = close_gate
        close_task = asyncio.create_task(provider.aclose())
        await close_started.wait()
        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        close_gate.set()
        await provider.aclose()
        assert factory.clients[0].closed
        assert provider.active_stream_count == 0

    asyncio.run(scenario())


def test_cancellation_during_pending_retry_keeps_cleanup_recoverable() -> None:
    async def scenario() -> None:
        retry_started = asyncio.Event()
        retry_gate = asyncio.Event()
        fake_scenario = FakeDeepSeekScenario(
            events=(_text(), _completed()),
            stream_close_failures=1,
        )
        factory = FakeDeepSeekClientFactory((fake_scenario,))
        provider = _provider(factory)
        first = await _collect(provider)
        assert first[-1].error_code == "provider_unavailable"
        fake_scenario.stream_close_started = retry_started
        fake_scenario.stream_close_gate = retry_gate
        retry_task = asyncio.create_task(_collect(provider))
        await retry_started.wait()
        retry_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await retry_task
        retry_gate.set()
        await provider.aclose()
        assert provider.active_stream_count == 0
        assert factory.clients[0].closed

    asyncio.run(scenario())


def test_cancellation_while_waiting_for_lifecycle_lock_propagates() -> None:
    async def scenario() -> None:
        create_started = asyncio.Event()
        create_gate = asyncio.Event()
        second_started = asyncio.Event()
        factory = FakeDeepSeekClientFactory(
            (
                FakeDeepSeekScenario(
                    events=(_text(), _completed()),
                    create_started=create_started,
                    create_gate=create_gate,
                ),
            )
        )
        provider = _provider(factory)
        first_task = asyncio.create_task(_collect(provider))
        await create_started.wait()

        async def second_request() -> list[LLMEvent]:
            second_started.set()
            return await _collect(provider)

        second_task = asyncio.create_task(second_request())
        await second_started.wait()
        second_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second_task
        create_gate.set()
        await first_task
        await provider.aclose()
        assert provider.active_stream_count == 0
        assert not {
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }

    asyncio.run(scenario())
