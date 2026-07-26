"""Framework-independent ownership of one interactive Agent runtime session."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from sjtuclaw.application.active_turn_coordinator import (
    ActiveTurnCoordinatorError,
    DefaultActiveTurnCoordinator,
)
from sjtuclaw.application.agent_loop import AgentLoop, CancellationToken
from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
    ProviderLifecycleState,
    ProviderProfileService,
    ProviderProfileServiceError,
)
from sjtuclaw.application.provider_settings_service import (
    ProviderSettingsService,
)
from sjtuclaw.domain.events import AgentEvent, AgentEventType
from sjtuclaw.domain.models import (
    AgentState,
    ChatMessage,
    MessageRole,
    ProfileId,
    ProviderContinuation,
    UserMessageCommand,
)
from sjtuclaw.domain.ports import LLMProvider


class RuntimeState(Enum):
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"


class RuntimeEventType(Enum):
    TURN_STARTED = "turn_started"
    AGENT_STATE_CHANGED = "agent_state_changed"
    TEXT_DELTA = "text_delta"
    TURN_COMPLETED = "turn_completed"
    TURN_CANCELLED = "turn_cancelled"
    TURN_FAILED = "turn_failed"
    TURN_SETTLED = "turn_settled"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """A Qt-safe event DTO that never contains continuation or secrets."""

    type: RuntimeEventType
    turn_id: str
    state: str = ""
    text: str = ""
    safe_code: str = ""
    safe_message: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """A non-sensitive immutable view of runtime-owned state."""

    runtime_state: str
    provider_lifecycle: str
    active_profile_id: str | None
    active_turn_id: str | None
    agent_state: str
    accepting_commands: bool
    retiring_provider_count: int
    candidate_cleanup_pending_count: int
    runtime_thread_id: int


@dataclass(frozen=True, slots=True)
class RuntimeCommandResult:
    success: bool
    safe_code: str
    safe_message: str

    @classmethod
    def ok(cls) -> RuntimeCommandResult:
        return cls(True, "none", "")

    @classmethod
    def failure(
        cls,
        safe_code: str,
        safe_message: str,
    ) -> RuntimeCommandResult:
        return cls(False, safe_code, safe_message)


class AgentLoopFactory(Protocol):
    def __call__(self, provider: LLMProvider) -> AgentLoop: ...


RuntimeEventSink = Callable[[RuntimeEvent], None]


class RuntimeSessionController:
    """Own Provider activation, one turn, history, and safe shutdown."""

    def __init__(
        self,
        provider_service: ProviderProfileService,
        turn_coordinator: DefaultActiveTurnCoordinator,
        agent_loop_factory: AgentLoopFactory,
        event_sink: RuntimeEventSink,
        *,
        runtime_thread_id: int,
    ) -> None:
        self._provider_service = provider_service
        self._turn_coordinator = turn_coordinator
        self._agent_loop_factory = agent_loop_factory
        self._event_sink = event_sink
        self._runtime_thread_id = runtime_thread_id
        self._state = RuntimeState.READY
        self._accepting_commands = True
        self._agent_loop: AgentLoop | None = None
        self._active_turn_task: asyncio.Task[None] | None = None
        self._turn_idle = asyncio.Event()
        self._turn_idle.set()
        self._histories: dict[str, list[ChatMessage]] = {}
        self._continuations: dict[
            tuple[str, ProfileId], ProviderContinuation
        ] = {}
        self._agent_state = AgentState.IDLE

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def provider_settings_service(self) -> ProviderSettingsService | None:
        """Expose the optional settings boundary only to RuntimeThread."""

        if isinstance(self._provider_service, ProviderSettingsService):
            return self._provider_service
        return None

    @property
    def active_turn_task(self) -> asyncio.Task[None] | None:
        return self._active_turn_task

    def history_for_session(
        self,
        session_id: str,
    ) -> tuple[ChatMessage, ...]:
        return tuple(self._histories.get(session_id, ()))

    def continuation_for(
        self,
        session_id: str,
        profile_id: ProfileId,
    ) -> ProviderContinuation | None:
        return self._continuations.get((session_id, profile_id))

    async def wait_until_turn_idle(self) -> None:
        """Wait without taking ownership of or cancelling the active task."""

        await self._turn_idle.wait()

    def snapshot(self) -> RuntimeSnapshot:
        runtime_profile_id = self._provider_service.runtime_profile_id
        return RuntimeSnapshot(
            runtime_state=self._state.value,
            provider_lifecycle=self._provider_service.lifecycle_state.value,
            active_profile_id=(
                None
                if runtime_profile_id is None
                else runtime_profile_id.value
            ),
            active_turn_id=self._turn_coordinator.current_turn_id,
            agent_state=self._agent_state.value,
            accepting_commands=self._accepting_commands,
            retiring_provider_count=(
                self._provider_service.retiring_provider_count
            ),
            candidate_cleanup_pending_count=(
                self._provider_service.candidate_cleanup_pending_count
            ),
            runtime_thread_id=self._runtime_thread_id,
        )

    async def activate_profile(
        self,
        profile_id: ProfileId,
        options: ProviderActivationOptions,
        turn_handling: ActiveTurnHandling | None,
    ) -> RuntimeCommandResult:
        unavailable = self._require_ready()
        if unavailable is not None:
            return unavailable
        if (
            self._turn_coordinator.has_active_turn
            and turn_handling is None
        ):
            return RuntimeCommandResult.failure(
                "switch_requires_turn_decision",
                "Choose whether to cancel or wait for the active turn.",
            )
        effective_handling = turn_handling
        if (
            effective_handling is None
            and self._provider_service.active_provider is not None
        ):
            effective_handling = ActiveTurnHandling.WAIT_FOR_ACTIVE
        try:
            provider = await self._provider_service.activate_profile(
                profile_id,
                options,
                turn_handling=effective_handling,
            )
            self._agent_loop = self._agent_loop_factory(provider)
        except asyncio.CancelledError:
            raise
        except (ProviderProfileServiceError, ActiveTurnCoordinatorError):
            return RuntimeCommandResult.failure(
                "provider_activation_failed",
                "The selected Provider could not be activated safely.",
            )
        except Exception:
            return RuntimeCommandResult.failure(
                "provider_activation_failed",
                "The selected Provider could not be activated safely.",
            )
        return RuntimeCommandResult.ok()

    async def start_turn(
        self,
        *,
        content: str,
        session_id: str,
    ) -> RuntimeCommandResult:
        unavailable = self._require_ready()
        if unavailable is not None:
            return unavailable
        if not content.strip() or not session_id.strip():
            return RuntimeCommandResult.failure(
                "invalid_command",
                "Message content and session identifier must not be blank.",
            )
        if self._turn_coordinator.has_active_turn:
            return RuntimeCommandResult.failure(
                "turn_already_running",
                "An Agent turn is already running.",
            )
        if (
            self._provider_service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        ):
            return RuntimeCommandResult.failure(
                "provider_cleanup_pending",
                "Provider cleanup must complete before starting a turn.",
            )
        profile_id = self._provider_service.runtime_profile_id
        agent_loop = self._agent_loop
        if (
            profile_id is None
            or agent_loop is None
            or self._provider_service.active_provider is None
        ):
            return RuntimeCommandResult.failure(
                "provider_not_active",
                "Activate a Provider profile before sending a message.",
            )

        command = UserMessageCommand.create(
            content.strip(),
            session_id=session_id.strip(),
        )
        cancellation = CancellationToken()
        task = asyncio.create_task(
            self._run_turn(
                agent_loop=agent_loop,
                command=command,
                profile_id=profile_id,
                cancellation=cancellation,
            ),
            name=f"sjtuclaw-turn-{command.turn_id}",
        )
        self._turn_idle.clear()
        try:
            self._turn_coordinator.bind_turn(
                task=task,
                cancellation=cancellation,
                turn_id=command.turn_id,
                profile_id=profile_id,
            )
        except Exception:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._turn_idle.set()
            return RuntimeCommandResult.failure(
                "turn_start_failed",
                "The Agent turn could not be started safely.",
            )
        self._active_turn_task = task
        task.add_done_callback(self._on_turn_done)
        return RuntimeCommandResult.ok()

    async def cancel_active_turn(self) -> RuntimeCommandResult:
        unavailable = self._require_ready()
        if unavailable is not None:
            return unavailable
        profile_id = self._turn_coordinator.current_profile_id
        if profile_id is None:
            return RuntimeCommandResult.failure(
                "no_active_turn",
                "There is no active Agent turn to cancel.",
            )
        try:
            await self._turn_coordinator.prepare_for_provider_switch(
                old_profile_id=profile_id,
                new_profile_id=profile_id,
                handling=ActiveTurnHandling.CANCEL_ACTIVE,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return RuntimeCommandResult.failure(
                "turn_cancel_failed",
                "The active Agent turn could not be cancelled safely.",
            )
        return RuntimeCommandResult.ok()

    async def shutdown(
        self,
        *,
        cancel_active: bool,
    ) -> RuntimeCommandResult:
        if self._state is RuntimeState.CLOSED:
            return RuntimeCommandResult.ok()
        self._state = RuntimeState.CLOSING
        self._accepting_commands = False
        profile_id = self._turn_coordinator.current_profile_id
        if profile_id is not None:
            handling = (
                ActiveTurnHandling.CANCEL_ACTIVE
                if cancel_active
                else ActiveTurnHandling.WAIT_FOR_ACTIVE
            )
            try:
                await self._turn_coordinator.prepare_for_provider_switch(
                    old_profile_id=profile_id,
                    new_profile_id=profile_id,
                    handling=handling,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                return RuntimeCommandResult.failure(
                    "shutdown_turn_cleanup_failed",
                    "The active turn could not be quiesced safely.",
                )
        try:
            await self._provider_service.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            return RuntimeCommandResult.failure(
                "shutdown_provider_cleanup_failed",
                "Provider cleanup did not complete safely.",
            )
        self._agent_loop = None
        self._state = RuntimeState.CLOSED
        self._agent_state = AgentState.IDLE
        return RuntimeCommandResult.ok()

    async def _run_turn(
        self,
        *,
        agent_loop: AgentLoop,
        command: UserMessageCommand,
        profile_id: ProfileId,
        cancellation: CancellationToken,
    ) -> None:
        history = tuple(self._histories.get(command.session_id, ()))
        continuation = self._continuations.get(
            (command.session_id, profile_id)
        )
        terminal_event: AgentEvent | None = None
        try:
            async for event in agent_loop.run(
                command,
                history=history,
                cancellation=cancellation,
                continuation=continuation,
            ):
                if event.type is AgentEventType.TURN_COMPLETED:
                    self._commit_completed_turn(
                        command=command,
                        profile_id=profile_id,
                        event=event,
                    )
                self._process_agent_event(event)
                if event.type in {
                    AgentEventType.TURN_COMPLETED,
                    AgentEventType.TURN_CANCELLED,
                    AgentEventType.TURN_FAILED,
                }:
                    terminal_event = event
                    self._turn_coordinator.mark_terminal(command.turn_id)
            if terminal_event is None:
                self._emit(
                    RuntimeEvent(
                        type=RuntimeEventType.TURN_FAILED,
                        turn_id=command.turn_id,
                        safe_code="invalid_agent_result",
                        safe_message=(
                            "The Agent turn ended without a terminal result."
                        ),
                    )
                )
                self._turn_coordinator.mark_terminal(command.turn_id)
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TURN_FAILED,
                    turn_id=command.turn_id,
                    safe_code="runtime_turn_failed",
                    safe_message="The Agent turn failed safely.",
                )
            )
            self._turn_coordinator.mark_terminal(command.turn_id)

    def _process_agent_event(self, event: AgentEvent) -> None:
        if event.type is AgentEventType.TURN_STARTED:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TURN_STARTED,
                    turn_id=event.turn_id,
                )
            )
        elif event.type is AgentEventType.STATE_CHANGED:
            state = event.state or AgentState.ERROR
            self._agent_state = state
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.AGENT_STATE_CHANGED,
                    turn_id=event.turn_id,
                    state=state.value,
                )
            )
        elif event.type is AgentEventType.TEXT_DELTA:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TEXT_DELTA,
                    turn_id=event.turn_id,
                    text=event.text,
                )
            )
        elif event.type is AgentEventType.TURN_COMPLETED:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TURN_COMPLETED,
                    turn_id=event.turn_id,
                    text=event.text,
                )
            )
        elif event.type is AgentEventType.TURN_CANCELLED:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TURN_CANCELLED,
                    turn_id=event.turn_id,
                )
            )
        elif event.type is AgentEventType.TURN_FAILED:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TURN_FAILED,
                    turn_id=event.turn_id,
                    safe_code=event.error_code,
                    safe_message=event.error_message,
                )
            )

    def _commit_completed_turn(
        self,
        *,
        command: UserMessageCommand,
        profile_id: ProfileId,
        event: AgentEvent,
    ) -> None:
        history = self._histories.setdefault(command.session_id, [])
        history.extend(
            (
                ChatMessage(
                    role=MessageRole.USER,
                    content=command.content,
                ),
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=event.text,
                ),
            )
        )
        key = (command.session_id, profile_id)
        if event.continuation is None:
            self._continuations.pop(key, None)
        else:
            self._continuations[key] = event.continuation

    def _on_turn_done(self, task: asyncio.Task[None]) -> None:
        turn_id = self._turn_coordinator.current_turn_id
        self._turn_coordinator.release_finished_turn(task)
        if self._active_turn_task is task:
            self._active_turn_task = None
        self._turn_idle.set()
        if turn_id is not None:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.TURN_SETTLED,
                    turn_id=turn_id,
                )
            )

    def _emit(self, event: RuntimeEvent) -> None:
        try:
            self._event_sink(event)
        except Exception:
            return

    def _require_ready(self) -> RuntimeCommandResult | None:
        if self._state is RuntimeState.CLOSING:
            return RuntimeCommandResult.failure(
                "runtime_closing",
                "The runtime is closing and cannot accept this command.",
            )
        if self._state is RuntimeState.CLOSED:
            return RuntimeCommandResult.failure(
                "runtime_closed",
                "The runtime is closed.",
            )
        if not self._accepting_commands:
            return RuntimeCommandResult.failure(
                "runtime_not_ready",
                "The runtime is not accepting commands.",
            )
        return None
