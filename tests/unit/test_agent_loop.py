import asyncio
import logging
from collections.abc import AsyncIterator

import pytest

from sjtuclaw.application.agent_loop import AgentLoop, CancellationToken
from sjtuclaw.application.context_manager import ContextManager
from sjtuclaw.domain.events import AgentEvent, AgentEventType, LLMEvent, LLMEventType
from sjtuclaw.domain.models import AgentState, LLMRequest, ToolCall, UserMessageCommand
from sjtuclaw.infrastructure.llm.fake_provider import FakeProvider


class _BlockingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cleaned_up = asyncio.Event()

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
        self.started.set()
        try:
            await asyncio.Event().wait()
            yield LLMEvent.completed()
        finally:
            self.cleaned_up.set()


class _ExplodingProvider(FakeProvider):
    def __init__(self, secret: str, sensitive_body: str) -> None:
        super().__init__()
        self._secret = secret
        self._sensitive_body = sensitive_body

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        del request
        await asyncio.sleep(0)
        if self._secret:
            raise RuntimeError(f"{self._secret}: {self._sensitive_body}")
        yield LLMEvent.completed()


def _collect(
    agent: AgentLoop,
    command: UserMessageCommand,
    *,
    cancellation: CancellationToken | None = None,
) -> list[AgentEvent]:
    async def collect_events() -> list[AgentEvent]:
        return [
            event
            async for event in agent.run(
                command,
                cancellation=cancellation,
            )
        ]

    return asyncio.run(collect_events())


def test_agent_loop_streams_text_and_state_transitions() -> None:
    provider = FakeProvider(response_text="abcdef", chunk_size=2)
    agent = AgentLoop(provider, ContextManager())

    events = _collect(agent, UserMessageCommand.create("hello"))

    assert [event.type for event in events] == [
        AgentEventType.TURN_STARTED,
        AgentEventType.STATE_CHANGED,
        AgentEventType.STATE_CHANGED,
        AgentEventType.STATE_CHANGED,
        AgentEventType.TEXT_DELTA,
        AgentEventType.TEXT_DELTA,
        AgentEventType.TEXT_DELTA,
        AgentEventType.STATE_CHANGED,
        AgentEventType.TURN_COMPLETED,
    ]
    assert [event.state for event in events if event.type is AgentEventType.STATE_CHANGED] == [
        AgentState.LISTENING,
        AgentState.THINKING,
        AgentState.SPEAKING,
        AgentState.IDLE,
    ]
    assert (
        "".join(event.text for event in events if event.type is AgentEventType.TEXT_DELTA)
        == "abcdef"
    )
    assert events[-1].text == "abcdef"


def test_agent_loop_surfaces_provider_error_without_leaking_exception() -> None:
    provider = FakeProvider(
        script=[LLMEvent.failure("invalid_api_key", "The provider rejected the key.")]
    )
    agent = AgentLoop(provider, ContextManager())

    events = _collect(agent, UserMessageCommand.create("hello"))

    failure = next(event for event in events if event.type is AgentEventType.TURN_FAILED)
    assert failure.error_code == "invalid_api_key"
    assert failure.error_message == "The provider rejected the key."
    assert events[-1].state is AgentState.IDLE


def test_agent_loop_fails_closed_when_provider_requests_tool() -> None:
    provider = FakeProvider(
        script=[
            LLMEvent.call_tool(
                ToolCall(call_id="call-1", name="open_url", arguments={"url": "https://x"})
            )
        ]
    )
    agent = AgentLoop(provider, ContextManager())

    events = _collect(agent, UserMessageCommand.create("open a site"))

    failure = next(event for event in events if event.type is AgentEventType.TURN_FAILED)
    assert failure.error_code == "tool_execution_not_configured"
    assert AgentEventType.TOOL_STARTED not in {event.type for event in events}
    assert AgentEventType.TOOL_FINISHED not in {event.type for event in events}


def test_agent_loop_honors_pre_cancelled_token() -> None:
    token = CancellationToken()
    token.cancel()
    agent = AgentLoop(FakeProvider(), ContextManager())

    events = _collect(
        agent,
        UserMessageCommand.create("hello"),
        cancellation=token,
    )

    assert [event.type for event in events] == [
        AgentEventType.TURN_STARTED,
        AgentEventType.STATE_CHANGED,
        AgentEventType.TURN_CANCELLED,
        AgentEventType.STATE_CHANGED,
    ]
    assert events[-1].state is AgentState.IDLE


