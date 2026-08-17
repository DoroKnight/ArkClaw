"""Transparent, frameless window shared by production and fallback pets."""

from __future__ import annotations

import math
import random
from contextlib import suppress
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QRect, QSignalBlocker, Qt, QTimer, Signal, SignalInstance
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QContextMenuEvent,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from arkclaw.application.pet.pet_action_sequence import (
    PetActionName,
    default_animation_registry,
)
from arkclaw.application.pet.pet_animation import (
    MonotonicClock,
    PetAnimationConfig,
    PetAnimationEngine,
    PetRenderFrame,
    SystemMonotonicClock,
)
from arkclaw.application.pet.pet_autonomous_scheduler import AutonomousActionScheduler
from arkclaw.application.pet.pet_geometry import (
    Point,
    Rect,
    Size,
    select_workspace,
)
from arkclaw.application.pet.pet_motion import PetMotionModel
from arkclaw.application.pet.pet_production_actions import (
    ActionSource,
    ProductionAction,
    can_resume_autonomous,
)
from arkclaw.application.pet.pet_render_layout import (
    PetRenderLayout,
    PetRenderLayoutFailure,
    PetRenderSurfaceMode,
)
from arkclaw.application.pet.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
    action_request_for_frame,
)
from arkclaw.application.pet.pet_state import (
    PetFacing,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
)
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    AnimationPlayerCapabilities,
    PetTrack0Controller,
    PlaybackEvent,
    PlaybackRequest,
    PlaybackToken,
)
from arkclaw.application.system.autostart_operation_journal import (
    AutostartOperationOrigin,
)
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.presentation.pet_pointer_gesture import (
    GestureCancelReason,
    GestureDecision,
    PetPointerGesture,
)
from arkclaw.presentation.qt.pet.pet_effect_overlay import PetEffectOverlayWindow
from arkclaw.presentation.qt.pet.pet_renderer import (
    PetRenderer,
    PetRendererSafeCode,
    PlaceholderPetRenderer,
    SafePetRenderer,
)
from arkclaw.presentation.qt.ui.production_action_menu import (
    ProductionActionMenuSection,
    prepare_arkclaw_menu,
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


class _PlaybackEventSource(Protocol):
    def update(self, delta_seconds: float) -> tuple[PlaybackEvent, ...]: ...


@runtime_checkable
class _OverflowSurfaceRenderer(Protocol):
    def plan_layout(
        self,
        body_rect: Rect,
        workspace: Rect,
        device_pixel_ratio: float,
        *,
        display: Rect | None = None,
    ) -> PetRenderLayout | PetRenderLayoutFailure: ...

    def set_render_layout(self, layout: PetRenderLayout) -> None: ...

    def render_surface(self, painter: QPainter) -> None: ...

_PET_WIDTH = 160
_PET_HEIGHT = 180
_TIMER_INTERVAL_MS = 16


def workspace_rect_from_qrect(geometry: QRect) -> Rect:
    """Convert Qt's sized rectangle to the domain's half-open edge contract."""

    return Rect(
        geometry.x(),
        geometry.y(),
        geometry.width(),
        geometry.height(),
    )


def select_workspace_display_pair(
    position: Point,
    window_size: Size,
    pairs: tuple[tuple[Rect, Rect], ...],
) -> tuple[Rect, Rect]:
    """Select an available/full geometry pair without crossing screens."""

    if not pairs:
        fallback = Rect(0, 0, 1_920, 1_080)
        return fallback, fallback
    workspaces = tuple(workspace for workspace, _display in pairs)
    selected = select_workspace(position, window_size, workspaces)
    selected_index = workspaces.index(selected)
    return pairs[selected_index]


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
    action_palette_requested = Signal()

    def __init__(
        self,
        *,
        always_on_top: bool = True,
        renderer: PetRenderer | None = None,
        clock: MonotonicClock | None = None,
        rng: random.Random | None = None,
        animation_config: PetAnimationConfig | None = None,
        autostart_controller: _AutostartUiController | None = None,
        track0: PetTrack0Controller | None = None,
        active_role_pack_id: str = "placeholder",
        available_production_actions: frozenset[ProductionAction] = frozenset(),
        autonomous_scheduler: AutonomousActionScheduler | None = None,
        playback_event_source: _PlaybackEventSource | None = None,
    ) -> None:
        super().__init__()
        self._always_on_top = always_on_top
        self._allow_final_close = False
        self._exit_emitted = False
        self._drag_offset: Point | None = None
        self._right_press_pos: Point | None = None
        self._pointer_gesture = PetPointerGesture()
        self._context_menu: QMenu | None = None
        self._production_action_section: ProductionActionMenuSection | None = None
        self._autostart_controller = autostart_controller
        self._autostart_action: QAction | None = None
        self._active_role_pack_id = active_role_pack_id
        self._available_production_actions = frozenset(
            available_production_actions
        )
        self._playback_event_source = playback_event_source
        selected_renderer = renderer or PlaceholderPetRenderer()
        self._overflow_renderer: _OverflowSurfaceRenderer | None = (
            selected_renderer
            if isinstance(selected_renderer, _OverflowSurfaceRenderer)
            else None
        )
        self._effect_overlay: PetEffectOverlayWindow | None = None
        self._active_render_layout: PetRenderLayout | None = None
        self._active_layout_workspace: Rect | None = None
        self._active_layout_action: PetRendererAction | None = None
        self._special_completion_facing: PetFacing | None = None
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
        self._animation_player: PlaceholderAnimationPlayer | None = None
        selected_track0 = track0
        if selected_track0 is None:
            self._animation_player = PlaceholderAnimationPlayer()
            selected_track0 = PetTrack0Controller(
                player=self._animation_player,
                registry=default_animation_registry(),
                clock=selected_clock,
            )
        self._animation = PetAnimationEngine(
            motion,
            rng=rng,
            config=animation_config,
            track0=selected_track0,
            autonomous_scheduler=autonomous_scheduler,
            clock=selected_clock,
            use_relax_motion_fallback=bool(available_production_actions),
        )
        self._last_device_pixel_ratio = float(self.devicePixelRatioF())
        self._renderer.set_device_pixel_ratio(self._last_device_pixel_ratio)
        self._renderer.initialize(Size(_PET_WIDTH, _PET_HEIGHT))
        if self._renderer.safe_code is not PetRendererSafeCode.NONE:
            self._active_role_pack_id = "placeholder"
            self._available_production_actions = frozenset()
            self._playback_event_source = None
            self._overflow_renderer = None
        elif autonomous_scheduler is not None:
            self._animation.start_autonomous()
        if self._overflow_renderer is not None:
            self._effect_overlay = PetEffectOverlayWindow(
                self._overflow_renderer,
                input_target=self,
            )
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
    def active_role_pack_id(self) -> str:
        return self._active_role_pack_id

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]:
        return self._available_production_actions

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
        self._cancel_pointer_gesture(GestureCancelReason.PAUSE_REQUESTED)
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
        overlay = self._effect_overlay
        if overlay is not None and overlay.isVisible():
            layout = self._active_render_layout
            if layout is not None:
                overlay.show_layout(layout, always_on_top=enabled)
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
        self._cancel_pointer_gesture(GestureCancelReason.CLOSING)
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
        self._hide_effect_overlay()
        if self._effect_overlay is not None:
            self._effect_overlay.close()
            self._effect_overlay = None
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

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        """Submit one tray action without promoting it to direct manipulation."""

        return self._request_pet_action(action, ActionSource.TRAY)

    def request_user_pet_action(self, action: ProductionAction) -> ActionOutcome:
        """Submit one direct pet-window action with USER authority."""

        return self._request_pet_action(action, ActionSource.USER)

    def _request_pet_action(
        self,
        action: ProductionAction,
        source: ActionSource,
    ) -> ActionOutcome:

        if (
            self.lifecycle_state is PetLifecycleState.CLOSING
            or action not in self._available_production_actions
        ):
            return ActionOutcome.INVALID_SEQUENCE
        outcome = self._animation.request_action(action, source)
        self._sync_renderer_state()
        self.update()
        self.presentation_state_changed.emit()
        return outcome

    def resume_pet_autonomous(self) -> ActionOutcome:
        return self._resume_pet_autonomous(ActionSource.TRAY)

    def resume_user_pet_autonomous(self) -> ActionOutcome:
        return self._resume_pet_autonomous(ActionSource.USER)

    def _resume_pet_autonomous(self, source: ActionSource) -> ActionOutcome:
        if not can_resume_autonomous(
            closing=self.lifecycle_state is PetLifecycleState.CLOSING,
            available_actions=self._available_production_actions,
        ):
            return ActionOutcome.INVALID_SEQUENCE
        outcome = self._animation.resume_autonomous(source)
        self._sync_renderer_state()
        self.update()
        self.presentation_state_changed.emit()
        return outcome

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
            global_position = event.globalPosition()
            local_position = event.position()
            try:
                self._pointer_gesture.press(
                    Point(local_position.x(), local_position.y()),
                    Point(global_position.x(), global_position.y()),
                    float(QApplication.startDragDistance()),
                )
            except ValueError:
                event.ignore()
                return
            self._drag_offset = Point(
                local_position.x(),
                local_position.y(),
            )
            event.accept()
            return
        if (
            event.button() is Qt.MouseButton.RightButton
            and self._animation.motion.accepts_interaction
        ):
            global_position = event.globalPosition()
            self._right_press_pos = Point(
                global_position.x(),
                global_position.y(),
            )
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if bool(event.buttons() & Qt.MouseButton.LeftButton):
            global_position = event.globalPosition()
            decision = self._pointer_gesture.move(
                Point(global_position.x(), global_position.y())
            )
            if decision is GestureDecision.BEGIN_DRAG:
                try:
                    outcome = self._animation.start_dragging()
                except PetStateTransitionError:
                    self._pointer_gesture.cancel(GestureCancelReason.CLOSING)
                    event.ignore()
                    return
                if outcome not in {
                    ActionOutcome.ACCEPTED,
                    ActionOutcome.LEGACY_DIRECT,
                }:
                    self._pointer_gesture.cancel(
                        GestureCancelReason.PLAYBACK_DEGRADED
                    )
                    event.ignore()
                    return
                self._sync_renderer_state()
            if decision not in {GestureDecision.BEGIN_DRAG, GestureDecision.DRAG}:
                event.accept()
                return
            offset = self._drag_offset
            if offset is None:
                event.ignore()
                return
            snapshot = self._animation.motion.drag_to(
                Point(
                    global_position.x() - offset.x,
                    global_position.y() - offset.y,
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
        if event.button() is Qt.MouseButton.LeftButton:
            global_position = event.globalPosition()
            decision = self._pointer_gesture.release(
                Point(global_position.x(), global_position.y())
            )
            self._drag_offset = None
            if decision is GestureDecision.RELEASE_ACTIVE_DRAG:
                self._animation.release_drag(self._workspaces())
                self._sync_renderer_state()
                self.update()
                event.accept()
                return
            if decision is GestureDecision.CLICK:
                self.request_user_pet_action(ProductionAction.INTERACT)
                event.accept()
                return
        if event.button() is Qt.MouseButton.RightButton:
            press_pos = self._right_press_pos
            self._right_press_pos = None
            if (
                press_pos is not None
                and self._animation.motion.accepts_interaction
            ):
                global_position = event.globalPosition()
                distance = abs(global_position.x() - press_pos.x) + abs(
                    global_position.y() - press_pos.y
                )
                if distance <= float(QApplication.startDragDistance()):
                    event.accept()
                    self.action_palette_requested.emit()
                    return
            event.ignore()
            return
        event.ignore()

    def _cancel_pointer_gesture(self, reason: GestureCancelReason) -> None:
        self._right_press_pos = None
        decision = self._pointer_gesture.cancel(reason)
        self._drag_offset = None
        if decision is GestureDecision.RELEASE_ACTIVE_DRAG:
            with suppress(PetStateTransitionError):
                self._animation.release_drag(self._workspaces())
        elif decision is GestureDecision.ABORT_ACTIVE_DRAG:
            self._animation.contain_renderer_failure()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Production Schwarz Right Click -> Action Palette (Slice 6B).

        The completed right-click semantic is a presentation request only:
        the window emits ``action_palette_requested`` and the production
        composition routes it to ``ShowForegroundOverlayIntent(PALETTE)``.
        The legacy native QMenu construction is preserved verbatim in
        ``_show_legacy_context_menu`` for rollback / tray parity; production
        no longer instantiates it (06 4.3, 08 15.2, 09 21).
        """
        if self.lifecycle_state is PetLifecycleState.CLOSING:
            event.ignore()
            return
        self._right_press_pos = None
        event.accept()
        self.action_palette_requested.emit()

    def _show_legacy_context_menu(
        self,
        event: QContextMenuEvent,
    ) -> None:
        """Preserved legacy native QMenu route (Slice 6B dead-but-kept).

        Non-blocking TBD: cleanup only when every consumer is migrated.
        """
        if self._context_menu is not None:
            self._context_menu.deleteLater()
        menu = QMenu(self)
        prepare_arkclaw_menu(
            menu,
            object_name="arkclawPetContextMenu",
        )
        self._context_menu = menu

        pause_action = QAction(
            (
                "Continue"
                if self.lifecycle_state is PetLifecycleState.PAUSED
                else "Pause"
            ),
            menu,
        )
        pause_action.setObjectName("petPauseAction")
        pause_action.triggered.connect(lambda checked=False: self.toggle_paused())
        menu.addAction(pause_action)

        top_action = QAction("Always on top", menu)
        top_action.setObjectName("petAlwaysOnTopAction")
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

        section = ProductionActionMenuSection(
            menu,
            request_action=self.request_user_pet_action,
            resume_autonomous=self.resume_user_pet_autonomous,
        )
        section.update(
            role_pack_id=self._active_role_pack_id,
            available_actions=self._available_production_actions,
            closing=False,
        )
        self._production_action_section = section
        menu.addSeparator()

        open_action = QAction("Open Agent window", menu)
        open_action.setText("Open ArkClaw Control Center")
        open_action.setObjectName("openControlCenterAction")
        open_action.triggered.connect(
            lambda checked=False: self.open_agent_requested.emit()
        )
        menu.addAction(open_action)

        exit_action = QAction("Exit", menu)
        exit_action.setObjectName("quitArkClawAction")
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
            if self._effect_overlay is not None:
                self._effect_overlay.close()
                self._effect_overlay = None
            self._renderer.close()
            event.accept()
            return
        event.ignore()
        self.request_safe_exit()

    def hideEvent(self, event: QHideEvent) -> None:
        self._cancel_pointer_gesture(GestureCancelReason.WINDOW_HIDDEN)
        self._hide_effect_overlay()
        super().hideEvent(event)

    def _advance_animation(self) -> None:
        current_ratio = float(self.devicePixelRatioF())
        if not math.isclose(current_ratio, self._last_device_pixel_ratio):
            self._renderer.set_device_pixel_ratio(current_ratio)
            self._last_device_pixel_ratio = current_ratio
        now = self._clock.now()
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now
        snapshot = self._animation.advance(
            elapsed,
            self._workspaces(),
        )
        if self._playback_event_source is not None:
            try:
                playback_events = self._playback_event_source.update(
                    snapshot.applied_delta_seconds
                )
                for playback_event in playback_events:
                    self._animation.handle_playback_event(
                        playback_event,
                        special_completion_facing=(
                            self._special_completion_facing
                        ),
                    )
            except Exception:
                self._animation.contain_renderer_failure()
                self._playback_event_source = None
                self._active_role_pack_id = "placeholder"
                self._available_production_actions = frozenset()
        request = action_request_for_frame(snapshot.frame)
        self._renderer.set_state(request)
        layout = self._prepare_render_layout(request)
        # Move to the authoritative motion position after any render-layout
        # avoidance commit. The pre-tick snapshot position would overwrite an
        # avoided edge position and misalign the body from the overlay.
        motion_model = self._animation.motion
        self.move(
            round(motion_model.position.x),
            round(motion_model.position.y),
        )
        controller = self._overflow_renderer
        if layout is not None and controller is not None:
            controller.set_render_layout(layout)
        self._renderer.update(snapshot.applied_delta_seconds)
        if (
            self._available_production_actions
            and self._renderer.safe_code is not PetRendererSafeCode.NONE
        ):
            self._animation.contain_renderer_failure()
            self._playback_event_source = None
            self._active_role_pack_id = "placeholder"
            self._available_production_actions = frozenset()
            self._sync_renderer_state()
            self._hide_effect_overlay()
        else:
            self._publish_surface_owner(layout)
        self.update()

    def _sync_renderer_state(self) -> None:
        self._renderer.set_state(
            action_request_for_frame(self._animation.frame)
        )

    def _prepare_render_layout(
        self,
        request: PetRendererActionRequest,
    ) -> PetRenderLayout | None:
        controller = self._overflow_renderer
        if controller is None:
            return None
        motion_model = self._animation.motion
        motion = motion_model.snapshot
        window_size = motion_model.window_size
        body_rect = Rect(
            motion.position.x,
            motion.position.y,
            window_size.width,
            window_size.height,
        )
        display: Rect | None = None
        if request.action is PetRendererAction.SITTING:
            workspace, display = select_workspace_display_pair(
                motion.position,
                window_size,
                self._workspace_display_pairs(),
            )
        else:
            workspace = select_workspace(
                motion.position,
                window_size,
                self._workspaces(),
            )
        if (
            request.action is PetRendererAction.SPECIAL
            and self._active_layout_action is PetRendererAction.SPECIAL
            and self._active_render_layout is not None
        ):
            if workspace == self._active_layout_workspace:
                return self._active_render_layout
            # A material screen/workspace change invalidates the immutable
            # Special composition. End it instead of flipping or rescaling it.
            self._animation.contain_renderer_failure()
            self._animation.start_autonomous()
            request = action_request_for_frame(self._animation.frame)
            self._renderer.set_state(request)
            self._hide_effect_overlay()
        try:
            if request.action is PetRendererAction.SITTING:
                result = controller.plan_layout(
                    body_rect,
                    workspace,
                    self._last_device_pixel_ratio,
                    display=display,
                )
            else:
                result = controller.plan_layout(
                    body_rect,
                    workspace,
                    self._last_device_pixel_ratio,
                )
            if isinstance(result, PetRenderLayoutFailure):
                self._animation.contain_renderer_failure()
                self._hide_effect_overlay()
                return None
            # A resolved body position that differs from the current desktop
            # position becomes the official motion position for this tick.
            resolved = result.resolved_body_position
            current = motion.position
            if not (
                math.isclose(resolved.x, current.x)
                and math.isclose(resolved.y, current.y)
            ):
                try:
                    motion_model.place_for_render_layout(resolved, workspace)
                except (PetStateTransitionError, ValueError):
                    self._animation.contain_renderer_failure()
                    self._hide_effect_overlay()
                    return None
        except Exception:
            self._animation.contain_renderer_failure()
            self._hide_effect_overlay()
            return None
        self._active_render_layout = result
        self._active_layout_workspace = workspace
        self._active_layout_action = request.action
        self._special_completion_facing = (
            result.effective_facing
            if request.action is PetRendererAction.SPECIAL
            and result.effective_facing is not request.facing
            else None
        )
        return result

    def _publish_surface_owner(self, layout: PetRenderLayout | None) -> None:
        overlay = self._effect_overlay
        if layout is None or overlay is None:
            return
        if layout.mode is PetRenderSurfaceMode.OVERFLOW:
            overlay.show_layout(layout, always_on_top=self._always_on_top)
            overlay.update()
            self.update()
            return
        # QWidget.update() only schedules a future paint. Repaint the prepared
        # BODY frame synchronously before removing the old overflow owner.
        self.repaint()
        overlay.retire_surface()

    def _hide_effect_overlay(self) -> None:
        overlay = self._effect_overlay
        if overlay is not None:
            overlay.hide_surface()

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
            workspace_rect_from_qrect(screen.availableGeometry())
            for screen in QApplication.screens()
        )
        return workspaces or (Rect(0, 0, 1_920, 1_080),)

    def _workspace_display_pairs(self) -> tuple[tuple[Rect, Rect], ...]:
        return tuple(
            (
                workspace_rect_from_qrect(screen.availableGeometry()),
                workspace_rect_from_qrect(screen.geometry()),
            )
            for screen in QApplication.screens()
        )

    def _primary_workspace(self) -> Rect:
        screen = QApplication.primaryScreen()
        if screen is None:
            return Rect(0, 0, 1_920, 1_080)
        geometry = screen.availableGeometry()
        return workspace_rect_from_qrect(geometry)
