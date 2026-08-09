"""Transparent, frameless window for the original placeholder desktop pet."""

from __future__ import annotations

import random
from typing import Protocol

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal, SignalInstance
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QContextMenuEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from sjtuclaw.application.autostart_operation_journal import (
    AutostartOperationOrigin,
)
from sjtuclaw.application.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from sjtuclaw.application.pet_action_sequence import (
    PetActionName,
    default_animation_registry,
)
from sjtuclaw.application.pet_animation import (
    MonotonicClock,
    PetAnimationConfig,
    PetAnimationEngine,
    PetRenderFrame,
    SystemMonotonicClock,
)
from sjtuclaw.application.pet_geometry import Point, Rect, Size
from sjtuclaw.application.pet_motion import PetMotionModel
from sjtuclaw.application.pet_renderer_model import action_request_for_frame
from sjtuclaw.application.pet_state import (
    PetFacing,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
)
from sjtuclaw.application.pet_track0 import (
    ActionOutcome,
    AnimationPlayerCapabilities,
    PetTrack0Controller,
    PlaybackRequest,
    PlaybackToken,
)
from sjtuclaw.presentation.qt.pet_renderer import (
    PetRenderer,
    PetRendererSafeCode,
    PlaceholderPetRenderer,
    SafePetRenderer,
)


class _AutostartUiController(Protocol):
    @property
    def state_changed(self) -> SignalInstance: ...

    @property
    def snapshot(self) -> AutostartSnapshot: ...

    @property
    def display_message(self) -> str: ...

    @property
    def user_toggle_allowed(self) -> bool: ...

    def set_enabled(
        self,
        enabled: bool,
        *,
        origin: AutostartOperationOrigin,
    ) -> str | None: ...

_PET_WIDTH = 160
_PET_HEIGHT = 180
_TIMER_INTERVAL_MS = 16


class PlaceholderAnimationPlayer:
    """Explicitly disable production sequencing for the drawn placeholder."""

    _CAPABILITIES = AnimationPlayerCapabilities(False, False, False, False)

    def __init__(self) -> None:
        self._play_call_count = 0

    @property
    def capabilities(self) -> AnimationPlayerCapabilities:
        return self._CAPABILITIES

    @property
    def play_call_count(self) -> int:
        return self._play_call_count

    def request(self, action: PetActionName) -> ActionOutcome:
        """Retain the legacy renderer-neutral path without pretending to play."""

        del action
        return ActionOutcome.LEGACY_DIRECT

    def play(self, request: PlaybackRequest) -> PlaybackToken:
        del request
        self._play_call_count += 1
        raise RuntimeError("placeholder production sequencing is disabled")

    def clear(self, track: int, mix_seconds: float) -> None:
        del track, mix_seconds