def test_agent_loop_times_out() -> None:
    provider = FakeProvider(response_text="slow", delay_seconds=0.05)
    agent = AgentLoop(provider, ContextManager(), max_turn_seconds=0.001)

    events = _collect(agent, UserMessageCommand.create("hello"))

    failure = next(event for event in events if event.type is AgentEventType.TURN_FAILED)
    assert failure.error_code == "turn_timeout"
    assert events[-1].state is AgentState.IDLE


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        -1,
        "30",
    ],
)
def test_agent_loop_rejects_invalid_max_turn_seconds(value: object) -> None:
    provider = FakeProvider()
    try:
        with pytest.raises(ValueError, match="max_turn_seconds"):
            AgentLoop(
                provider,
                ContextManager(),
                max_turn_seconds=value,  # type: ignore[arg-type]
            )
    finally:
        asyncio.run(provider.aclose())


@pytest.mark.parametrize("value", [1, 1.5])
def test_agent_loop_accepts_positive_finite_max_turn_seconds(
    value: int | float,
) -> None:
    provider = FakeProvider()
    try:
        AgentLoop(provider, ContextManager(), max_turn_seconds=value)
    finally:
        asyncio.run(provider.aclose())


def test_cooperative_cancellation_interrupts_waiting_provider_and_cleans_tasks() -> None:
    async def scenario() -> None:
        provider = _BlockingProvider()
        token = CancellationToken()
        agent = AgentLoop(provider, ContextManager())

        async def collect() -> list[AgentEvent]:
            return [
                event
                async for event in agent.run(
                    UserMessageCommand.create("hello"),
                    cancellation=token,
                )
            ]

        task = asyncio.create_task(collect())
        await asyncio.wait_for(provider.started.wait(), timeout=0.2)
        token.cancel()
        events = await asyncio.wait_for(task, timeout=0.2)

        assert AgentEventType.TURN_CANCELLED in {event.type for event in events}
        assert provider.cleaned_up.is_set()
        current = asyncio.current_task()
        pending = {
            pending_task
            for pending_task in asyncio.all_tasks()
            if pending_task is not current and not pending_task.done()
        }
        assert not pending

    asyncio.run(scenario())


def test_external_task_cancellation_propagates_after_provider_cleanup() -> None:
    async def scenario() -> None:
        provider = _BlockingProvider()
        agent = AgentLoop(provider, ContextManager())

        async def collect() -> list[AgentEvent]:
            return [
                event
                async for event in agent.run(UserMessageCommand.create("hello"))
            ]

        task = asyncio.create_task(collect())
        await asyncio.wait_for(provider.started.wait(), timeout=0.2)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.cleaned_up.is_set()
        assert not provider.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "script",
    [
        (),
        (LLMEvent.text_delta("partial"),),
        (LLMEvent.completed(), LLMEvent.completed()),
        (LLMEvent.completed(), LLMEvent.text_delta("late")),
        (LLMEvent(type=LLMEventType.TOOL_CALL),),
        (LLMEvent(type=LLMEventType.ERROR),),
        (LLMEvent(type=LLMEventType.TEXT_DELTA, text=""),),
    ],
    ids=[
        "empty-stream",
        "missing-terminal",
        "duplicate-completed",
        "event-after-terminal",
        "missing-tool-call",
        "incomplete-error",
        "empty-text-delta",
    ],
)
def test_agent_loop_rejects_invalid_provider_stream(
    script: tuple[LLMEvent, ...],
) -> None:
    agent = AgentLoop(FakeProvider(script=script), ContextManager())

    events = _collect(agent, UserMessageCommand.create("hello"))

    failure = next(event for event in events if event.type is AgentEventType.TURN_FAILED)
    assert failure.error_code == "invalid_provider_stream"
    assert failure.error_message == "The provider returned an invalid event stream."
    assert AgentEventType.TURN_COMPLETED not in {event.type for event in events}


def test_unexpected_exception_is_logged_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-test-should-not-leak"
    sensitive_body = "private user message"
    provider = _ExplodingProvider(secret, sensitive_body)
    agent = AgentLoop(provider, ContextManager())
    command = UserMessageCommand(
        turn_id="turn-observe",
        session_id="session-observe",
        content=sensitive_body,
    )
    caplog.set_level(logging.ERROR, logger="sjtuclaw.application.agent_loop")

    events = _collect(agent, command)

    failure = next(event for event in events if event.type is AgentEventType.TURN_FAILED)
    assert failure.error_code == "unexpected_agent_error"
    assert failure.error_message == "The Agent turn failed unexpectedly."
    log_text = caplog.text
    assert "turn-observe" in log_text
    assert "session-observe" in log_text
    assert "provider=fake" in log_text
    assert "exception_type=RuntimeError" in log_text
    assert "generate_stream" in log_text
    assert secret not in log_text
    assert sensitive_body not in log_text
