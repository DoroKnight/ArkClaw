"""Non-blocking GUI-thread bridge to the persistent runtime thread."""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal, Slot

from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
)
from sjtuclaw.application.provider_settings_service import (
    ProviderSettingsSnapshot,
)
from sjtuclaw.application.runtime_session_controller import (
    RuntimeEvent,
    RuntimeEventType,
    RuntimeSnapshot,
)
from sjtuclaw.presentation.qt.runtime_thread import (
    RuntimeControllerFactory,
    RuntimeThread,
    RuntimeThreadCommand,
    RuntimeThreadCommandType,
)


class _BridgeState(Enum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class QtRuntimeBridge(QObject):
    """GUI-owned QObject exposing command methods and safe Qt signals."""

    runtime_ready = Signal()
    runtime_state_changed = Signal(object)
    provider_lifecycle_changed = Signal(object)
    turn_started = Signal(str)
    agent_state_changed = Signal(str, str)
    text_delta = Signal(str, str)
    turn_completed = Signal(str, str)
    turn_cancelled = Signal(str)
    turn_failed = Signal(str, str, str)
    command_completed = Signal(str)
    command_failed = Signal(str, str, str)
    provider_settings_changed = Signal(str, object)
    shutdown_finished = Signal(bool, str)

    def __init__(
        self,
        controller_factory: RuntimeControllerFactory,
    ) -> None:
        super().__init__()
        self._thread = RuntimeThread(controller_factory)
        self._state = _BridgeState.NEW
        self._start_command_id: str | None = None
        self._shutdown_command_id: str | None = None
        self._shutdown_outcome: tuple[str, bool, str, str] | None = None
        self._pending_command_ids: set[str] = set()
        self._protocol_failure: tuple[str, str] | None = None
        connection = Qt.ConnectionType.QueuedConnection
        self._thread.worker_ready.connect(
            self._on_worker_ready,
            connection,
        )
        self._thread.runtime_event_emitted.connect(
            self._relay_runtime_event,
            connection,
        )
        self._thread.snapshot_emitted.connect(
            self._relay_snapshot,
            connection,
        )
        self._thread.provider_settings_emitted.connect(
            self._relay_provider_settings,
            connection,
        )
        self._thread.command_result_emitted.connect(
            self._on_command_result,
            connection,
        )
        self._thread.shutdown_outcome_emitted.connect(
            self._on_shutdown_outcome,
            connection,
        )
        self._thread.finished.connect(
            self._on_thread_finished,
            connection,
        )

    @property
    def runtime_thread(self) -> RuntimeThread:
        """Expose only the QThread handle for ownership tests and diagnostics."""

        return self._thread

    def start_runtime(self) -> str:
        command_id = self._new_command_id()
        if self._state is not _BridgeState.NEW:
            self._fail_command(
                command_id,
                "runtime_already_started",
                "The runtime has already been started.",
            )
            return command_id
        self._state = _BridgeState.STARTING
        self._start_command_id = command_id
        try:
            self._thread.start()
        except RuntimeError:
            self._state = _BridgeState.FAILED
            self._start_command_id = None
            self._fail_command(
                command_id,
                "runtime_start_failed",
                "The runtime thread could not be started safely.",
            )
        return command_id

    def activate_profile(
        self,
        profile_id: str,
        options: ProviderActivationOptions,
        turn_handling: ActiveTurnHandling | None,
    ) -> str:
        command_id = self._new_command_id()
        if not profile_id.strip():
            self._fail_command(
                command_id,
                "invalid_command",
                "The Provider profile identifier must not be blank.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.ACTIVATE_PROFILE,
                profile_id=profile_id.strip(),
                options=options,
                turn_handling=turn_handling,
            )
        )

    def send_message(self, content: str, session_id: str) -> str:
        command_id = self._new_command_id()
        if not content.strip() or not session_id.strip():
            self._fail_command(
                command_id,
                "invalid_command",
                "Message content and session identifier must not be blank.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.SEND_MESSAGE,
                content=content.strip(),
                session_id=session_id.strip(),
            )
        )

    def cancel_active_turn(self) -> str:
        return self._submit(
            RuntimeThreadCommand(
                command_id=self._new_command_id(),
                type=RuntimeThreadCommandType.CANCEL_ACTIVE_TURN,
            )
        )

    def request_snapshot(self) -> str:
        return self._submit(
            RuntimeThreadCommand(
                command_id=self._new_command_id(),
                type=RuntimeThreadCommandType.REQUEST_SNAPSHOT,
            )
        )

    def request_provider_settings(self) -> str:
        return self._submit(
            RuntimeThreadCommand(
                command_id=self._new_command_id(),
                type=RuntimeThreadCommandType.REQUEST_PROVIDER_SETTINGS,
            )
        )

    def create_provider_profile(
        self,
        *,
        provider_id: str,
        display_name: str,
        model: str,
        credential_id: str | None,
    ) -> str:
        command_id = self._new_command_id()
        if (
            not provider_id.strip()
            or not display_name.strip()
            or not model.strip()
        ):
            self._fail_command(
                command_id,
                "invalid_command",
                "Provider, display name, and model are required.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.CREATE_PROVIDER_PROFILE,
                provider_id=provider_id.strip(),
                display_name=display_name.strip(),
                model=model.strip(),
                credential_id=(
                    "" if credential_id is None else credential_id.strip()
                ),
            )
        )

    def update_provider_profile(
        self,
        *,
        profile_id: str,
        display_name: str,
        model: str,
        credential_id: str | None,
    ) -> str:
        command_id = self._new_command_id()
        if (
            not profile_id.strip()
            or not display_name.strip()
            or not model.strip()
        ):
            self._fail_command(
                command_id,
                "invalid_command",
                "Profile, display name, and model are required.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.UPDATE_PROVIDER_PROFILE,
                profile_id=profile_id.strip(),
                display_name=display_name.strip(),
                model=model.strip(),
                credential_id=(
                    "" if credential_id is None else credential_id.strip()
                ),
            )
        )

    def delete_provider_profile(self, profile_id: str) -> str:
        command_id = self._new_command_id()
        if not profile_id.strip():
            self._fail_command(
                command_id,
                "invalid_command",
                "The Provider profile identifier is required.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.DELETE_PROVIDER_PROFILE,
                profile_id=profile_id.strip(),
            )
        )

    def save_provider_credential(
        self,
        credential_id: str,
        secret: str,
    ) -> str:
        command_id = self._new_command_id()
        if not credential_id.strip() or not secret.strip():
            self._fail_command(
                command_id,
                "invalid_command",
                "Credential identifier and value are required.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.SAVE_PROVIDER_CREDENTIAL,
                credential_id=credential_id.strip(),
                secret=secret,
            )
        )

    def delete_provider_credential(self, credential_id: str) -> str:
        command_id = self._new_command_id()
        if not credential_id.strip():
            self._fail_command(
                command_id,
                "invalid_command",
                "The credential identifier is required.",
            )
            return command_id
        return self._submit(
            RuntimeThreadCommand(
                command_id=command_id,
                type=RuntimeThreadCommandType.DELETE_PROVIDER_CREDENTIAL,
                credential_id=credential_id.strip(),
            )
        )

    def shutdown(self, cancel_active: bool) -> str:
        command_id = self._new_command_id()
        if self._state is _BridgeState.NEW:
            self._state = _BridgeState.CLOSED
            self._complete_command(command_id)
            self.shutdown_finished.emit(True, "none")
            return command_id
        if self._state is _BridgeState.CLOSED:
            self._complete_command(command_id)
            self.shutdown_finished.emit(True, "runtime_already_closed")
            return command_id
        if self._state is _BridgeState.FAILED:
            self._fail_command(
                command_id,
                "runtime_failed",
                "The runtime has already failed.",
            )
            return command_id
        if self._shutdown_command_id is not None:
            self._fail_command(
                command_id,
                "shutdown_in_progress",
                "Runtime shutdown is already in progress.",
            )
            return command_id
        self._state = _BridgeState.CLOSING
        self._shutdown_command_id = command_id
        command = RuntimeThreadCommand(
            command_id=command_id,
            type=RuntimeThreadCommandType.SHUTDOWN,
            cancel_active=cancel_active,
        )
        self._thread.request_shutdown(command)
        return command_id

    def _submit(self, command: RuntimeThreadCommand) -> str:
        if self._state is _BridgeState.STARTING:
            self._fail_command(
                command.command_id,
                "runtime_not_ready",
                "Wait for runtime_ready before sending commands.",
            )
            return command.command_id
        if self._state is _BridgeState.CLOSING:
            self._fail_command(
                command.command_id,
                "runtime_closing",
                "The runtime is closing.",
            )
            return command.command_id
        if self._state in {_BridgeState.CLOSED, _BridgeState.FAILED}:
            self._fail_command(
                command.command_id,
                "runtime_closed",
                "The runtime is closed.",
            )
            return command.command_id
        if self._state is not _BridgeState.READY:
            self._fail_command(
                command.command_id,
                "runtime_not_ready",
                "The runtime is not ready.",
            )
            return command.command_id
        if not self._thread.submit(command):
            self._fail_command(
                command.command_id,
                "runtime_not_ready",
                "The runtime cannot accept commands.",
            )
        return command.command_id

    @Slot(object)
    def _on_worker_ready(self, snapshot: object) -> None:
        if not isinstance(snapshot, RuntimeSnapshot):
            self._state = _BridgeState.CLOSING
            self._protocol_failure = (
                "runtime_bootstrap_failed",
                "The runtime returned an invalid startup snapshot.",
            )
            if self._start_command_id is not None:
                self._fail_command(
                    self._start_command_id,
                    *self._protocol_failure,
                )
                self._start_command_id = None
            self._thread.request_shutdown(
                RuntimeThreadCommand(
                    command_id=f"internal-{uuid4()}",
                    type=RuntimeThreadCommandType.SHUTDOWN,
                    cancel_active=True,
                )
            )
            return
        if self._state is _BridgeState.CLOSING:
            return
        if self._state is not _BridgeState.STARTING:
            return
        self._state = _BridgeState.READY
        self.runtime_ready.emit()
        self.runtime_state_changed.emit(snapshot)
        self.provider_lifecycle_changed.emit(snapshot)
        if self._start_command_id is not None:
            self._complete_command(self._start_command_id)
            self._start_command_id = None

    @Slot(object)
    def _relay_runtime_event(self, value: object) -> None:
        if not isinstance(value, RuntimeEvent):
            return
        if value.type is RuntimeEventType.TURN_STARTED:
            self.turn_started.emit(value.turn_id)
        elif value.type is RuntimeEventType.AGENT_STATE_CHANGED:
            self.agent_state_changed.emit(value.turn_id, value.state)
        elif value.type is RuntimeEventType.TEXT_DELTA:
            self.text_delta.emit(value.turn_id, value.text)
        elif value.type is RuntimeEventType.TURN_COMPLETED:
            self.turn_completed.emit(value.turn_id, value.text)
        elif value.type is RuntimeEventType.TURN_CANCELLED:
            self.turn_cancelled.emit(value.turn_id)
        elif value.type is RuntimeEventType.TURN_FAILED:
            self.turn_failed.emit(
                value.turn_id,
                value.safe_code,
                value.safe_message,
            )

    @Slot(object)
    def _relay_snapshot(self, value: object) -> None:
        if not isinstance(value, RuntimeSnapshot):
            return
        self.runtime_state_changed.emit(value)
        self.provider_lifecycle_changed.emit(value)

    @Slot(str, object)
    def _relay_provider_settings(
        self,
        command_id: str,
        value: object,
    ) -> None:
        if (
            command_id not in self._pending_command_ids
            or not isinstance(value, ProviderSettingsSnapshot)
        ):
            return
        self.provider_settings_changed.emit(command_id, value)

    @Slot(str, bool, str, str)
    def _on_command_result(
        self,
        command_id: str,
        success: bool,
        safe_code: str,
        safe_message: str,
    ) -> None:
        if command_id not in self._pending_command_ids:
            return
        if success:
            self._complete_command(command_id)
            return
        if command_id == self._shutdown_command_id:
            self._shutdown_command_id = None
            self.shutdown_finished.emit(False, safe_code)
        self._fail_command(
            command_id,
            safe_code,
            safe_message,
        )

    @Slot(str, bool, str, str)
    def _on_shutdown_outcome(
        self,
        command_id: str,
        success: bool,
        safe_code: str,
        safe_message: str,
    ) -> None:
        self._shutdown_outcome = (
            command_id,
            success,
            safe_code,
            safe_message,
        )

    @Slot()
    def _on_thread_finished(self) -> None:
        outcome = self._shutdown_outcome
        self._shutdown_outcome = None
        protocol_failure = self._protocol_failure
        self._protocol_failure = None
        if protocol_failure is not None:
            safe_code, safe_message = protocol_failure
            self._state = _BridgeState.FAILED
            self._fail_all_pending(safe_code, safe_message)
            self._start_command_id = None
            self._shutdown_command_id = None
            self.shutdown_finished.emit(False, safe_code)
            return
        if outcome is None:
            self._state = _BridgeState.FAILED
            self._fail_all_pending(
                "runtime_thread_stopped_unexpectedly",
                "The runtime thread stopped unexpectedly.",
            )
            self._start_command_id = None
            self._shutdown_command_id = None
            self.shutdown_finished.emit(
                False,
                "runtime_thread_stopped_unexpectedly",
            )
            return
        command_id, success, safe_code, safe_message = outcome
        if safe_code == "runtime_bootstrap_failed":
            self._state = _BridgeState.FAILED
            self._fail_all_pending(safe_code, safe_message)
            self._start_command_id = None
        else:
            if self._start_command_id is not None:
                self._complete_command(self._start_command_id)
                self._start_command_id = None
            if success:
                self._complete_command(command_id)
                self._fail_all_pending(
                    "runtime_closed",
                    "The runtime closed before the command was processed.",
                )
            else:
                self._fail_command(
                    command_id,
                    safe_code,
                    safe_message,
                )
                if safe_code in {
                    "runtime_command_cancelled",
                    "runtime_shutdown_cancelled",
                    "runtime_thread_cancelled",
                }:
                    self._fail_all_pending(
                        "runtime_thread_cancelled",
                        "The runtime thread was cancelled safely.",
                    )
                else:
                    self._fail_all_pending(
                        "runtime_thread_stopped_unexpectedly",
                        "The runtime thread stopped unexpectedly.",
                    )
        if success:
            self._state = _BridgeState.CLOSED
        else:
            self._state = _BridgeState.FAILED
        self._shutdown_command_id = None
        self.shutdown_finished.emit(success, safe_code)

    def _new_command_id(self) -> str:
        command_id = str(uuid4())
        while command_id in self._pending_command_ids:
            command_id = str(uuid4())
        self._pending_command_ids.add(command_id)
        return command_id

    def _complete_command(self, command_id: str) -> bool:
        if command_id not in self._pending_command_ids:
            return False
        self._pending_command_ids.remove(command_id)
        self.command_completed.emit(command_id)
        return True

    def _fail_command(
        self,
        command_id: str,
        safe_code: str,
        safe_message: str,
    ) -> bool:
        if command_id not in self._pending_command_ids:
            return False
        self._pending_command_ids.remove(command_id)
        self.command_failed.emit(command_id, safe_code, safe_message)
        return True

    def _fail_all_pending(
        self,
        safe_code: str,
        safe_message: str,
    ) -> None:
        for command_id in tuple(self._pending_command_ids):
            self._fail_command(command_id, safe_code, safe_message)
