"""GUI-thread shared state for the RuntimeThread-owned autostart service."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from sjtuclaw.application.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


class AutostartUiController(QObject):
    """Keep one shared safe snapshot for every autostart UI entry point."""

    state_changed = Signal(object)
    operation_failed = Signal(str, str)

    def __init__(
        self,
        bridge: QtRuntimeBridge,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._snapshot = AutostartSnapshot.for_status(
            AutostartStatus.UNAVAILABLE
        )
        self._busy = False
        self._last_error: tuple[str, str] | None = None
        self._command_ids: set[str] = set()
        self._operation_ids: set[str] = set()
        bridge.runtime_ready.connect(self.refresh)
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
    def user_toggle_allowed(self) -> bool:
        return (
            self._snapshot.user_toggle_allowed
            and not self._busy
            and self._bridge.accepting_commands
        )

    @property
    def display_message(self) -> str:
        if self._last_error is not None:
            return self._last_error[1]
        return self._snapshot.safe_message

    @Slot()
    def refresh(self) -> str | None:
        if self._busy or not self._bridge.accepting_commands:
            return None
        command_id = self._bridge.request_autostart()
        if not self._bridge.is_command_pending(command_id):
            return None
        self._command_ids.add(command_id)
        return command_id

    def set_enabled(self, enabled: bool) -> str | None:
        if not self.user_toggle_allowed:
            return None
        if enabled == self._snapshot.enabled:
            return None
        self._last_error = None
        self._busy = True
        command_id = self._bridge.set_autostart_enabled(enabled)
        if not self._bridge.is_command_pending(command_id):
            self._busy = False
            self._last_error = (
                "autostart_runtime_unavailable",
                "The autostart setting cannot change while runtime is closing.",
            )
            self.state_changed.emit(self._snapshot)
            self.operation_failed.emit(*self._last_error)
            return None
        self._command_ids.add(command_id)
        self._operation_ids.add(command_id)
        self.state_changed.emit(self._snapshot)
        return command_id

    @Slot(str, object)
    def _on_state_changed(self, command_id: str, value: object) -> None:
        if (
            command_id not in self._command_ids
            or not isinstance(value, AutostartSnapshot)
        ):
            return
        self._snapshot = value
        self.state_changed.emit(value)

    @Slot(str)
    def _on_command_completed(self, command_id: str) -> None:
        if command_id not in self._command_ids:
            return
        self._command_ids.remove(command_id)
        if command_id in self._operation_ids:
            self._operation_ids.remove(command_id)
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
        if command_id not in self._command_ids:
            return
        self._command_ids.remove(command_id)
        if command_id in self._operation_ids:
            self._operation_ids.remove(command_id)
            self._busy = False
            self._last_error = (safe_code, safe_message)
            self.state_changed.emit(self._snapshot)
        self.operation_failed.emit(safe_code, safe_message)
