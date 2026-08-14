"""GUI-thread shared state for the RuntimeThread-owned autostart service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot

from arkclaw.application.system.autostart_operation_journal import (
    AutostartOperationContext,
    AutostartOperationEvent,
    AutostartOperationJournal,
    AutostartOperationJournalError,
    AutostartOperationOrigin,
    AutostartOperationRuntimeState,
)
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge


@dataclass(frozen=True, slots=True)
class _PendingAutostartOperation:
    context: AutostartOperationContext
    mutation: bool


class AutostartUiController(QObject):
    """Keep one shared, revision-ordered state for every autostart UI."""

    state_changed = Signal(object)
    operation_failed = Signal(str, str)

    def __init__(
        self,
        bridge: QtRuntimeBridge,
        parent: QObject | None = None,
        *,
        operation_journal: AutostartOperationJournal | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._operation_journal = operation_journal
        self._snapshot = AutostartSnapshot.for_status(
            AutostartStatus.UNAVAILABLE
        )
        self._busy = False
        self._closing = False
        self._last_error: tuple[str, str] | None = None
        self._pending: dict[str, _PendingAutostartOperation] = {}
        self._revision = 0
        self._latest_mutation_revision = 0
        self._latest_applied_revision = 0
        bridge.runtime_ready.connect(self._refresh_startup)
        bridge.runtime_closing.connect(self.begin_closing)
        bridge.autostart_state_changed.connect(self._on_state_changed)
        bridge.command_completed.connect(self._on_command_completed)
        bridge.command_failed.connect(self._on_command_failed)

    @property
    def snapshot(self) -> AutostartSnapshot:
        return self._snapshot

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def controller_revision(self) -> int:
        return self._revision

    @property
    def user_toggle_allowed(self) -> bool:
        return (
            self._snapshot.user_toggle_allowed
            and not self._busy
            and not self._closing
            and self._bridge.accepting_commands
        )

    @property
    def display_message(self) -> str:
        if self._last_error is not None:
            return self._last_error[1]
        return self._snapshot.safe_message

    @Slot()
    def _refresh_startup(self) -> None:
        self.refresh(origin=AutostartOperationOrigin.STARTUP_QUERY)

    def refresh(
        self,
        *,
        origin: AutostartOperationOrigin = (
            AutostartOperationOrigin.STATE_REFRESH
        ),
    ) -> str | None:
        if self._closing or not self._bridge.accepting_commands:
            self._record_rejection(origin, None, "controller_not_accepting")
            return None
        context = self._new_context(origin, None)
        if not self._record(
            AutostartOperationEvent.UI_REQUEST_ACCEPTED,
            context,
        ):
            self._journal_failure()
            return None
        command_id = self._bridge.request_autostart(
            operation_id=context.operation_id,
            origin=context.origin,
            controller_revision=context.controller_revision,
        )
        if not self._bridge.is_command_pending(command_id):
            return None
        final_context = self._with_command_id(context, command_id)
        self._pending[command_id] = _PendingAutostartOperation(
            final_context,
            mutation=False,
        )
        return command_id

    def set_enabled(
        self,
        enabled: bool,
        *,
        origin: AutostartOperationOrigin = AutostartOperationOrigin.UNKNOWN,
    ) -> str | None:
        if not self.user_toggle_allowed or enabled == self._snapshot.enabled:
            self._record_rejection(origin, enabled, "request_rejected")
            return None
        context = self._new_context(origin, enabled)
        if not self._record(
            AutostartOperationEvent.UI_REQUEST_ACCEPTED,
            context,
        ):
            self._journal_failure()
            return None
        self._last_error = None
        self._busy = True
        self._latest_mutation_revision = context.controller_revision
        command_id = self._bridge.set_autostart_enabled(
            enabled,
            operation_id=context.operation_id,
            origin=context.origin,
            controller_revision=context.controller_revision,
        )
        if not self._bridge.is_command_pending(command_id):
            self._busy = False
            self._last_error = (
                "autostart_runtime_unavailable",
                "The autostart setting cannot change while runtime is closing.",
            )
            self.state_changed.emit(self._snapshot)
            self.operation_failed.emit(*self._last_error)
            return None
        final_context = self._with_command_id(context, command_id)
        self._pending[command_id] = _PendingAutostartOperation(
            final_context,
            mutation=True,
        )
        self.state_changed.emit(self._snapshot)
        return command_id

    @Slot()
    def begin_closing(self) -> None:
        if self._closing:
            return
        self._closing = True
        context = self._new_context(
            AutostartOperationOrigin.SHUTDOWN,
            None,
        )
        self._record(
            AutostartOperationEvent.CONTROLLER_CLOSING,
            context,
            runtime_state=AutostartOperationRuntimeState.RUNTIME_CLOSING,
        )
        self.state_changed.emit(self._snapshot)

    @Slot(str, object)
    def _on_state_changed(self, command_id: str, value: object) -> None:
        pending = self._pending.get(command_id)
        if pending is None or not isinstance(value, AutostartSnapshot):
            return
        revision = pending.context.controller_revision
        stale = revision < self._latest_applied_revision or (
            not pending.mutation
            and revision < self._latest_mutation_revision
        )
        if stale:
            self._record(
                AutostartOperationEvent.STALE_RESULT_IGNORED,
                pending.context,
                result_code="stale_revision",
            )
            return
        self._latest_applied_revision = revision
        self._snapshot = value
        self.state_changed.emit(value)

    @Slot(str)
    def _on_command_completed(self, command_id: str) -> None:
        pending = self._pending.pop(command_id, None)
        if pending is None:
            return
        if pending.mutation:
            self._busy = False
            self._last_error = None
            self.state_changed.emit(self._snapshot)

    @Slot(str, str, str)
    def _on_command_failed(
        self,
        command_id: str,
        safe_code: str,
        safe_message: str,
    ) -> None:
        pending = self._pending.pop(command_id, None)
        if pending is None:
            return
        if pending.mutation:
            self._busy = False
            self._last_error = (safe_code, safe_message)
            self.state_changed.emit(self._snapshot)
        self.operation_failed.emit(safe_code, safe_message)

    def _new_context(
        self,
        origin: AutostartOperationOrigin,
        requested_enabled: bool | None,
    ) -> AutostartOperationContext:
        self._revision += 1
        return AutostartOperationContext(
            operation_id=str(uuid4()),
            origin=origin,
            requested_enabled=requested_enabled,
            controller_revision=self._revision,
        )

    @staticmethod
    def _with_command_id(
        context: AutostartOperationContext,
        command_id: str,
    ) -> AutostartOperationContext:
        return AutostartOperationContext(
            operation_id=context.operation_id,
            command_id=command_id,
            origin=context.origin,
            requested_enabled=context.requested_enabled,
            controller_revision=context.controller_revision,
        )

    def _record_rejection(
        self,
        origin: AutostartOperationOrigin,
        requested_enabled: bool | None,
        result_code: str,
    ) -> None:
        if self._operation_journal is None:
            return
        context = self._new_context(origin, requested_enabled)
        self._record(
            AutostartOperationEvent.UI_REQUEST_REJECTED,
            context,
            result_code=result_code,
        )

    def _record(
        self,
        event: AutostartOperationEvent,
        context: AutostartOperationContext,
        *,
        runtime_state: AutostartOperationRuntimeState = (
            AutostartOperationRuntimeState.GUI
        ),
        result_code: str = "none",
    ) -> bool:
        journal = self._operation_journal
        if journal is None:
            return True
        try:
            journal.record(
                event,
                context,
                runtime_state=runtime_state,
                result_code=result_code,
            )
        except AutostartOperationJournalError:
            return False
        return True

    def _journal_failure(self) -> None:
        self._last_error = (
            "autostart_diagnostic_journal_failed",
            "The autostart diagnostic journal failed safely.",
        )
        self.state_changed.emit(self._snapshot)
        self.operation_failed.emit(*self._last_error)
