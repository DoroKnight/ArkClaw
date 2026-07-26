"""Minimal production-oriented desktop shell for the Qt runtime."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sjtuclaw.application.provider_settings_service import (
    ProviderSettingsSnapshot,
)
from sjtuclaw.application.runtime_session_controller import RuntimeSnapshot
from sjtuclaw.presentation.qt.provider_settings_dialog import (
    ProviderSettingsDialog,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


class MainWindow(QMainWindow):
    """Small responsive shell; visual desktop-pet behavior is intentionally absent."""

    def __init__(self, bridge: QtRuntimeBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._runtime_ready = False
        self._turn_active = False
        self._closing = False
        self._allow_final_close = False
        self._settings_dialog: ProviderSettingsDialog | None = None
        self._session_id = "desktop-session"

        self.setWindowTitle("SJTUClaw")
        self.resize(720, 520)
        self.conversation_view = QPlainTextEdit()
        self.conversation_view.setObjectName("conversationView")
        self.conversation_view.setReadOnly(True)
        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("messageInput")
        self.input_edit.setPlaceholderText("Type a message")
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendMessageButton")
        self.cancel_button = QPushButton("Cancel reply")
        self.cancel_button.setObjectName("cancelTurnButton")
        self.settings_button = QPushButton("Provider settings")
        self.settings_button.setObjectName("openProviderSettingsButton")
        self.profile_label = QLabel("Profile: inactive")
        self.profile_label.setObjectName("activeProfileLabel")
        self.runtime_label = QLabel("Runtime: starting")
        self.runtime_label.setObjectName("runtimeStateLabel")
        self.error_label = QLabel("")
        self.error_label.setObjectName("safeErrorLabel")
        self.error_label.setWordWrap(True)

        command_row = QHBoxLayout()
        command_row.addWidget(self.input_edit)
        command_row.addWidget(self.send_button)
        command_row.addWidget(self.cancel_button)
        status_row = QHBoxLayout()
        status_row.addWidget(self.runtime_label)
        status_row.addWidget(self.profile_label)
        status_row.addWidget(self.settings_button)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.conversation_view)
        layout.addLayout(command_row)
        layout.addLayout(status_row)
        layout.addWidget(self.error_label)
        self.setCentralWidget(central)

        self.send_button.clicked.connect(self._send_message)
        self.input_edit.returnPressed.connect(self._send_message)
        self.cancel_button.clicked.connect(self._cancel_turn)
        self.settings_button.clicked.connect(self._open_settings)
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
    def is_closing(self) -> bool:
        return self._closing

    @property
    def settings_dialog(self) -> ProviderSettingsDialog | None:
        return self._settings_dialog

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_final_close:
            event.accept()
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

    @Slot()
    def _on_runtime_ready(self) -> None:
        self._runtime_ready = True
        self.runtime_label.setText("Runtime: ready")
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
