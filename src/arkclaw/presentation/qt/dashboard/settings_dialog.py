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
