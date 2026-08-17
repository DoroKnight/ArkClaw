"""Injectable system-tray boundary for the desktop pet application."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from PySide6.QtCore import QObject, QPoint, QSignalBlocker, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_operation_journal import (
    AutostartOperationOrigin,
)
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme
from arkclaw.presentation.qt.ui.autostart_controller import (
    AutostartUiController,
)
from arkclaw.presentation.qt.ui.production_action_menu import (
    ProductionActionMenuSection,
    build_menu_stylesheet,
    prepare_arkclaw_menu,
)


@dataclass(frozen=True, slots=True)
class PetTrayState:
    pet_visible: bool
    paused: bool
    always_on_top: bool
    closing: bool
    autostart: AutostartSnapshot = field(
        default_factory=lambda: AutostartSnapshot.for_status(
            AutostartStatus.UNAVAILABLE
        )
    )
    autostart_busy: bool = False
    autostart_display_message: str = ""
    role_pack_id: str = "placeholder"
    available_actions: frozenset[ProductionAction] = frozenset()


class PetTrayCommands(Protocol):
    @property
    def pet_visible(self) -> bool: ...

    @property
    def pet_paused(self) -> bool: ...

    @property
    def pet_always_on_top(self) -> bool: ...

    @property
    def pet_closing(self) -> bool: ...

    def toggle_pet_visibility(self) -> None: ...

    def open_agent_window(self) -> None: ...

    def open_dashboard(self) -> None: ...

    def toggle_paused(self) -> None: ...

    def set_always_on_top(self, enabled: bool) -> None: ...

    def request_safe_exit(self) -> None: ...


class PetProductionActionCommands(Protocol):
    @property
    def active_role_pack_id(self) -> str: ...

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]: ...

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome: ...

    def resume_pet_autonomous(self) -> ActionOutcome: ...


@dataclass(frozen=True, slots=True)
class TrayCallbacks:
    refresh: Callable[[], None]
    toggle_pet_visibility: Callable[[], None]
    open_agent_window: Callable[[], None]
    toggle_paused: Callable[[], None]
    set_always_on_top: Callable[[bool], None]
    request_safe_exit: Callable[[], None]
    open_dashboard: Callable[[], None] | None = None
    set_autostart_enabled: Callable[[bool], None] | None = None
    request_action: Callable[[ProductionAction], None] | None = None
    resume_autonomous: Callable[[], None] | None = None


class TrayView(Protocol):
    def show(self) -> None: ...

    def is_visible(self) -> bool: ...

    def update_state(self, state: PetTrayState) -> None: ...

    def close(self) -> None: ...


TrayViewFactory = Callable[[TrayCallbacks, QObject], TrayView | None]


class _QtSystemTrayView:
    def __init__(
        self,
        callbacks: TrayCallbacks,
        parent: QObject,
    ) -> None:
        self._closed = False
        self._tray = QSystemTrayIcon(parent)
        self._tray.setObjectName("arkclawSystemTray")
        self._tray.setToolTip("ArkClaw")
        self._tray.setIcon(_create_programmatic_tray_icon())
        self._menu = QMenu()
        prepare_arkclaw_menu(
            self._menu,
            object_name="arkclawSystemTrayMenu",
        )
        self._menu.aboutToShow.connect(callbacks.refresh)

        self._open_dashboard_action = QAction("Open Dashboard", self._menu)
        self._open_dashboard_action.setObjectName("openDashboardAction")
        self._open_dashboard_action.triggered.connect(
            lambda checked=False: callbacks.open_dashboard()
            if callbacks.open_dashboard is not None
            else callbacks.open_agent_window()
        )
        self._menu.addAction(self._open_dashboard_action)

        self._visibility_action = QAction("Hide Character", self._menu)
        self._visibility_action.triggered.connect(
            lambda checked=False: callbacks.toggle_pet_visibility()
        )
        self._menu.addAction(self._visibility_action)

        self._pause_action = QAction("Pause Autonomous", self._menu)
        self._pause_action.triggered.connect(
            lambda checked=False: callbacks.toggle_paused()
        )
        self._menu.addAction(self._pause_action)

        self._always_on_top_action = QAction(
            "Always on Top",
            self._menu,
        )
        self._always_on_top_action.setCheckable(True)
        self._always_on_top_action.toggled.connect(
            callbacks.set_always_on_top
        )
        self._menu.addAction(self._always_on_top_action)

        self._role_pack_action: QAction | None = None
        self._move_menu: QMenu | None = None
        self._resume_autonomous_action: QAction | None = None
        self._action_items: dict[ProductionAction, QAction] = {}
        self._production_action_section: ProductionActionMenuSection | None = None
        if (
            callbacks.request_action is not None
            and callbacks.resume_autonomous is not None
        ):
            self._menu.addSeparator()
            section = ProductionActionMenuSection(
                self._menu,
                request_action=callbacks.request_action,
                resume_autonomous=callbacks.resume_autonomous,
            )
            self._production_action_section = section
            self._role_pack_action = section.role_pack_action
            self._move_menu = section.move_menu
            self._resume_autonomous_action = section.resume_autonomous_action
            self._action_items = section.action_items

        self._autostart_action = QAction(
            "Start with Windows",
            self._menu,
        )
        self._autostart_action.setObjectName(
            "trayAutostartEnabledAction"
        )
        self._autostart_action.setCheckable(True)
        self._autostart_action.toggled.connect(
            lambda enabled: (
                callbacks.set_autostart_enabled(enabled)
                if callbacks.set_autostart_enabled is not None
                else None
            )
        )
        self._menu.addAction(self._autostart_action)
        self._menu.addSeparator()

        self._exit_action = QAction("Exit", self._menu)
        self._exit_action.triggered.connect(
            lambda checked=False: callbacks.request_safe_exit()
        )
        self._menu.addAction(self._exit_action)
        self._tray.setContextMenu(self._menu)

    def show(self) -> None:
        if not self._closed:
            self._tray.show()

    def is_visible(self) -> bool:
        return not self._closed and self._tray.isVisible()

    def update_state(self, state: PetTrayState) -> None:
        if self._closed:
            return
        self._visibility_action.setText(
            "Hide Character" if state.pet_visible else "Show Character"
        )
        self._pause_action.setText(
            "Resume Autonomous" if state.paused else "Pause Autonomous"
        )
        blocker = QSignalBlocker(self._always_on_top_action)
        self._always_on_top_action.setChecked(state.always_on_top)
        del blocker
        autostart_blocker = QSignalBlocker(self._autostart_action)
        self._autostart_action.setChecked(state.autostart.enabled)
        del autostart_blocker
        self._autostart_action.setToolTip(
            state.autostart_display_message
            or state.autostart.safe_message
        )
        self._autostart_action.setEnabled(
            not state.closing
            and not state.autostart_busy
            and state.autostart.user_toggle_allowed
        )
        for action in (
            self._visibility_action,
            self._open_dashboard_action,
            self._pause_action,
            self._always_on_top_action,
        ):
            action.setEnabled(not state.closing)
        self._exit_action.setEnabled(not state.closing)
        if self._production_action_section is not None:
            self._production_action_section.update(
                role_pack_id=state.role_pack_id,
                available_actions=state.available_actions,
                closing=state.closing,
            )

    def set_theme(self, theme: QtTheme) -> None:
        if self._closed:
            return
        self._menu.setStyleSheet(build_menu_stylesheet(theme))
        if self._move_menu is not None:
            self._move_menu.setStyleSheet(build_menu_stylesheet(theme))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tray.hide()
        for action in self._menu.actions():
            action.setEnabled(False)
        self._menu.close()
        self._menu.clear()
        self._menu.deleteLater()
        self._tray.deleteLater()


class SystemTrayController(QObject):
    """Map fixed tray actions to the existing GUI coordinator."""

    def __init__(
        self,
        commands: PetTrayCommands,
        *,
        production_actions: PetProductionActionCommands | None = None,
        autostart_controller: AutostartUiController | None = None,
        view_factory: TrayViewFactory | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._commands = commands
        if production_actions is None and all(
            hasattr(commands, name)
            for name in (
                "active_role_pack_id",
                "available_pet_actions",
                "request_pet_action",
                "resume_pet_autonomous",
            )
        ):
            production_actions = cast(PetProductionActionCommands, commands)
        self._production_actions = production_actions
        self._autostart_controller = autostart_controller
        self._closed = False
        self._shutdown_started = False
        self._exit_requested = False
        self._refresh_disabled = False
        self._view: TrayView | None = None
        self._cleanup_pending_view: TrayView | None = None
        self._safe_code = "none"
        callbacks = TrayCallbacks(
            refresh=self.refresh,
            toggle_pet_visibility=self._toggle_pet_visibility,
            open_agent_window=self._open_agent_window,
            open_dashboard=self._open_dashboard,
            toggle_paused=self._toggle_paused,
            set_always_on_top=self._set_always_on_top,
            request_safe_exit=self._request_safe_exit,
            set_autostart_enabled=(
                None
                if autostart_controller is None
                else self._set_autostart_enabled
            ),
            request_action=(
                None
                if production_actions is None
                else self._request_production_action
            ),
            resume_autonomous=(
                None
                if production_actions is None
                else self._resume_autonomous
            ),
        )
        factory = view_factory or _create_qt_tray_view
        try:
            view = factory(callbacks, self)
        except Exception:
            self._safe_code = "system_tray_initialization_failed"
            return
        if view is None:
            self._safe_code = "system_tray_unavailable"
            return
        self._view = view
        if autostart_controller is not None:
            autostart_controller.state_changed.connect(
                self._on_autostart_state_changed
            )
        try:
            self._update_view(view)
            view.show()
        except Exception:
            self._safe_code = "system_tray_initialization_failed"
            self._cleanup_pending_view = view
            self._view = None

    @property
    def available(self) -> bool:
        return self._view is not None

    @property
    def visible(self) -> bool:
        view = self._view
        if view is None:
            return False
        try:
            return view.is_visible()
        except Exception:
            return False

    @property
    def safe_code(self) -> str:
        return self._safe_code

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def cleanup_pending(self) -> bool:
        return self._cleanup_pending_view is not None

    def set_theme(self, theme: QtTheme) -> None:
        if self._closed or self._view is None:
            return
        set_view_theme = getattr(self._view, "set_theme", None)
        if callable(set_view_theme):
            set_view_theme(theme)

    def refresh(self) -> None:
        if (
            self._closed
            or self._refresh_disabled
            or self._view is None
        ):
            return
        try:
            self._update_view(self._view)
        except Exception:
            self._refresh_disabled = True
            self._safe_code = "system_tray_refresh_failed"

    def recover_failed_shutdown(self) -> None:
        if self._closed or self._shutdown_started:
            return
        self._exit_requested = False
        self._refresh_disabled = False
        self.refresh()

    def complete_shutdown(self) -> None:
        if self._closed:
            return
        self._shutdown_started = True
        self._exit_requested = True
        view = self._cleanup_pending_view or self._view
        self._view = None
        if view is None:
            self._closed = True
            return
        self._cleanup_pending_view = view
        self._try_close_pending_view()

    def retry_pending_cleanup(self) -> bool:
        """Retry a retained failed tray cleanup without recreating the tray."""

        if self._closed:
            return True
        if not self._shutdown_started:
            return False
        return self._try_close_pending_view()

    def _try_close_pending_view(self) -> bool:
        view = self._cleanup_pending_view
        if view is None:
            self._closed = True
            return True
        try:
            view.close()
        except Exception:
            self._safe_code = "system_tray_cleanup_failed"
            return False
        self._cleanup_pending_view = None
        self._closed = True
        if self._safe_code == "system_tray_cleanup_failed":
            self._safe_code = "none"
        return True

    def _update_view(self, view: TrayView) -> None:
        view.update_state(
            PetTrayState(
                pet_visible=self._commands.pet_visible,
                paused=self._commands.pet_paused,
                always_on_top=self._commands.pet_always_on_top,
                closing=self._commands.pet_closing,
                autostart=(
                    AutostartSnapshot.for_status(
                        AutostartStatus.UNAVAILABLE
                    )
                    if self._autostart_controller is None
                    else self._autostart_controller.snapshot
                ),
                autostart_busy=(
                    False
                    if self._autostart_controller is None
                    else self._autostart_controller.busy
                ),
                autostart_display_message=(
                    ""
                    if self._autostart_controller is None
                    else self._autostart_controller.display_message
                ),
                role_pack_id=(
                    "placeholder"
                    if self._production_actions is None
                    else self._production_actions.active_role_pack_id
                ),
                available_actions=(
                    frozenset()
                    if self._production_actions is None
                    else self._production_actions.available_pet_actions
                ),
            )
        )

    def _on_autostart_state_changed(self, value: object) -> None:
        del value
        self.refresh()

    def _set_autostart_enabled(self, enabled: bool) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        controller = self._autostart_controller
        if controller is None:
            return
        controller.set_enabled(
            enabled,
            origin=AutostartOperationOrigin.TRAY_ACTION,
        )
        self.refresh()

    def _toggle_pet_visibility(self) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        self._commands.toggle_pet_visibility()
        self.refresh()

    def _open_agent_window(self) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        self._commands.open_agent_window()
        self.refresh()

    def _open_dashboard(self) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        commands = self._commands
        open_dashboard = getattr(commands, "open_dashboard", None)
        if open_dashboard is None:
            return
        open_dashboard()
        self.refresh()

    def _toggle_paused(self) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        self._commands.toggle_paused()
        self.refresh()

    def _set_always_on_top(self, enabled: bool) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        self._commands.set_always_on_top(enabled)
        self.refresh()

    def _request_production_action(self, action: ProductionAction) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        commands = self._production_actions
        if commands is None:
            return
        commands.request_pet_action(action)
        self.refresh()

    def _resume_autonomous(self) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        commands = self._production_actions
        if commands is None:
            return
        commands.resume_pet_autonomous()
        self.refresh()

    def _request_safe_exit(self) -> None:
        if self._exit_requested or self._shutdown_started or self._closed:
            return
        self._exit_requested = True
        self._commands.request_safe_exit()
        self.refresh()


def _create_qt_tray_view(
    callbacks: TrayCallbacks,
    parent: QObject,
) -> TrayView | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    return _QtSystemTrayView(callbacks, parent)


def _create_programmatic_tray_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            scale = size / 64.0
            painter.scale(scale, scale)
            outline = QPen(QColor(25, 71, 82), 5)
            outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(outline)
            painter.setBrush(QColor(80, 207, 188))
            painter.drawEllipse(8, 14, 48, 44)
            painter.drawPolygon(
                [
                    _point(13, 22),
                    _point(19, 5),
                    _point(29, 18),
                    _point(35, 18),
                    _point(45, 5),
                    _point(51, 22),
                ]
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(25, 71, 82))
            painter.drawEllipse(22, 32, 5, 7)
            painter.drawEllipse(37, 32, 5, 7)
        finally:
            painter.end()
        icon.addPixmap(pixmap)
    return icon


def _point(x: int, y: int) -> QPoint:
    return QPoint(x, y)
