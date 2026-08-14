import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import ClassVar

import pytest

import arkclaw.__main__ as cli
from arkclaw.config.models import RuntimeConfig
from arkclaw.domain.events import AgentEvent
from arkclaw.domain.models import (
    ChatMessage,
    ProviderContinuation,
    UserMessageCommand,
)
from arkclaw.infrastructure.llm.provider_factory import ProviderFactory


class _StubProvider:
    name = "fake"

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _RecordingAgent:
    scripts: ClassVar[list[tuple[AgentEvent, ...]]] = []
    histories: ClassVar[list[tuple[ChatMessage, ...]]] = []
    continuations: ClassVar[list[ProviderContinuation | None]] = []
    max_turn_seconds_values: ClassVar[list[float]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args
        max_turn_seconds = kwargs["max_turn_seconds"]
        assert isinstance(max_turn_seconds, (int, float))
        self.max_turn_seconds_values.append(float(max_turn_seconds))

    async def run(
        self,
        command: UserMessageCommand,
        *,
        history: Sequence[ChatMessage] = (),
        continuation: ProviderContinuation | None = None,
        **kwargs: object,
    ) -> AsyncIterator[AgentEvent]:
        del command, kwargs
        self.histories.append(tuple(history))
        self.continuations.append(continuation)
        for event in self.scripts.pop(0):
            yield event


@pytest.mark.parametrize(
    ("first_events", "expected_history"),
    [
        (
            (
                AgentEvent.delta("turn-1", "draft"),
                AgentEvent.failed("turn-1", "provider_error", "Provider failed."),
            ),
            [],
        ),
        (
            (
                AgentEvent.delta("turn-1", "draft"),
                AgentEvent.cancelled("turn-1"),
            ),
            [],
        ),
        (
            (
                AgentEvent.delta("turn-1", "draft"),
                AgentEvent.failed(
                    "turn-1",
                    "tool_execution_not_configured",
                    "Tool execution is disabled.",
                ),
            ),
            [],
        ),
        (
            (
                AgentEvent.delta("turn-1", "draft"),
                AgentEvent.completed("turn-1", "final answer"),
            ),
            ["first", "final answer"],
        ),
    ],
    ids=["provider-error", "cancelled", "tool-rejected", "completed"],
)
def test_cli_commits_history_only_after_turn_completed(
    monkeypatch: pytest.MonkeyPatch,
    first_events: tuple[AgentEvent, ...],
    expected_history: list[str],
) -> None:
    _RecordingAgent.scripts = [
        first_events,
        (AgentEvent.completed("turn-2", "second answer"),),
    ]
    _RecordingAgent.histories = []
    _RecordingAgent.continuations = []
    _RecordingAgent.max_turn_seconds_values = []
    provider = _StubProvider()

    def create_provider(_factory: object, _config: RuntimeConfig) -> _StubProvider:
        return provider

    user_inputs = iter(("first", "second", "/quit"))

    def read_input(_prompt: str = "") -> str:
        return next(user_inputs)

    monkeypatch.setattr(ProviderFactory, "create", create_provider)
    monkeypatch.setattr(cli, "AgentLoop", _RecordingAgent)
    monkeypatch.setattr("builtins.input", read_input)

    asyncio.run(cli._run_demo(RuntimeConfig()))

    assert [message.content for message in _RecordingAgent.histories[1]] == expected_history
    assert provider.closed


def test_cli_uses_max_turn_timeout_not_provider_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _StubProvider()
    _RecordingAgent.scripts = []
    _RecordingAgent.histories = []
    _RecordingAgent.continuations = []
    _RecordingAgent.max_turn_seconds_values = []

    monkeypatch.setattr(ProviderFactory, "create", lambda _self, _config: provider)
    monkeypatch.setattr(cli, "AgentLoop", _RecordingAgent)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "/quit")

    asyncio.run(
        cli._run_demo(
            RuntimeConfig(
                provider_timeout_seconds=0.001,
                max_turn_seconds=12.5,
            )
        )
    )

    assert _RecordingAgent.max_turn_seconds_values == [12.5]
    assert provider.closed


