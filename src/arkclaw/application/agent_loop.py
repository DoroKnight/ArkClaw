"""The first provider-independent ArkClaw Agent Loop."""

from __future__ import annotations

import asyncio
import logging
import math
import traceback
from collections.abc import AsyncIterator, Sequence

from arkclaw.application.context_manager import ContextManager
from arkclaw.domain.errors import (
    ContextBudgetError,
    InvalidProviderEventError,
    ProviderError,
)
from arkclaw.domain.events import AgentEvent, LLMEvent, LLMEventType
from arkclaw.domain.models import (
    AgentState,
    ChatMessage,
    MemoryRecord,
    ProviderContinuation,
    ToolSpec,
    UserMessageCommand,
)
from arkclaw.domain.ports import LLMProvider

logger = logging.getLogger(__name__)


class CancellationToken:
    """Cooperative cancellation token for a running turn."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError

    async def wait(self) -> None:
        """Wait until cooperative cancellation is requested."""

        await self._event.wait()


type _ProviderReadResult = tuple[str, LLMEvent | None]


async def _read_next_event(stream: AsyncIterator[LLMEvent]) -> _ProviderReadResult:
    try:
        return ("event", await anext(stream))
    except StopAsyncIteration:
        return ("eof", None)


async def _wait_for_cancellation(token: CancellationToken) -> _ProviderReadResult:
    await token.wait()
    return ("cancelled", None)


async def _close_provider_stream(stream: AsyncIterator[LLMEvent]) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


def _invalid_provider_stream() -> InvalidProviderEventError:
    return InvalidProviderEventError(
        "invalid_provider_stream",
        "The provider returned an invalid event stream.",
    )


class AgentLoop:
    """Stream normalized Agent events while failing closed on tool calls."""

    def __init__(
        self,
        provider: LLMProvider,
        context_manager: ContextManager,
        *,
        max_turn_seconds: float = 90.0,
    ) -> None:
        if (
            isinstance(max_turn_seconds, bool)
            or not isinstance(max_turn_seconds, (int, float))
            or not math.isfinite(max_turn_seconds)
            or max_turn_seconds <= 0
        ):
            raise ValueError("max_turn_seconds must be a finite positive number")
        self._provider = provider
        self._context_manager = context_manager
        self._max_turn_seconds = max_turn_seconds

    async def run(
        self,
        command: UserMessageCommand,
        *,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[MemoryRecord] = (),
        tools: Sequence[ToolSpec] = (),
        cancellation: CancellationToken | None = None,
        continuation: ProviderContinuation | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one user turn and stream events to the caller."""

        token = cancellation or CancellationToken()
        turn_id = command.turn_id
        yield AgentEvent.started(turn_id)
        yield AgentEvent.state_changed(turn_id, AgentState.LISTENING)

        try:
            if token.cancelled:
                yield AgentEvent.cancelled(turn_id)
                yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
                return
            if (
                continuation is not None
                and continuation.provider_name != self._provider.name
            ):
                raise ProviderError(
                    "provider_continuation_mismatch",
                    "The continuation does not belong to the selected provider.",
                )

            request = self._context_manager.build_request(
                command,
                history=history,
                memories=memories,
                tools=tools,
                continuation=continuation,
            )
            yield AgentEvent.state_changed(turn_id, AgentState.THINKING)

            text_parts: list[str] = []
            speaking = False
            terminal_type: LLMEventType | None = None
            provider_failure: tuple[str, str] | None = None
            completed_continuation: ProviderContinuation | None = None
            cooperatively_cancelled = False
            stream = self._provider.generate_stream(request)
            cancellation_task = asyncio.create_task(_wait_for_cancellation(token))
            next_event_task: asyncio.Task[_ProviderReadResult] | None = None

            try:
                async with asyncio.timeout(self._max_turn_seconds):
                    while True:
                        next_event_task = asyncio.create_task(_read_next_event(stream))
                        done, _ = await asyncio.wait(
                            (next_event_task, cancellation_task),
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        if cancellation_task in done:
                            cooperatively_cancelled = True
                            break

                        result_type, event = next_event_task.result()
                        next_event_task = None
                        if result_type == "eof":
                            break
                        if event is None:
                            raise _invalid_provider_stream()
                        if terminal_type is not None:
                            raise _invalid_provider_stream()
                        if (
                            event.continuation is not None
                            and event.type is not LLMEventType.COMPLETED
                        ):
                            raise _invalid_provider_stream()

                        if event.type is LLMEventType.TEXT_DELTA:
                            if not event.text:
                                raise _invalid_provider_stream()
                            if not speaking:
                                speaking = True
                                yield AgentEvent.state_changed(turn_id, AgentState.SPEAKING)
                            text_parts.append(event.text)
                            yield AgentEvent.delta(turn_id, event.text)
                            continue

                        if event.type is LLMEventType.TOOL_CALL:
                            if event.tool_call is None:
                                raise _invalid_provider_stream()
                            yield AgentEvent.state_changed(turn_id, AgentState.ERROR)
                            yield AgentEvent.failed(
                                turn_id,
                                "tool_execution_not_configured",
                                "Tool execution is disabled until ToolService and "
                                "user approval are connected.",
                            )
                            yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
                            return

                        if event.type is LLMEventType.ERROR:
                            if not event.error_code or not event.error_message:
                                raise _invalid_provider_stream()
                            terminal_type = event.type
                            provider_failure = (event.error_code, event.error_message)
                            continue

                        if event.type is LLMEventType.COMPLETED:
                            if (
                                event.continuation is not None
                                and event.continuation.provider_name
                                != self._provider.name
                            ):
                                raise ProviderError(
                                    "provider_continuation_mismatch",
                                    "The provider returned continuation state "
                                    "for a different provider.",
                                )
                            terminal_type = event.type
                            completed_continuation = event.continuation
                            continue

                        raise _invalid_provider_stream()
            finally:
                if next_event_task is not None:
                    next_event_task.cancel()
                    await asyncio.gather(next_event_task, return_exceptions=True)
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)
                await _close_provider_stream(stream)

            if cooperatively_cancelled or token.cancelled:
                yield AgentEvent.cancelled(turn_id)
                yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
                return

            if terminal_type is None:
                raise _invalid_provider_stream()
            if terminal_type is LLMEventType.ERROR:
                if provider_failure is None:
                    raise _invalid_provider_stream()
                raise ProviderError(*provider_failure)

            final_text = "".join(text_parts)
            yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
            yield AgentEvent.completed(turn_id, final_text, completed_continuation)

        except TimeoutError:
            yield AgentEvent.state_changed(turn_id, AgentState.ERROR)
            yield AgentEvent.failed(
                turn_id,
                "turn_timeout",
                f"The Agent turn exceeded {self._max_turn_seconds:g} seconds.",
            )
            yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
        except ContextBudgetError as error:
            yield AgentEvent.state_changed(turn_id, AgentState.ERROR)
            yield AgentEvent.failed(turn_id, "context_budget_exceeded", str(error))
            yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
        except ProviderError as error:
            yield AgentEvent.state_changed(turn_id, AgentState.ERROR)
            yield AgentEvent.failed(turn_id, error.code, error.message)
            yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
        except Exception as error:
            safe_traceback = "".join(traceback.format_tb(error.__traceback__))
            logger.error(
                "Unexpected Agent turn failure: turn_id=%s session_id=%s "
                "provider=%s exception_type=%s\n%s",
                turn_id,
                command.session_id,
                self._provider.name,
                type(error).__name__,
                safe_traceback,
            )
            yield AgentEvent.state_changed(turn_id, AgentState.ERROR)
            yield AgentEvent.failed(
                turn_id,
                "unexpected_agent_error",
                "The Agent turn failed unexpectedly.",
            )
            yield AgentEvent.state_changed(turn_id, AgentState.IDLE)
