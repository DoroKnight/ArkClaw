"""ArkClaw desktop companion control center and runtime owner window."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import QMainWindow

from arkclaw.application.provider_settings_service import (
    ProviderSettingsSnapshot,
)
from arkclaw.application.runtime_session_controller import RuntimeSnapshot
from arkclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from arkclaw.presentation.qt.control_center import (
    CONTROL_CENTER_STYLE,
    ControlCenterView,
    PetPresentationSnapshot,
)
from arkclaw.presentation.qt.provider_settings_dialog import (
    ProviderSettingsDialog,
)
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


class MainWindow(QMainWindow):
    """Responsive control center that keeps runtime ownership in the bridge."""

    toggle_pet_visibility_requested = Signal()
    toggle_pet_paused_requested = Signal()
    set_pet_always_on_top_requested = Signal(bool)
    pet_action_requested = Signal(str)

    def __init__(
        self,
        bridge: QtRuntimeBridge,
        *,
        hide_on_close: bool = False,
        autostart_controller: AutostartUiController | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._autostart_controller = autostart_controller
        self._hide_on_close = hide_on_close
        self._safe_close_requested = False
        self._runtime_ready = False
        self._turn_active = False
        self._closing = False
        self._allow_final_close = False
        self._settings_dialog: ProviderSettingsDialog | None = None
        self._session_id = "desktop-session"
        self._pet_presentation = PetPresentationSnapshot()

        self.setWindowTitle("ArkClaw")
        self.setMinimumSize(880, 600)
        self.resize(1180, 760)
        self.setStyleSheet(CONTROL_CENTER_STYLE)
        self.control_center = ControlCenterView(
            self._autostart_controller,
            self,
        )
        self.control_center.setObjectName("controlCenter")
        self.setCentralWidget(self.control_center)
        self.control_center.apply_width(self.width())

        intelligence = self.control_center.settings_page
        self.conversation_view = intelligence.conversation_view
        self.input_edit = intelligence.input_edit
        self.send_button = intelligence.send_button
        self.cancel_button = intelligence.cancel_button
        self.settings_button = intelligence.settings_button
        self.profile_label = intelligence.profile_label
        self.runtime_label = intelligence.runtime_label
        self.error_label = intelligence.error_label

        self.send_button.clicked.connect(self._send_message)
        self.input_edit.returnPressed.connect(self._send_message)
        self.cancel_button.clicked.connect(self._cancel_turn)
        intelligence.open_provider_settings_requested.connect(
            self._open_settings
        )
        self.control_center.home_page.pause_requested.connect(
            self.toggle_pet_paused_requested
        )
        self.control_center.home_page.interact_requested.connect(
            lambda: self.pet_action_requested.emit("Interact")
        )
        self.control_center.action_requested.connect(
            self.pet_action_requested
        )
        self.control_center.home_page.visibility_requested.connect(
            self.toggle_pet_visibility_requested
        )
        self.control_center.appearance_page.visibility_changed.connect(
            lambda enabled: self.toggle_pet_visibility_requested.emit()
        )
        self.control_center.appearance_page.always_on_top_changed.connect(
            self.set_pet_always_on_top_requested
        )
        self._bridge.runtime_ready.connect(self._on_runtime_ready)
        self._bridge.runtime_state_changed.connect(
            self._on_runtime_state_changed
        )
        self._bridge.provider_settings_changed.connect(
            self._on_provider_settings_changed
        )
        self._bridge.turn_started.connect(self._on_turn_started)
        self._bridge.turn_completed.connect(self._on_turn_completed)
        self._bridge.turn_cancelled.connect(self._on_turn_cancelled)
        self._bridge.turn_failed.connect(self._on_turn_failed)
        self._bridge.command_failed.connect(self._on_command_failed)
        self._bridge.shutdown_finished.connect(self._on_shutdown_finished)
        self._update_controls()
        self._bridge.start_runtime()

    @property
    def current_page(self) -> str:
        return self.control_center.current_page

    def navigate_to(self, page: str) -> None:
        """Select one public control-center page."""

        self.control_center.navigate(page)

    @Slot(bool, bool, bool, str)
    def update_pet_presentation(
        self,
        visible: bool,
        paused: bool,
        always_on_top: bool,
        action: str,
    ) -> None:
        """Render a coordinator-owned desktop-pet presentation snapshot."""

        self._pet_presentation = PetPresentationSnapshot(
            visible=visible,
            paused=paused,
            always_on_top=always_on_top,
            action=action,
            attached=True,
        )
        self._refresh_control_center()

    @property
    def is_closing(self) -> bool:
        return self._closing

    @property
    def settings_dialog(self) -> ProviderSettingsDialog | None:
        return self._settings_dialog

    def request_safe_close(self) -> None:
        """Enter the existing asynchronous closeEvent state machine."""

        self._safe_close_requested = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_final_close:
            event.accept()
            return
        if self._hide_on_close and not self._safe_close_requested:
            event.ignore()
            self.hide()
            return
        if not self._bridge.runtime_thread.isRunning():
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.error_label.clear()
        self.runtime_label.setText("Runtime: closing")
        self._update_controls()
        self._bridge.shutdown(cancel_active=True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.control_center.apply_width(event.size().width())

    @Slot()
    def _on_runtime_ready(self) -> None:
        self._runtime_ready = True
        self.runtime_label.setText("Runtime: ready")
        self._refresh_control_center()
        self._update_controls()

    @Slot(object)
    def _on_runtime_state_changed(self, value: object) -> None:
        if not isinstance(value, RuntimeSnapshot):
            return
        self._runtime_ready = (
            value.runtime_state == "ready"
            and value.accepting_commands
            and not self._closing
        )
        self._turn_active = value.active_turn_id is not None
        self.runtime_label.setText(
            f"Runtime: {value.runtime_state}; "
            f"Provider: {value.provider_lifecycle}"
        )
        self.profile_label.setText(
            "Profile: "
            + (
                "inactive"
                if value.active_profile_id is None
                else value.active_profile_id
            )
        )
        self._refresh_control_center()
        self._update_controls()

    @Slot(str, object)
    def _on_provider_settings_changed(
        self,
        command_id: str,
        value: object,
    ) -> None:
        del command_id
        if not isinstance(value, ProviderSettingsSnapshot):
            return
        profile = next(
            (
                item
                for item in value.profiles
                if item.profile_id == value.runtime_profile_id
            ),
            None,
        )
        if profile is not None:
            self.profile_label.setText(
                f"Profile: {profile.display_name} ({profile.provider_id})"
            )

    def _send_message(self) -> None:
        if not self._runtime_ready or self._turn_active or self._closing:
            return
        content = self.input_edit.text().strip()
        if not content:
            return
        self.input_edit.clear()
        self.error_label.clear()
        self.conversation_view.appendPlainText(f"You: {content}")
        self._bridge.send_message(content, self._session_id)

    def _cancel_turn(self) -> None:
        if self._turn_active and not self._closing:
            self._bridge.cancel_active_turn()

    def _open_settings(self) -> None:
        if self._closing:
            return
        if self._settings_dialog is None:
            self._settings_dialog = ProviderSettingsDialog(
                self._bridge,
                self,
                autostart_controller=self._autostart_controller,
            )
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    @Slot(str)
    def _on_turn_started(self, turn_id: str) -> None:
        del turn_id
        self._turn_active = True
        self._update_controls()

    @Slot(str, str)
    def _on_turn_completed(self, turn_id: str, text: str) -> None:
        del turn_id
        self._turn_active = False
        self.conversation_view.appendPlainText(f"Assistant: {text}")
        self._update_controls()

    @Slot(str)
    def _on_turn_cancelled(self, turn_id: str) -> None:
        del turn_id
        self._turn_active = False
        self.error_label.setText(
            "turn_cancelled: The current reply was cancelled."
        )
        self._update_controls()

    @Slot(str, str, str)
    def _on_turn_failed(
        self,
        turn_id: str,
        safe_code: str,
        safe_message: str,
    ) -> None:
        del turn_id
        self._turn_active = False
        self.error_label.setText(f"{safe_code}: {safe_message}")
        self._update_controls()

    @Slot(str, str, str)
    def _on_command_failed(
        self,
        command_id: str,
        safe_code: str,
        safe_message: str,
    ) -> None:
        del command_id
        self.error_label.setText(f"{safe_code}: {safe_message}")

    @Slot(bool, str)
    def _on_shutdown_finished(self, success: bool, safe_code: str) -> None:
        if not self._closing:
            if not success:
                self.error_label.setText(
                    f"{safe_code}: Runtime shutdown failed safely."
                )
            return
        if not success:
            self._closing = False
            self._safe_close_requested = False
            self.runtime_label.setText("Runtime: shutdown failed")
            self.error_label.setText(
                f"{safe_code}: Runtime shutdown failed safely; retry closing."
            )
            self._update_controls()
            return
        self._allow_final_close = True
        QTimer.singleShot(0, self.close)

    def _update_controls(self) -> None:
        can_send = (
            self._runtime_ready
            and not self._turn_active
            and not self._closing
        )
        self.input_edit.setEnabled(can_send)
        self.send_button.setEnabled(can_send)
        self.cancel_button.setEnabled(
            self._turn_active and not self._closing
        )
        self.settings_button.setEnabled(
            self._runtime_ready and not self._closing
        )

    def _refresh_control_center(self) -> None:
        self.control_center.update_pet(
            self._pet_presentation,
            self._runtime_ready and not self._closing,
        )