class PetWindow(QWidget):
    """Render and move a small programmatic character without runtime access."""

    open_agent_requested = Signal()
    safe_exit_requested = Signal()
    presentation_state_changed = Signal()

    def __init__(
        self,
        *,
        always_on_top: bool = True,
        renderer: PetRenderer | None = None,
        clock: MonotonicClock | None = None,
        rng: random.Random | None = None,
        animation_config: PetAnimationConfig | None = None,
        autostart_controller: _AutostartUiController | None = None,
    ) -> None:
        super().__init__()
        self._always_on_top = always_on_top
        self._allow_final_close = False
        self._exit_emitted = False
        self._drag_offset: Point | None = None
        self._context_menu: QMenu | None = None
        self._autostart_controller = autostart_controller
        self._autostart_action: QAction | None = None
        selected_renderer = renderer or PlaceholderPetRenderer()
        self._renderer = (
            selected_renderer
            if isinstance(selected_renderer, SafePetRenderer)
            else SafePetRenderer(selected_renderer)
        )
        self.setObjectName("placeholderPetWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(_PET_WIDTH, _PET_HEIGHT)
        self._apply_window_flags()

        workspace = self._primary_workspace()
        initial = Point(
            workspace.right - _PET_WIDTH - 32,
            workspace.bottom - _PET_HEIGHT,
        )
        self._default_always_on_top = always_on_top
        self._default_position = initial
        motion = PetMotionModel(
            initial,
            Size(_PET_WIDTH, _PET_HEIGHT),
        )
        selected_clock = clock or SystemMonotonicClock()
        self._animation_player = PlaceholderAnimationPlayer()
        track0 = PetTrack0Controller(
            player=self._animation_player,
            registry=default_animation_registry(),
            clock=selected_clock,
        )
        self._animation = PetAnimationEngine(
            motion,
            rng=rng,
            config=animation_config,
            track0=track0,
        )
        self._renderer.initialize(Size(_PET_WIDTH, _PET_HEIGHT))
        self._sync_renderer_state()
        self._clock = selected_clock
        self._last_tick = self._clock.now()
        self.move(round(initial.x), round(initial.y))

        self._animation_timer = QTimer(self)
        self._animation_timer.setObjectName("petAnimationTimer")
        self._animation_timer.setInterval(_TIMER_INTERVAL_MS)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._animation_timer.start()
        if autostart_controller is not None:
            autostart_controller.state_changed.connect(
                self._on_autostart_state_changed
            )

    @property
    def lifecycle_state(self) -> PetLifecycleState:
        return self._animation.motion.state.lifecycle

    @property
    def motion_state(self) -> PetMotionState:
        return self._animation.motion.state.motion

    @property
    def render_frame(self) -> PetRenderFrame:
        return self._animation.frame

    @property
    def always_on_top(self) -> bool:
        return self._always_on_top

    @property
    def physics_timer(self) -> QTimer:
        """Backward-compatible diagnostic handle for the single GUI timer."""

        return self._animation_timer

    @property
    def renderer_safe_code(self) -> PetRendererSafeCode:
        """Expose only a fixed diagnostic category, never exception details."""

        return self._renderer.safe_code

    def toggle_paused(self) -> None:
        if self.lifecycle_state is PetLifecycleState.CLOSING:
            return
        try:
            if self.lifecycle_state is PetLifecycleState.PAUSED:
                self._animation.resume()
                self._renderer.resume()
                self._last_tick = self._clock.now()
            else:
                self._animation.pause()
                self._renderer.pause()
        except PetStateTransitionError:
            return
        self._sync_renderer_state()
        self.update()
        self.presentation_state_changed.emit()

    def set_always_on_top(self, enabled: bool) -> None:
        if (
            self.lifecycle_state is PetLifecycleState.CLOSING
            or enabled == self._always_on_top
        ):
            return
        self._always_on_top = enabled
        visible = self.isVisible()
        self._apply_window_flags()
        if visible:
            self.show()
        self.presentation_state_changed.emit()

    def reclaim_to_workspace(self) -> None:
        if self.lifecycle_state is PetLifecycleState.CLOSING:
            return
        snapshot = self._animation.motion.constrain(self._workspaces())
        self.move(
            round(snapshot.position.x),
            round(snapshot.position.y),
        )

    def restore_persisted_position(self, window_x: int, window_y: int) -> None:
        """Apply non-sensitive coordinates to the authoritative motion model."""

        if self.lifecycle_state is PetLifecycleState.CLOSING:
            return
        snapshot = self._animation.motion.restore_position(
            Point(window_x, window_y),
            self._workspaces(),
        )
        self.move(
            round(snapshot.position.x),
            round(snapshot.position.y),
        )

    def persisted_presentation_state(self) -> tuple[int, int, bool]:
        """Return a final constrained snapshot suitable for persistence."""

        snapshot = self._animation.motion.constrain(self._workspaces())
        self.move(
            round(snapshot.position.x),
            round(snapshot.position.y),
        )
        return (
            round(snapshot.position.x),
            round(snapshot.position.y),
            self._always_on_top,
        )

    def restore_builtin_presentation_defaults(self) -> None:
        """Restore constructor defaults after optional settings fail."""

        self._always_on_top = self._default_always_on_top
        self._apply_window_flags()
        snapshot = self._animation.motion.restore_position(
            self._default_position,
            self._workspaces(),
        )
        self.move(
            round(snapshot.position.x),
            round(snapshot.position.y),
        )

    def request_safe_exit(self) -> None:
        if self._exit_emitted:
            return
        try:
            self._animation.begin_closing()
        except PetStateTransitionError:
            return
        self._exit_emitted = True
        self._drag_offset = None
        self._sync_renderer_state()
        self._animation_timer.stop()
        self.update()
        self.presentation_state_changed.emit()
        self.safe_exit_requested.emit()

    def recover_from_failed_close(self) -> None:
        if self.lifecycle_state is not PetLifecycleState.CLOSING:
            return
        self._animation.recover_failed_close()
        self._renderer.pause()
        self._sync_renderer_state()
        self._exit_emitted = False
        self._last_tick = self._clock.now()
        self._animation_timer.start()
        self.update()
        self.presentation_state_changed.emit()

    def complete_safe_close(self) -> None:
        self._allow_final_close = True
        self._animation_timer.stop()
        self._renderer.close()
        self.close()

    def request_reminder_animation(self) -> bool:
        """Start a content-free reminder visual if the current state permits."""

        try:
            self._animation.request_reminder_animation()
        except PetStateTransitionError:
            return False
        self._sync_renderer_state()
        self.update()
        return True

    def request_thinking_animation(self) -> bool:
        try:
            self._animation.request_thinking_animation()
        except PetStateTransitionError:
            return False
        self._sync_renderer_state()
        self.update()
        return True

    def request_walk(self, direction: PetFacing) -> bool:
        try:
            self._animation.request_walk(direction)
        except PetStateTransitionError:
            return False
        self._sync_renderer_state()
        self.update()
        return True

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        self._renderer.render(painter, self._animation.frame)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._renderer.set_viewport(
            Size(event.size().width(), event.size().height())
        )
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() is Qt.MouseButton.LeftButton
            and self._animation.motion.accepts_interaction
        ):
            try:
                self._animation.start_dragging()
            except PetStateTransitionError:
                event.ignore()
                return
            self._sync_renderer_state()
            global_position = event.globalPosition()
            self._drag_offset = Point(
                global_position.x() - self.x(),
                global_position.y() - self.y(),
            )
            self.update()
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self.motion_state is PetMotionState.DRAGGING
            and self._drag_offset is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
        ):
            global_position = event.globalPosition()
            snapshot = self._animation.motion.drag_to(
                Point(
                    global_position.x() - self._drag_offset.x,
                    global_position.y() - self._drag_offset.y,
                ),
                self._workspaces(),
            )
            self.move(
                round(snapshot.position.x),
                round(snapshot.position.y),
            )
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() is Qt.MouseButton.LeftButton
            and self.motion_state is PetMotionState.DRAGGING
        ):
            self._drag_offset = None
            self._animation.release_drag()
            self._sync_renderer_state()
            self.update()
            event.accept()
            return
        event.ignore()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self.lifecycle_state is PetLifecycleState.CLOSING:
            event.ignore()
            return
        if self._context_menu is not None:
            self._context_menu.deleteLater()
        menu = QMenu(self)
        self._context_menu = menu

        pause_action = QAction(
            (
                "Continue"
                if self.lifecycle_state is PetLifecycleState.PAUSED
                else "Pause"
            ),
            menu,
        )
        pause_action.triggered.connect(lambda checked=False: self.toggle_paused())
        menu.addAction(pause_action)

        top_action = QAction("Always on top", menu)
        top_action.setCheckable(True)
        top_action.setChecked(self._always_on_top)
        top_action.toggled.connect(self.set_always_on_top)
        menu.addAction(top_action)

        self._autostart_action = QAction("Start with Windows", menu)
        self._autostart_action.setObjectName(
            "petAutostartEnabledAction"
        )
        self._autostart_action.setCheckable(True)
        self._autostart_action.toggled.connect(
            self._set_autostart_enabled
        )
        menu.addAction(self._autostart_action)
        self._sync_autostart_action()
        menu.addSeparator()

        open_action = QAction("Open Agent window", menu)
        open_action.triggered.connect(
            lambda checked=False: self.open_agent_requested.emit()
        )
        menu.addAction(open_action)

        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(
            lambda checked=False: self.request_safe_exit()
        )
        menu.addAction(exit_action)
        menu.popup(event.globalPos())
        event.accept()

    def _set_autostart_enabled(self, enabled: bool) -> None:
        controller = self._autostart_controller
        if (
            controller is None
            or self.lifecycle_state is PetLifecycleState.CLOSING
        ):
            self._sync_autostart_action()
            return
        controller.set_enabled(
            enabled,
            origin=AutostartOperationOrigin.PET_MENU_ACTION,
        )
        self._sync_autostart_action()

    def _on_autostart_state_changed(self, value: object) -> None:
        del value
        self._sync_autostart_action()

    def _sync_autostart_action(self) -> None:
        action = self._autostart_action
        if action is None:
            return
        controller = self._autostart_controller
        snapshot = (
            AutostartSnapshot.for_status(AutostartStatus.UNAVAILABLE)
            if controller is None
            else controller.snapshot
        )
        blocker = QSignalBlocker(action)
        action.setChecked(snapshot.enabled)
        del blocker
        action.setToolTip(
            snapshot.safe_message
            if controller is None
            else controller.display_message
        )
        action.setEnabled(
            self.lifecycle_state is not PetLifecycleState.CLOSING
            and controller is not None
            and controller.user_toggle_allowed
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_final_close:
            self._animation_timer.stop()
            self._renderer.close()
            event.accept()
            return
        event.ignore()
        self.request_safe_exit()

    def _advance_animation(self) -> None:
        now = self._clock.now()
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now
        snapshot = self._animation.advance(
            elapsed,
            self._workspaces(),
        )
        self._renderer.set_state(
            action_request_for_frame(snapshot.frame)
        )
        self._renderer.update(snapshot.applied_delta_seconds)
        self.move(
            round(snapshot.motion.position.x),
            round(snapshot.motion.position.y),
        )
        self.update()

    def _sync_renderer_state(self) -> None:
        self._renderer.set_state(
            action_request_for_frame(self._animation.frame)
        )

    def _apply_window_flags(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _workspaces(self) -> tuple[Rect, ...]:
        workspaces = tuple(
            Rect(
                screen.availableGeometry().x(),
                screen.availableGeometry().y(),
                screen.availableGeometry().width(),
                screen.availableGeometry().height(),
            )
            for screen in QApplication.screens()
        )
        return workspaces or (Rect(0, 0, 1_920, 1_080),)

    def _primary_workspace(self) -> Rect:
        screen = QApplication.primaryScreen()
        if screen is None:
            return Rect(0, 0, 1_920, 1_080)
        geometry = screen.availableGeometry()
        return Rect(
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        )