def test_cli_passes_successful_continuation_to_next_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _StubProvider()
    continuation = ProviderContinuation("fake", b"opaque-state", version="1")
    _RecordingAgent.scripts = [
        (AgentEvent.completed("turn-1", "first answer", continuation),),
        (AgentEvent.completed("turn-2", "second answer"),),
    ]
    _RecordingAgent.histories = []
    _RecordingAgent.continuations = []
    _RecordingAgent.max_turn_seconds_values = []
    user_inputs = iter(("first", "second", "/quit"))

    monkeypatch.setattr(ProviderFactory, "create", lambda _self, _config: provider)
    monkeypatch.setattr(cli, "AgentLoop", _RecordingAgent)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(user_inputs))

    asyncio.run(cli._run_demo(RuntimeConfig()))

    assert _RecordingAgent.continuations == [None, continuation]
    assert provider.closed


class _FailingCloseProvider(_StubProvider):
    async def aclose(self) -> None:
        self.closed = True
        raise RuntimeError("sensitive-close-details")


def test_cli_handles_provider_close_failure_safely(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _FailingCloseProvider()
    _RecordingAgent.scripts = []
    _RecordingAgent.max_turn_seconds_values = []
    caplog.set_level(logging.ERROR, logger="arkclaw.__main__")

    monkeypatch.setattr(ProviderFactory, "create", lambda _self, _config: provider)
    monkeypatch.setattr(cli, "AgentLoop", _RecordingAgent)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "/quit")

    asyncio.run(cli._run_demo(RuntimeConfig()))

    assert provider.closed
    assert "exception_type=RuntimeError" in caplog.text
    assert "sensitive-close-details" not in caplog.text


class _ExplodingAgent:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def run(
        self,
        command: UserMessageCommand,
        **kwargs: object,
    ) -> AsyncIterator[AgentEvent]:
        del command, kwargs
        if False:
            yield AgentEvent.completed("unreachable", "")
        raise RuntimeError("turn failed")


def test_cli_closes_provider_when_turn_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _StubProvider()
    user_inputs = iter(("hello",))

    monkeypatch.setattr(ProviderFactory, "create", lambda _self, _config: provider)
    monkeypatch.setattr(cli, "AgentLoop", _ExplodingAgent)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(user_inputs))

    with pytest.raises(RuntimeError, match="turn failed"):
        asyncio.run(cli._run_demo(RuntimeConfig()))

    assert provider.closed


@pytest.mark.parametrize("exit_signal", [EOFError(), KeyboardInterrupt()])
def test_cli_closes_provider_on_terminal_input_exit(
    monkeypatch: pytest.MonkeyPatch,
    exit_signal: BaseException,
) -> None:
    provider = _StubProvider()
    _RecordingAgent.max_turn_seconds_values = []

    def stop_input(_prompt: str = "") -> str:
        raise exit_signal

    monkeypatch.setattr(ProviderFactory, "create", lambda _self, _config: provider)
    monkeypatch.setattr(cli, "AgentLoop", _RecordingAgent)
    monkeypatch.setattr("builtins.input", stop_input)

    asyncio.run(cli._run_demo(RuntimeConfig()))

    assert provider.closed


class _SlowCloseProvider(_StubProvider):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def aclose(self) -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            self.cancelled = True


def test_cli_bounds_provider_close_time(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _SlowCloseProvider()
    _RecordingAgent.scripts = []
    _RecordingAgent.max_turn_seconds_values = []
    caplog.set_level(logging.ERROR, logger="arkclaw.__main__")

    monkeypatch.setattr(ProviderFactory, "create", lambda _self, _config: provider)
    monkeypatch.setattr(cli, "AgentLoop", _RecordingAgent)
    monkeypatch.setattr(cli, "_PROVIDER_CLOSE_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "/quit")

    asyncio.run(cli._run_demo(RuntimeConfig()))

    assert provider.cancelled
    assert "Provider close timed out" in caplog.text
