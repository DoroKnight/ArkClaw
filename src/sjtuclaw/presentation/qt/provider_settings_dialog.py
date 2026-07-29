"""Non-blocking Provider settings dialog backed only by QtRuntimeBridge."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
)
from sjtuclaw.application.provider_settings_service import (
    CredentialBindingView,
    ProviderProfileView,
    ProviderSettingsSnapshot,
)
from sjtuclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge

_ACTIVATION_OPTIONS = ProviderActivationOptions(
    timeout_seconds=60.0,
    max_retries=0,
    stream=True,
)


class ProviderSettingsDialog(QDialog):
    """Render non-sensitive Provider settings without owning runtime objects."""

    def __init__(
        self,
        bridge: QtRuntimeBridge,
        parent: QWidget | None = None,
        *,
        autostart_controller: AutostartUiController | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._autostart_controller = autostart_controller
        self._snapshot: ProviderSettingsSnapshot | None = None
        self._profiles: dict[str, ProviderProfileView] = {}
        self._bindings: dict[str, CredentialBindingView] = {}
        self._activation_commands: set[str] = set()
        self.setWindowTitle("Agent Settings")
        self.resize(760, 650)

        self.profile_list = QListWidget()
        self.profile_list.setObjectName("providerProfileList")
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("providerTypeCombo")
        for label, provider_id in (
            ("Fake", "fake"),
            ("OpenAI", "openai"),
            ("DeepSeek", "deepseek"),
        ):
            self.provider_combo.addItem(label, provider_id)
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setObjectName("profileDisplayNameEdit")
        self.model_edit = QLineEdit()
        self.model_edit.setObjectName("profileModelEdit")
        self.credential_combo = QComboBox()
        self.credential_combo.setObjectName("credentialBindingCombo")
        self.origin_label = QLabel("Fixed origin: none")
        self.origin_label.setObjectName("fixedOriginLabel")
        self.credential_status_label = QLabel("Credential: not applicable")
        self.credential_status_label.setObjectName("credentialStatusLabel")
        self.capabilities_label = QLabel("Capabilities: select a Profile")
        self.capabilities_label.setObjectName("providerCapabilitiesLabel")
        self.capabilities_label.setWordWrap(True)
        self.lifecycle_label = QLabel("Runtime: unavailable")
        self.lifecycle_label.setObjectName("providerLifecycleLabel")
        self.lifecycle_label.setWordWrap(True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("providerSettingsErrorLabel")
        self.error_label.setWordWrap(True)
        self.autostart_checkbox = QCheckBox(
            "Start SJTUClaw when I sign in"
        )
        self.autostart_checkbox.setObjectName("autostartEnabledCheckBox")
        self.autostart_status_label = QLabel(
            "Autostart status is unavailable."
        )
        self.autostart_status_label.setObjectName("autostartStatusLabel")
        self.autostart_status_label.setWordWrap(True)
        self.autostart_error_label = QLabel("")
        self.autostart_error_label.setObjectName("autostartErrorLabel")
        self.autostart_error_label.setWordWrap(True)
        self.autostart_help_label = QLabel(
            "Windows Settings > Apps > Startup or Task Manager may also "
            "disable startup. SJTUClaw does not change Windows "
            "StartupApproved state."
        )
        self.autostart_help_label.setObjectName("autostartHelpLabel")
        self.autostart_help_label.setWordWrap(True)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setObjectName("providerApiKeyEdit")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(
            "Enter a new key; saved values are never displayed"
        )

        self.create_button = QPushButton("Create")
        self.create_button.setObjectName("createProviderProfileButton")
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("copyProviderProfileButton")
        self.update_button = QPushButton("Update")
        self.update_button.setObjectName("updateProviderProfileButton")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("deleteProviderProfileButton")
        self.save_key_button = QPushButton("Save key")
        self.save_key_button.setObjectName("saveProviderCredentialButton")
        self.delete_key_button = QPushButton("Delete key")
        self.delete_key_button.setObjectName("deleteProviderCredentialButton")
        self.activate_button = QPushButton("Activate")
        self.activate_button.setObjectName("activateProviderProfileButton")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("refreshProviderSettingsButton")

        self.turn_choice = QComboBox()
        self.turn_choice.setObjectName("activeTurnSwitchChoice")
        self.turn_choice.addItem("Choose active-turn behavior", None)
        self.turn_choice.addItem(
            "Wait for current turn",
            ActiveTurnHandling.WAIT_FOR_ACTIVE,
        )
        self.turn_choice.addItem(
            "Cancel current turn, then switch",
            ActiveTurnHandling.CANCEL_ACTIVE,
        )
        self.turn_choice.addItem("Abandon this switch", "abandon")

        form = QFormLayout()
        form.addRow("Provider", self.provider_combo)
        form.addRow("Display name", self.display_name_edit)
        form.addRow("Model", self.model_edit)
        form.addRow("Credential", self.credential_combo)
        form.addRow("", self.origin_label)
        form.addRow("", self.credential_status_label)
        form.addRow("New API key", self.api_key_edit)
        form.addRow("Active turn", self.turn_choice)

        profile_actions = QHBoxLayout()
        for button in (
            self.create_button,
            self.copy_button,
            self.update_button,
            self.delete_button,
        ):
            profile_actions.addWidget(button)
        credential_actions = QHBoxLayout()
        credential_actions.addWidget(self.save_key_button)
        credential_actions.addWidget(self.delete_key_button)
        activation_actions = QHBoxLayout()
        activation_actions.addWidget(self.activate_button)
        activation_actions.addWidget(self.refresh_button)

        providers_content = QWidget()
        providers_content.setObjectName("providersSettingsContent")
        providers_layout = QVBoxLayout(providers_content)
        providers_layout.addWidget(self.lifecycle_label)
        providers_layout.addWidget(self.profile_list)
        providers_layout.addLayout(form)
        providers_layout.addWidget(self.capabilities_label)
        providers_layout.addLayout(profile_actions)
        providers_layout.addLayout(credential_actions)
        providers_layout.addLayout(activation_actions)
        providers_layout.addWidget(self.error_label)

        self.providers_scroll_area = QScrollArea()
        self.providers_scroll_area.setObjectName(
            "providersSettingsScrollArea"
        )
        self.providers_scroll_area.setWidgetResizable(True)
        self.providers_scroll_area.setWidget(providers_content)
        self.providers_page = QWidget()
        self.providers_page.setObjectName("providersSettingsPage")
        providers_page_layout = QVBoxLayout(self.providers_page)
        providers_page_layout.addWidget(self.providers_scroll_area)

        self.autostart_group = QGroupBox("Startup")
        self.autostart_group.setObjectName("autostartSettingsGroup")
        autostart_layout = QVBoxLayout(self.autostart_group)
        autostart_layout.addWidget(self.autostart_checkbox)
        autostart_layout.addWidget(self.autostart_status_label)
        autostart_layout.addWidget(self.autostart_error_label)
        autostart_layout.addWidget(self.autostart_help_label)

        general_content = QWidget()
        general_content.setObjectName("generalSettingsContent")
        general_layout = QVBoxLayout(general_content)
        general_layout.addWidget(self.autostart_group)
        general_layout.addStretch()
        self.general_scroll_area = QScrollArea()
        self.general_scroll_area.setObjectName("generalSettingsScrollArea")
        self.general_scroll_area.setWidgetResizable(True)
        self.general_scroll_area.setWidget(general_content)
        self.general_page = QWidget()
        self.general_page.setObjectName("generalSettingsPage")
        general_page_layout = QVBoxLayout(self.general_page)
        general_page_layout.addWidget(self.general_scroll_area)

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("providerSettingsTabs")
        self.settings_tabs.addTab(self.providers_page, "Providers")
        self.settings_tabs.addTab(self.general_page, "General")
        layout = QVBoxLayout(self)
        layout.addWidget(self.settings_tabs)

        self.profile_list.itemSelectionChanged.connect(
            self._on_profile_selected
        )
        self.provider_combo.currentIndexChanged.connect(
            self._on_provider_changed
        )
        self.credential_combo.currentIndexChanged.connect(
            self._update_credential_labels
        )
        self.create_button.clicked.connect(self._create_profile)
        self.copy_button.clicked.connect(self._copy_profile)
        self.update_button.clicked.connect(self._update_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        self.save_key_button.clicked.connect(self._save_credential)
        self.delete_key_button.clicked.connect(self._delete_credential)
        self.activate_button.clicked.connect(self._activate_profile)
        self.refresh_button.clicked.connect(self.refresh)
        self.autostart_checkbox.toggled.connect(
            self._on_autostart_toggled
        )
        self._bridge.provider_settings_changed.connect(
            self._on_settings_changed
        )
        self._bridge.command_failed.connect(self._on_command_failed)
        self._bridge.command_completed.connect(self._on_command_completed)
        if self._autostart_controller is not None:
            self._autostart_controller.state_changed.connect(
                self._on_autostart_state_changed
            )
            self._autostart_controller.operation_failed.connect(
                self._on_autostart_failed
            )
        self._render_autostart()
        self._set_controls_enabled()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # type: ignore[arg-type]
        self.refresh()
        if self._autostart_controller is not None:
            self._autostart_controller.refresh()

    def refresh(self) -> None:
        self.error_label.clear()
        self._bridge.request_provider_settings()

    @Slot(bool)
    def _on_autostart_toggled(self, enabled: bool) -> None:
        controller = self._autostart_controller
        if controller is None:
            self._render_autostart()
            return
        self.autostart_error_label.clear()
        if controller.set_enabled(enabled) is None:
            self._render_autostart()

    @Slot(object)
    def _on_autostart_state_changed(self, value: object) -> None:
        del value
        self._render_autostart()

    @Slot(str, str)
    def _on_autostart_failed(
        self,
        safe_code: str,
        safe_message: str,
    ) -> None:
        self.autostart_error_label.setText(
            f"{safe_code}: {safe_message}"
        )
        self._render_autostart()

    def _render_autostart(self) -> None:
        controller = self._autostart_controller
        if controller is None:
            self.autostart_checkbox.setChecked(False)
            self.autostart_checkbox.setEnabled(False)
            self.autostart_status_label.setText(
                "Autostart is unavailable in this runtime."
            )
            return
        snapshot = controller.snapshot
        blocker = QSignalBlocker(self.autostart_checkbox)
        self.autostart_checkbox.setChecked(snapshot.enabled)
        del blocker
        self.autostart_checkbox.setEnabled(
            controller.user_toggle_allowed
        )
        self.autostart_status_label.setText(controller.display_message)

    @Slot(str, object)
    def _on_settings_changed(
        self,
        command_id: str,
        value: object,
    ) -> None:
        del command_id
        if not isinstance(value, ProviderSettingsSnapshot):
            return
        selected_id = self._selected_profile_id()
        self._snapshot = value
        self._profiles = {
            profile.profile_id: profile for profile in value.profiles
        }
        self._bindings = {
            binding.credential_id: binding
            for binding in value.credential_bindings
        }
        self.profile_list.clear()
        for profile in value.profiles:
            marker = " [active]" if profile.is_runtime_profile else ""
            item = QListWidgetItem(
                f"{profile.display_name} ({profile.provider_id}){marker}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                profile.profile_id,
            )
            self.profile_list.addItem(item)
            if profile.profile_id == selected_id:
                self.profile_list.setCurrentItem(item)
        self.lifecycle_label.setText(
            "Runtime: "
            f"{value.runtime_state}; Provider: {value.provider_lifecycle}"
        )
        if self.profile_list.currentItem() is None and self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        self._set_controls_enabled()

    @Slot(str, str, str)
    def _on_command_failed(
        self,
        command_id: str,
        safe_code: str,
        safe_message: str,
    ) -> None:
        self._activation_commands.discard(command_id)
        self.error_label.setText(f"{safe_code}: {safe_message}")

    @Slot(str)
    def _on_command_completed(self, command_id: str) -> None:
        if command_id not in self._activation_commands:
            return
        self._activation_commands.remove(command_id)
        self.refresh()

    def _selected_profile_id(self) -> str | None:
        item = self.profile_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def _selected_profile(self) -> ProviderProfileView | None:
        profile_id = self._selected_profile_id()
        return None if profile_id is None else self._profiles.get(profile_id)

    @Slot()
    def _on_profile_selected(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            self._set_controls_enabled()
            return
        provider_index = self.provider_combo.findData(profile.provider_id)
        if provider_index >= 0:
            self.provider_combo.setCurrentIndex(provider_index)
        self.display_name_edit.setText(profile.display_name)
        self.model_edit.setText(profile.model)
        credential_index = self.credential_combo.findData(
            profile.credential_id
        )
        if credential_index >= 0:
            self.credential_combo.setCurrentIndex(credential_index)
        capabilities = profile.capabilities
        self.capabilities_label.setText(
            "Capabilities: "
            f"streaming={capabilities.streaming}, "
            f"tools={capabilities.tools}, "
            f"embeddings={capabilities.embeddings}, "
            f"continuation={capabilities.continuation_mode}, "
            f"protocol={capabilities.protocol}"
        )
        self._set_controls_enabled()

    @Slot()
    def _on_provider_changed(self) -> None:
        provider_id = self.provider_combo.currentData()
        selected_credential = self.credential_combo.currentData()
        self.credential_combo.clear()
        self.credential_combo.addItem("No credential", None)
        for binding in self._bindings.values():
            if binding.provider_id == provider_id:
                state = "configured" if binding.configured else "not configured"
                self.credential_combo.addItem(
                    f"{binding.display_name} ({state})",
                    binding.credential_id,
                )
        selected_index = self.credential_combo.findData(selected_credential)
        if selected_index >= 0:
            self.credential_combo.setCurrentIndex(selected_index)
        elif self.credential_combo.count() > 1:
            self.credential_combo.setCurrentIndex(1)
        self._update_credential_labels()

    @Slot()
    def _update_credential_labels(self) -> None:
        credential_id = self.credential_combo.currentData()
        binding = (
            self._bindings.get(credential_id)
            if isinstance(credential_id, str)
            else None
        )
        if binding is None:
            self.origin_label.setText("Fixed origin: none")
            self.credential_status_label.setText(
                "Credential: not applicable"
            )
        else:
            self.origin_label.setText(
                f"Fixed origin: {binding.fixed_origin}"
            )
            self.credential_status_label.setText(
                "Credential: "
                + ("configured" if binding.configured else "not configured")
            )
        self._set_controls_enabled()

    def _create_profile(self) -> None:
        self.error_label.clear()
        self._bridge.create_provider_profile(
            provider_id=str(self.provider_combo.currentData()),
            display_name=self.display_name_edit.text(),
            model=self.model_edit.text(),
            credential_id=self._credential_id(),
        )

    def _copy_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self.error_label.clear()
        self._bridge.create_provider_profile(
            provider_id=profile.provider_id,
            display_name=f"{profile.display_name} Copy",
            model=profile.model,
            credential_id=profile.credential_id,
        )

    def _update_profile(self) -> None:
        profile_id = self._selected_profile_id()
        if profile_id is None:
            return
        self.error_label.clear()
        self._bridge.update_provider_profile(
            profile_id=profile_id,
            display_name=self.display_name_edit.text(),
            model=self.model_edit.text(),
            credential_id=self._credential_id(),
        )

    def _delete_profile(self) -> None:
        profile = self._selected_profile()
        profile_id = self._selected_profile_id()
        if profile is None or profile_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Provider Profile",
            f'Delete the Profile "{profile.display_name}"?',
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.error_label.clear()
        self._bridge.delete_provider_profile(profile_id)

    def _save_credential(self) -> None:
        credential_id = self._credential_id()
        secret = self.api_key_edit.text()
        self.api_key_edit.clear()
        if credential_id is None or not secret:
            self.error_label.setText(
                "invalid_command: Credential and new API key are required."
            )
            return
        self.error_label.clear()
        self._bridge.save_provider_credential(credential_id, secret)
        secret = ""

    def _delete_credential(self) -> None:
        credential_id = self._credential_id()
        if credential_id is None:
            return
        binding = self._bindings.get(credential_id)
        display_name = (
            "the selected credential"
            if binding is None
            else f'"{binding.display_name}"'
        )
        answer = QMessageBox.question(
            self,
            "Delete Provider Credential",
            f"Delete {display_name} from Windows Credential Manager?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.error_label.clear()
        self._bridge.delete_provider_credential(credential_id)

    def _activate_profile(self) -> None:
        profile_id = self._selected_profile_id()
        if profile_id is None or self._snapshot is None:
            return
        handling: ActiveTurnHandling | None = None
        if self._snapshot.active_turn:
            selected = self.turn_choice.currentData()
            if selected == "abandon":
                self.error_label.setText(
                    "provider_switch_abandoned: No Provider change was made."
                )
                return
            if not isinstance(selected, ActiveTurnHandling):
                self.error_label.setText(
                    "switch_requires_turn_decision: Choose wait, cancel, "
                    "or abandon."
                )
                return
            handling = selected
        self.error_label.clear()
        command_id = self._bridge.activate_profile(
            profile_id,
            _ACTIVATION_OPTIONS,
            handling,
        )
        self._activation_commands.add(command_id)

    def _credential_id(self) -> str | None:
        value = self.credential_combo.currentData()
        return value if isinstance(value, str) and value else None

    def _set_controls_enabled(self) -> None:
        snapshot = self._snapshot
        profile = self._selected_profile()
        ready = snapshot is not None and snapshot.runtime_state == "ready"
        cleanup_pending = (
            snapshot is not None and snapshot.cleanup_pending
        )
        active_turn = snapshot is not None and snapshot.active_turn
        can_mutate = ready and not cleanup_pending and not active_turn
        is_active_profile = profile is not None and profile.is_runtime_profile
        has_credential = self._credential_id() is not None
        is_active_credential = (
            is_active_profile
            and profile is not None
            and profile.credential_id is not None
            and profile.credential_id == self._credential_id()
        )
        credential_tooltip = (
            "Switch away from the active Profile before changing this "
            "credential."
            if is_active_credential
            else ""
        )
        self.create_button.setEnabled(can_mutate)
        self.copy_button.setEnabled(can_mutate and profile is not None)
        self.update_button.setEnabled(
            can_mutate and profile is not None and not is_active_profile
        )
        self.delete_button.setEnabled(
            can_mutate and profile is not None and not is_active_profile
        )
        self.save_key_button.setEnabled(
            can_mutate and has_credential and not is_active_credential
        )
        self.delete_key_button.setEnabled(
            can_mutate and has_credential and not is_active_credential
        )
        self.save_key_button.setToolTip(credential_tooltip)
        self.delete_key_button.setToolTip(credential_tooltip)
        self.activate_button.setEnabled(
            ready
            and not cleanup_pending
            and profile is not None
            and not is_active_profile
        )
        self.turn_choice.setEnabled(
            ready and not cleanup_pending and active_turn
        )
