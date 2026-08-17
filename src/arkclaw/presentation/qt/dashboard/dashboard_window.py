"""Dashboard App Shell window (Slice 7B).

Authority: 07 sections 7/17 and tokens component.dashboard.window:
default 1280x800, minimum 1024x680, Top App Shell 56, global content max
1120, page gutter 40/32.  The shell composes Top Shell + NavigationPane +
page stack; Settings is an auxiliary top-shell entry (never a primary
page).  Theme switching is state-driven and preserves the current page;
dispose is idempotent and removes the owned top-level.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arkclaw.presentation.qt.dashboard.dashboard_page import (
    DashboardPage,
)
from arkclaw.presentation.qt.dashboard.navigation_pane import NavigationPane
from arkclaw.presentation.qt.dashboard.pages import build_page
from arkclaw.presentation.qt.dashboard.settings_dialog import SettingsDialog
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.icons import (
    IconKind,
    icon_color_for_theme,
    icon_pixmap,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, apply_theme
from arkclaw.presentation.qt.ui.autostart_controller import AutostartUiController


class DashboardWindow(QMainWindow):
    """Independent full-dashboard window (one top-level per product)."""

    page_selected = Signal(object)

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        *,
        autostart_controller: AutostartUiController | None = None,
    ) -> None:
        super().__init__()
        self._tokens = tokens if tokens is not None else load_design_tokens()
        self._autostart_controller = autostart_controller
        self._disposed = False
        self._current_page = DashboardPage.HOME
        self._theme = QtTheme.LIGHT
        self._settings_dialog: SettingsDialog | None = None
        self.setObjectName("dashboardWindow")
        self.setWindowTitle("ArkClaw")
        window = self._tokens.component["dashboard"]["window"]
        self.resize(
            int(window["default_width"]),
            int(window["default_height"]),
        )
        self.setMinimumSize(
            int(window["minimum_width"]),
            int(window["minimum_height"]),
        )
        root = QWidget(self)
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self._top_shell = QWidget(root)
        self._top_shell.setObjectName("topShell")
        self._top_shell.setFixedHeight(
            int(window["top_app_shell_height"])
        )
        top_layout = QHBoxLayout(self._top_shell)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(8)
        title = QLabel("ArkClaw", self._top_shell)
        title.setObjectName("topShellTitle")
        top_layout.addWidget(title)
        top_layout.addStretch(1)
        settings = QPushButton(self._top_shell)
        settings.setObjectName("secondaryButton")
        settings.setFixedSize(
            int(self._tokens.icon["default_hit_target"]),
            int(self._tokens.icon["default_hit_target"]),
        )
        settings.setAccessibleName("Settings")
        settings.setToolTip("Settings")
        settings.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        top_layout.addWidget(settings)
        self._settings_button = settings
        self._settings_button.clicked.connect(self.open_settings_dialog)
        self._theme = QtTheme.LIGHT
        self._render_settings_icon()
        body = QWidget(root)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._navigation = NavigationPane(self._tokens, body)
        self._pages = QStackedWidget(body)
        self._pages.setObjectName("pageArea")
        self._page_widgets: dict[DashboardPage, QWidget] = {}
        for page in DashboardPage:
            page_widget = build_page(page, self._tokens)
            self._pages.addWidget(page_widget)
            self._page_widgets[page] = page_widget
        body_layout.addWidget(self._navigation)
        body_layout.addWidget(self._pages, 1)
        root_layout.addWidget(self._top_shell)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self._navigation.page_selected.connect(self._on_navigation_page_selected)
        apply_theme(self, QtTheme.LIGHT, self._tokens)
        self._navigation.select_page(DashboardPage.HOME)
        self._pages.setCurrentWidget(self._page_widgets[DashboardPage.HOME])

    # -- accessors ----------------------------------------------------------
    @property
    def top_shell(self) -> QWidget:
        return self._top_shell

    @property
    def navigation(self) -> NavigationPane:
        return self._navigation

    @property
    def current_page(self) -> DashboardPage:
        return self._current_page

    def page_widget(self, page: DashboardPage) -> QWidget:
        return self._page_widgets[page]

    def settings_button(self) -> QPushButton:
        return self._settings_button

    def open_settings_dialog(self) -> SettingsDialog:
        """Open or raise the modal settings dialog."""
        dialog = SettingsDialog(
            self,
            autostart_controller=self._autostart_controller,
            theme=self._theme,
            theme_change_handler=self.set_theme,
            tokens=self._tokens,
        )
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    # -- behavior -----------------------------------------------------------
    def select_page(self, page: DashboardPage) -> None:
        self._current_page = page
        self._navigation.select_page(page)
        self._pages.setCurrentWidget(self._page_widgets[page])
        self.page_selected.emit(page)

    def set_theme(self, theme: QtTheme) -> None:
        self._theme = theme
        apply_theme(self, theme, self._tokens)
        self._navigation.set_theme(theme)
        self._render_settings_icon()
        for page_widget in self._page_widgets.values():
            set_theme = getattr(page_widget, "set_theme", None)
            if callable(set_theme):
                set_theme(theme)

    def _render_settings_icon(self) -> None:
        size = int(self._tokens.icon["action"])
        self._settings_button.setIcon(
            QIcon(
                icon_pixmap(
                    IconKind.SETTINGS,
                    size,
                    icon_color_for_theme(self._tokens, self._theme),
                    dpr=self.devicePixelRatioF(),
                )
            )
        )
        self._settings_button.setIconSize(QSize(size, size))

    def _on_navigation_page_selected(self, page: object) -> None:
        if isinstance(page, DashboardPage):
            self.select_page(page)

    def dispose(self) -> None:
        """Idempotent teardown: stop owned animation, hide, schedule delete."""
        if self._disposed:
            return
        self._disposed = True
        self._navigation.dispose()
        self.close()
        self.deleteLater()
