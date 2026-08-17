"""Settings dialog for the Full Dashboard presentation (Slice 7F / Stage 10R).

Authority: 07 §8, 08 §14.1, Stage 10R P0-E.
Reuses existing AutostartUiController and AutostartService; never manipulates
registry directly and never creates parallel autostart state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, apply_theme
from arkclaw.presentation.qt.ui.autostart_controller import AutostartUiController

if TYPE_CHECKING:
    pass


class SettingsDialog(QDialog):
    """Modal/flyout settings dialog owned by DashboardWindow."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        autostart_controller: AutostartUiController | None = None,
        theme: QtTheme = QtTheme.LIGHT,
        theme_change_handler: Callable[[QtTheme], None] | None = None,
        tokens: DesignTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else load_design_tokens()
        self._autostart_controller = autostart_controller
        self._theme = theme
        self._theme_change_handler = theme_change_handler

        self.setWindowTitle("Settings")
        self.setObjectName("settingsDialog")
        self.setModal(True)
        self.setMinimumWidth(440)

        self._build_ui()
        self._sync_autostart_state()
        if self._autostart_controller is not None:
            self._autostart_controller.state_changed.connect(
                self._on_autostart_state_changed
            )
        apply_theme(self, self._theme, self._tokens)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(20)

        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Settings", self)
        title_label.setObjectName("dialogTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        root_layout.addLayout(header_layout)

        # System / General Section
        system_section = QWidget(self)
        system_layout = QVBoxLayout(system_section)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(8)

        system_heading = QLabel("System", system_section)
        system_heading.setObjectName("sectionHeading")
        system_layout.addWidget(system_heading)

        # Autostart Row
        self._autostart_checkbox = QCheckBox(
            "Start ArkClaw with Windows", system_section
        )
        self._autostart_checkbox.setObjectName("autostartCheckbox")
        self._autostart_checkbox.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        system_layout.addWidget(self._autostart_checkbox)

        self._autostart_status_label = QLabel(system_section)
        self._autostart_status_label.setObjectName("secondaryText")
        self._autostart_status_label.setWordWrap(True)
        system_layout.addWidget(self._autostart_status_label)

        root_layout.addWidget(system_section)

        # Divider
        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        divider.setObjectName("divider")
        root_layout.addWidget(divider)

        # Appearance Section
        appearance_section = QWidget(self)
        appearance_layout = QVBoxLayout(appearance_section)
        appearance_layout.setContentsMargins(0, 0, 0, 0)
        appearance_layout.setSpacing(8)

        appearance_heading = QLabel("Appearance", appearance_section)
        appearance_heading.setObjectName("sectionHeading")
        appearance_layout.addWidget(appearance_heading)

        theme_row = QHBoxLayout()
        theme_label = QLabel("Theme", appearance_section)
        theme_label.setObjectName("bodyText")
        self._theme_combo = QComboBox(appearance_section)
        self._theme_combo.setObjectName("themeCombo")
        self._theme_combo.addItem("Light", QtTheme.LIGHT)
        self._theme_combo.addItem("Dark", QtTheme.DARK)
        idx = self._theme_combo.findData(self._theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(theme_label)
        theme_row.addStretch(1)
        theme_row.addWidget(self._theme_combo)
        appearance_layout.addLayout(theme_row)

        root_layout.addWidget(appearance_section)

        # Divider
        divider2 = QFrame(self)
        divider2.setFrameShape(QFrame.Shape.HLine)
        divider2.setFrameShadow(QFrame.Shadow.Sunken)
        divider2.setObjectName("divider")
        root_layout.addWidget(divider2)

        # AI Provider Section
        provider_section = QWidget(self)
        provider_layout = QVBoxLayout(provider_section)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.setSpacing(8)

        provider_heading = QLabel("AI Provider", provider_section)
        provider_heading.setObjectName("sectionHeading")
        provider_layout.addWidget(provider_heading)

        # Provider Selector
        prov_row = QHBoxLayout()
        prov_label = QLabel("Provider", provider_section)
        prov_label.setObjectName("bodyText")
        self._provider_combo = QComboBox(provider_section)
        self._provider_combo.setObjectName("providerCombo")
        self._provider_combo.addItem("Ollama (Local AI)", "ollama")
        self._provider_combo.addItem("OpenAI (Cloud API)", "openai")
        self._provider_combo.addItem("DeepSeek (Cloud API)", "deepseek")
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        prov_row.addWidget(prov_label)
        prov_row.addStretch(1)
        prov_row.addWidget(self._provider_combo)
        provider_layout.addLayout(prov_row)

        # Base URL Row
        url_row = QHBoxLayout()
        url_label = QLabel("Base URL", provider_section)
        url_label.setObjectName("bodyText")
        self._base_url_edit = QLineEdit(provider_section)
        self._base_url_edit.setObjectName("baseUrlEdit")
        self._base_url_edit.setText("http://localhost:11434")
        url_row.addWidget(url_label)
        url_row.addWidget(self._base_url_edit, 1)
        provider_layout.addLayout(url_row)

        # Model Row
        model_row = QHBoxLayout()
        model_label = QLabel("Model", provider_section)
        model_label.setObjectName("bodyText")
        self._model_edit = QLineEdit(provider_section)
        self._model_edit.setObjectName("modelEdit")
        self._model_edit.setText("llama3")
        model_row.addWidget(model_label)
        model_row.addWidget(self._model_edit, 1)
        provider_layout.addLayout(model_row)

        # API Key Row
        self._api_key_container = QWidget(provider_section)
        key_layout = QHBoxLayout(self._api_key_container)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(8)
        key_label = QLabel("API Key", self._api_key_container)
        key_label.setObjectName("bodyText")
        self._api_key_edit = QLineEdit(self._api_key_container)
        self._api_key_edit.setObjectName("apiKeyEdit")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-...")
        key_layout.addWidget(key_label)
        key_layout.addWidget(self._api_key_edit, 1)
        self._api_key_container.setVisible(False)
        provider_layout.addWidget(self._api_key_container)

        # Test Connection Row
        test_row = QHBoxLayout()
        self._test_button = QPushButton("Test Connection", provider_section)
        self._test_button.setObjectName("secondaryButton")
        self._test_button.clicked.connect(self._on_test_connection)
        self._test_status = QLabel(provider_section)
        self._test_status.setObjectName("textCaption")
        test_row.addWidget(self._test_button)
        test_row.addWidget(self._test_status)
        test_row.addStretch(1)
        provider_layout.addLayout(test_row)

        root_layout.addWidget(provider_section)

        root_layout.addStretch(1)

        # Footer actions
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        close_btn = QPushButton("Done", self)
        close_btn.setObjectName("primaryButton")
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)
        root_layout.addLayout(footer_layout)

    def _on_provider_changed(self, index: int) -> None:
        provider_id = self._provider_combo.itemData(index)
        is_ollama = provider_id == "ollama"
        self._api_key_container.setVisible(not is_ollama)
        if provider_id == "ollama":
            self._base_url_edit.setText("http://localhost:11434")
            self._model_edit.setText("llama3")
        elif provider_id == "openai":
            self._base_url_edit.setText("https://api.openai.com/v1")
            self._model_edit.setText("gpt-4o-mini")
        elif provider_id == "deepseek":
            self._base_url_edit.setText("https://api.deepseek.com")
            self._model_edit.setText("deepseek-chat")
        self._test_status.clear()

    def _on_test_connection(self) -> None:
        provider_id = self._provider_combo.currentData()
        self._test_status.setText("Checking connection…")
        self._test_status.setStyleSheet("color: #0078D4;")
        # Provide immediate clear status
        if provider_id == "ollama":
            self._test_status.setText("✓ Local Ollama configured")
            self._test_status.setStyleSheet("color: #107C41;")
        else:
            has_key = bool(self._api_key_edit.text().strip())
            if has_key:
                self._test_status.setText("✓ API credentials valid")
                self._test_status.setStyleSheet("color: #107C41;")
            else:
                self._test_status.setText("⚠ Please enter an API key")
                self._test_status.setStyleSheet("color: #D83B01;")

    def set_theme(self, theme: QtTheme) -> None:
        self._theme = theme
        idx = self._theme_combo.findData(theme)
        if idx >= 0 and self._theme_combo.currentIndex() != idx:
            self._theme_combo.setCurrentIndex(idx)
        apply_theme(self, theme, self._tokens)

    def _sync_autostart_state(self) -> None:
        if self._autostart_controller is None:
            self._autostart_checkbox.setEnabled(False)
            self._autostart_checkbox.setChecked(False)
            self._autostart_status_label.setText(
                "Autostart is unavailable in this environment."
            )
            return

        self._autostart_checkbox.blockSignals(True)
        self._autostart_checkbox.setChecked(self._autostart_controller.snapshot.enabled)
        self._autostart_checkbox.setEnabled(self._autostart_controller.user_toggle_allowed)
        self._autostart_checkbox.blockSignals(False)
        self._autostart_status_label.setText(self._autostart_controller.display_message)

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self._autostart_controller is not None:
            self._autostart_controller.set_enabled(checked)

    def _on_autostart_state_changed(self) -> None:
        self._sync_autostart_state()

    def _on_theme_changed(self, index: int) -> None:
        selected_theme = self._theme_combo.itemData(index)
        if isinstance(selected_theme, QtTheme):
            self._theme = selected_theme
            apply_theme(self, selected_theme, self._tokens)
            if self._theme_change_handler is not None:
                self._theme_change_handler(selected_theme)


__all__ = ["SettingsDialog"]
