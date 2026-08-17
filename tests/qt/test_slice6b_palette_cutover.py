"""Slice 6B - production Schwarz Right Click -> Action Palette cutover.

Authority: 06 4.3/9.4, 07 21/23-25, 08 15.2, 09 5.1/21.
Slice 6B atomically replaces the production Character Right Click route:
    native QMenu  ->  ShowForegroundOverlayIntent(PALETTE) -> model -> sink -> TOOL host

These tests drive the REAL production composition:
    PetApplicationCoordinator + real FrontendPresentationCoordinator +
    real ActionPaletteEffectSink + real PetWindow seam
with a stub runtime bridge only (backend not part of this presentation cutover).

Frozen contracts proven here:
- RED A/B: Right Click opens the Palette at ROOT; the legacy native QMenu is
  never visible (XOR, one presentation per Right Click);
- RED C: opening executes zero application command / zero Conversation /
  zero system mutation;
- RED D: the host is lazy, single, reused;
- RED E: Ask routes one ConversationOpenOrRestoreIntent through the existing
  presentation model and focuses the conversation input;
- RED F: Character actions dispatch exactly one existing production action;
- RED G: Resume Autonomous reflects the single can_resume_autonomous truth;
- RED H: stale Always-on-Top render never owns the mutation target;
- RED I/J: one physical Schwarz Left Click / a Schwarz Drag while the Palette
  is open preserve the existing character chain (one Interact / Drag, zero
  Conversation);
- RED K: an ordinary outside click dismisses without pass-through;
- RED L: a distinct second Right Click dismisses; a rapid double Right Click
  yields one open result;
- RED M: Escape dismisses at ROOT and returns to ROOT from secondary layers;
- RED N: repeated open/close never duplicates signal wiring.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QPushButton

from arkclaw.application.pet.pet_production_actions import (
    ActionSource,
    ProductionAction,
)
from arkclaw.application.pet.pet_role_pack import (
    AnimationRoleRegistry,
    RoleAnimationBinding,
    build_track0_animation_registry,
)
from arkclaw.application.pet.pet_state import PetMotionState
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    AnimationPlayerCapabilities,
    PetTrack0Controller,
    PlaybackRequest,
    PlaybackToken,
)
from arkclaw.presentation.command_descriptor_adapter import (
    CommandId,
)
from arkclaw.presentation.frontend_presentation import (
    ActionPaletteLayer,
    ConversationOpenOrRestoreIntent,
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
    FrontendPresentationIntent,
    PrimaryPresentation,
    SemanticFocusTarget,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.pet.pet_window import (
    PetLifecycleState,
    PetWindow,
)
from arkclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.ui.action_palette import (
    ActionPaletteHost,
    ActionPaletteWindowStrategy,
)
from arkclaw.presentation.qt.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
    yield application


class _Clock:
    def now(self) -> float:
        return 10.0


class _Player:
    capabilities = AnimationPlayerCapabilities(True, True, True, True)

    def __init__(self) -> None:
        self.requests: list[PlaybackRequest] = []

    def play(self, request: PlaybackRequest) -> PlaybackToken:
        self.requests.append(request)
        return object()

    def clear(self, track: int, mix_seconds: float) -> None:
        del track, mix_seconds


def _build_track0(player: _Player, clock: _Clock) -> PetTrack0Controller:
    return PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(
                        action,
                        "Move"
                        if action
                        in {ProductionAction.MOVE_LEFT, ProductionAction.MOVE_RIGHT}
                        else action.value.title(),
                    )
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )


class _StubBridge(QObject):
    """Minimal runtime bridge surface used by the production coordinator."""

    shutdown_finished = Signal(bool, str)


class _StubMainWindow:
    def __init__(self) -> None:
        self.safe_close_count = 0
        self.presentation_updates: list[tuple[bool, bool, bool, str]] = []

    def request_safe_close(self) -> None:
        self.safe_close_count += 1

    def update_pet_presentation(
        self,
        visible: bool,
        paused: bool,
        always_on_top: bool,
        last_action_label: str,
    ) -> None:
        self.presentation_updates.append(
            (visible, paused, always_on_top, last_action_label)
        )


class _ProductionSpyWindow(PetWindow):
    """Records every Palette-dispatched callback through the existing seam."""

    def __init__(self, **kwargs: object) -> None:
        self.palette_action_requests: list[ProductionAction] = []
        self.palette_resume_count = 0
        self.palette_always_on_top_calls: list[bool] = []
        self.palette_safe_exit_count = 0
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        self.palette_action_requests.append(action)
        return super().request_pet_action(action)

    def resume_pet_autonomous(self) -> ActionOutcome:
        self.palette_resume_count += 1
        return super().resume_pet_autonomous()

    def set_always_on_top(self, enabled: bool) -> None:
        self.palette_always_on_top_calls.append(enabled)
        super().set_always_on_top(enabled)

    def request_safe_exit(self) -> None:
        self.palette_safe_exit_count += 1
        super().request_safe_exit()


class _RecordingFrontendCoordinator(FrontendPresentationCoordinator):
    """Counts every intent the production model receives."""

    def __init__(self, effect_sink: object) -> None:
        self.intents: list[FrontendPresentationIntent] = []
        super().__init__(effect_sink=effect_sink)  # type: ignore[arg-type]

    def dispatch(
        self,
        intent: FrontendPresentationIntent,
    ) -> object:
        self.intents.append(intent)
        return super().dispatch(intent)


class _ProductionEnv:
    def __init__(
        self,
        application: QApplication,
        window: _ProductionSpyWindow,
        track0: PetTrack0Controller,
        player: _Player,
        coordinator: PetApplicationCoordinator,
        main_window: _StubMainWindow,
    ) -> None:
        self.application = application
        self.window = window
        self.track0 = track0
        self.player = player
        self.coordinator = coordinator
        self.main_window = main_window

    def install_recording_coordinator(self) -> _RecordingFrontendCoordinator:
        recording = _RecordingFrontendCoordinator(
            self.coordinator.palette_sink
        )
        self.coordinator.frontend_presentation = recording
        return recording

    @property
    def host(self) -> ActionPaletteHost | None:
        return self.coordinator.palette_sink.host

    @property
    def snapshot(self) -> object:
        return self.coordinator.frontend_presentation.snapshot


def _make_window(
    player: _Player,
    clock: _Clock,
    *,
    always_on_top: bool = True,
    available_actions: frozenset[ProductionAction] = frozenset(
        ProductionAction
    ),
) -> tuple[_ProductionSpyWindow, PetTrack0Controller]:
    track0 = _build_track0(player, clock)
    return (
        _ProductionSpyWindow(
            clock=clock,
            track0=track0,
            always_on_top=always_on_top,
            active_role_pack_id="schwarz-production",
            available_production_actions=available_actions,
        ),
        track0,
    )


@pytest.fixture
def production_env(
    qt_application: QApplication,
) -> Iterator[_ProductionEnv]:
    clock = _Clock()
    player = _Player()
    window, track0 = _make_window(player, clock)
    window.show()
    bridge = _StubBridge()
    main_window = _StubMainWindow()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        window,
    )
    env = _ProductionEnv(
        qt_application,
        window,
        track0,
        player,
        coordinator,
        main_window,
    )
    try:
        yield env
    finally:
        env.application.processEvents()
        # Production lifecycle seam: stop the outside-press poller, detach
        # the shared application event filter, disconnect the Palette
        # request hook, and dispose the sink host so no stale
        # ActionPaletteHost survives into a later test.
        env.coordinator.dispose()
        window.complete_safe_close()
        env.coordinator.deleteLater()
        env.application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _right_click(env: _ProductionEnv) -> None:
    window = env.window
    local = window.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        local,
        window.mapToGlobal(local),
    )
    env.application.sendEvent(window, event)
    env.application.processEvents()


def _open_palette(env: _ProductionEnv) -> ActionPaletteHost:
    _right_click(env)
    host = env.host
    assert host is not None
    assert host.isVisible()
    return host


def _click_row(host: ActionPaletteHost, command_id: CommandId) -> None:
    button = host.row_button(command_id)
    assert button is not None
    assert button.isVisible()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def _click_nav(host: ActionPaletteHost, target: ActionPaletteLayer) -> None:
    button = host.navigation_button(target)
    assert button is not None
    assert button.isVisible()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    # Offscreen rerenders rebuild the rows; let layout/visibility settle so
    # the following row click sees a fully visible Palette.
    QApplication.instance().processEvents()


def _conversation_intents(
    env: _ProductionEnv,
) -> list[FrontendPresentationIntent]:
    recording = env.coordinator.frontend_presentation
    if isinstance(recording, _RecordingFrontendCoordinator):
        return [
            intent
            for intent in recording.intents
            if isinstance(intent, ConversationOpenOrRestoreIntent)
        ]
    return []


# ---------------------------------------------------------------------------
# RED A/B/C - Right Click opens Palette ROOT, XOR with native QMenu, zero action
# ---------------------------------------------------------------------------


def test_startup_has_no_palette_host_and_no_foreground_overlay(
    production_env: _ProductionEnv,
) -> None:
    assert production_env.host is None
    snapshot = production_env.coordinator.frontend_presentation.snapshot
    assert snapshot.foreground_overlay is ForegroundOverlay.NONE
    assert snapshot.palette_layer is ActionPaletteLayer.ROOT
    assert (
        production_env.window.findChild(ActionPaletteHost) is None
    )


def test_pet_window_does_not_own_palette_host_or_descriptors(
    production_env: _ProductionEnv,
) -> None:
    assert not hasattr(production_env.window, "_palette")
    assert not hasattr(production_env.window, "build_command_descriptors")
    assert (
        production_env.coordinator.palette_sink.host is None
    )


def test_right_click_opens_palette_root_and_never_native_menu(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    recording = env.install_recording_coordinator()

    _right_click(env)

    host = env.host
    assert host is not None
    assert host.isVisible()
    assert host.current_layer is ActionPaletteLayer.ROOT
    snapshot = env.coordinator.frontend_presentation.snapshot
    assert snapshot.foreground_overlay is ForegroundOverlay.PALETTE
    assert snapshot.palette_layer is ActionPaletteLayer.ROOT
    # XOR: the legacy native menu must never be visible alongside the Palette.
    assert env.window.findChild(QMenu) is None
    popup = env.application.activePopupWidget()
    assert not isinstance(popup, QMenu)
    # Zero application command on open.
    assert env.player.requests == []
    assert env.window.palette_action_requests == []
    assert env.window.palette_resume_count == 0
    assert env.window.palette_always_on_top_calls == []
    assert _conversation_intents(env) == []
    assert [type(intent).__name__ for intent in recording.intents] == [
        "ShowForegroundOverlayIntent"
    ]


# ---------------------------------------------------------------------------
# RED D - lazy single reusable host + explicit TOOL strategy
# ---------------------------------------------------------------------------


def test_palette_host_is_lazy_reused_and_tool(production_env: _ProductionEnv) -> None:
    env = production_env
    assert env.host is None
    # Fixed fake clock so the rapid-reopen gate is deterministic.
    env.coordinator._palette_clock = lambda: 1.0
    host = _open_palette(env)
    assert env.host is host
    # PySide6 6.11 encodes Tool=11 (embedded Popup bits), so the native
    # strategy is proven by the explicit composition choice, not a bitmask.
    flags = host.windowFlags()
    assert bool(flags & Qt.WindowType.Tool)
    assert (
        env.coordinator.palette_sink.strategy
        is ActionPaletteWindowStrategy.TOOL
    )
    win_id = int(host.winId())
    # Distinct second right click (>= rapid threshold) dismisses.
    env.coordinator._palette_clock = lambda: 2.0
    _right_click(env)
    assert not host.isVisible()
    assert env.host is host
    # Reopen reuses the same host instance and native handle.
    env.coordinator._palette_clock = lambda: 3.0
    _right_click(env)
    assert env.host is host
    assert host.isVisible()
    assert int(host.winId()) == win_id


# ---------------------------------------------------------------------------
# RED E - Ask ArkClaw production trace
# ---------------------------------------------------------------------------


def test_ask_flow_dispatches_one_conversation_intent_and_focuses_input(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    host = _open_palette(env)
    _click_row(host, CommandId.ASK_ARKCLAW)
    env.application.processEvents()

    assert not host.isVisible()
    snapshot = env.coordinator.frontend_presentation.snapshot
    assert snapshot.primary_presentation is PrimaryPresentation.CAPSULE
    assert snapshot.conversation_context is not None
    assert (
        snapshot.semantic_focus_target
        is SemanticFocusTarget.CONVERSATION_INPUT
    )
    assert len(_conversation_intents(env)) == 1
    # Zero backend task: the palette selection never touches the pet action
    # chain and never creates a widget directly.
    assert env.player.requests == []
    assert env.window.palette_action_requests == []


# ---------------------------------------------------------------------------
# RED F - Character command production trace
# ---------------------------------------------------------------------------


def test_character_interact_dispatches_exactly_one_existing_action(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.CHARACTER)
    assert host.current_layer is ActionPaletteLayer.CHARACTER
    _click_row(host, CommandId.INTERACT)
    env.application.processEvents()

    assert env.window.palette_action_requests == [
        ProductionAction.INTERACT
    ]
    assert env.track0.active_request is not None
    assert env.track0.active_request.source is ActionSource.TRAY
    assert not host.isVisible()
    assert _conversation_intents(env) == []


# ---------------------------------------------------------------------------
# RED G - Resume Autonomous single capability owner
# ---------------------------------------------------------------------------


def test_resume_autonomous_valid_dispatches_once(production_env: _ProductionEnv) -> None:
    env = production_env
    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.CHARACTER)
    button = host.row_button(CommandId.RESUME_AUTONOMOUS)
    assert button is not None
    assert button.isEnabled()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    env.application.processEvents()

    assert env.window.palette_resume_count == 1
    assert not host.isVisible()
    assert env.player.requests != []


def test_resume_autonomous_disabled_when_relax_unavailable(
    qt_application: QApplication,
) -> None:
    clock = _Clock()
    player = _Player()
    window, track0 = _make_window(
        player,
        clock,
        available_actions=frozenset(
            {ProductionAction.SIT, ProductionAction.SLEEP}
        ),
    )
    window.show()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, _StubBridge()),
        cast(MainWindow, _StubMainWindow()),
        window,
    )
    env = _ProductionEnv(
        qt_application,
        window,
        track0,
        player,
        coordinator,
        _StubMainWindow(),
    )
    try:
        host = _open_palette(env)
        _click_nav(host, ActionPaletteLayer.CHARACTER)
        button = host.row_button(CommandId.RESUME_AUTONOMOUS)
        assert button is not None
        assert not button.isEnabled()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        env.application.processEvents()
        assert window.palette_resume_count == 0
        assert host.isVisible()
    finally:
        coordinator.dispose()
        window.complete_safe_close()
        coordinator.deleteLater()
        qt_application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ---------------------------------------------------------------------------
# RED H - stale System state never owns the mutation target
# ---------------------------------------------------------------------------


def test_stale_always_on_top_render_uses_current_dispatch_state(
    qt_application: QApplication,
) -> None:
    clock = _Clock()
    player = _Player()
    window, track0 = _make_window(player, clock, always_on_top=False)
    window.show()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, _StubBridge()),
        cast(MainWindow, _StubMainWindow()),
        window,
    )
    env = _ProductionEnv(
        qt_application,
        window,
        track0,
        player,
        coordinator,
        _StubMainWindow(),
    )
    try:
        host = _open_palette(env)
        _click_nav(host, ActionPaletteLayer.SYSTEM)
        row = host.row_button(CommandId.ALWAYS_ON_TOP)
        assert row is not None
        assert host.checked(CommandId.ALWAYS_ON_TOP) is False
        # Authoritative state drifts AFTER the row rendered unchecked.
        window.set_always_on_top(True)
        assert window.always_on_top is True
        window.palette_always_on_top_calls = []
        QTest.mouseClick(row, Qt.MouseButton.LeftButton)
        env.application.processEvents()
        # Target is SET(not current) -> False, never the stale snapshot.
        assert window.palette_always_on_top_calls == [False]
        assert window.always_on_top is False
        assert not host.isVisible()
    finally:
        coordinator.dispose()
        window.complete_safe_close()
        coordinator.deleteLater()
        qt_application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ---------------------------------------------------------------------------
# Disabled current descriptor at dispatch time executes zero
# ---------------------------------------------------------------------------


def test_command_disabled_at_dispatch_time_executes_zero(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.CHARACTER)
    row = host.row_button(CommandId.INTERACT)
    assert row is not None
    assert row.isEnabled()
    # The authoritative action set changes after render; the CURRENT
    # descriptor becomes disabled and must execute zero.
    env.window._available_production_actions = frozenset()  # type: ignore[attr-defined]
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    env.application.processEvents()
    assert env.window.palette_action_requests == []
    assert env.player.requests == []
    assert not host.isVisible()


# ---------------------------------------------------------------------------
# RED I/J - Schwarz Left Click and Drag while Palette open
# ---------------------------------------------------------------------------


def test_one_physical_left_click_schwarz_while_palette_open(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    host = _open_palette(env)

    QTest.mouseClick(
        env.window,
        Qt.MouseButton.LeftButton,
        pos=QPoint(80, 90),
    )
    env.application.processEvents()

    assert not host.isVisible()
    assert env.window.palette_action_requests == []
    assert [r.physical_name for r in env.player.requests] == ["Interact"]
    assert env.track0.active_request is not None
    assert env.track0.active_request.source is ActionSource.USER
    assert _conversation_intents(env) == []


def test_schwarz_drag_while_palette_open_preserves_drag(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    host = _open_palette(env)
    original = env.window.pos()

    QTest.mousePress(
        env.window,
        Qt.MouseButton.LeftButton,
        pos=QPoint(80, 90),
    )
    assert env.window.motion_state is PetMotionState.IDLE
    QTest.mouseMove(env.window, QPoint(30, 30))
    assert env.window.motion_state is PetMotionState.DRAGGING
    assert env.window.pos() != original
    QTest.mouseRelease(
        env.window,
        Qt.MouseButton.LeftButton,
        pos=QPoint(30, 30),
    )

    assert not host.isVisible()
    assert env.window.palette_action_requests == []
    assert _conversation_intents(env) == []
    assert all(
        r.physical_name != "Interact" for r in env.player.requests
    )
    env.application.processEvents()


# ---------------------------------------------------------------------------
# RED K - ordinary outside click dismisses without pass-through
# ---------------------------------------------------------------------------


def test_outside_click_dismisses_palette_without_pass_through(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    host = _open_palette(env)

    outside = QPushButton("outside")
    outside.show()
    clicked: list[bool] = []
    outside.clicked.connect(lambda: clicked.append(True))

    QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
    env.application.processEvents()

    assert not host.isVisible()
    assert clicked == []
    assert env.player.requests == []
    assert env.window.palette_action_requests == []
    assert _conversation_intents(env) == []
    outside.deleteLater()


# ---------------------------------------------------------------------------
# RED L - distinct second Right Click dismisses; rapid double yields one open
# ---------------------------------------------------------------------------


def test_distinct_second_right_click_dismisses_palette(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    env.coordinator._palette_clock = lambda: 1.0
    host = _open_palette(env)
    env.coordinator._palette_clock = lambda: 2.0
    _right_click(env)
    assert not host.isVisible()
    assert env.player.requests == []
    assert env.window.palette_action_requests == []
    assert _conversation_intents(env) == []
    snapshot = env.coordinator.frontend_presentation.snapshot
    assert snapshot.foreground_overlay is ForegroundOverlay.NONE
    assert snapshot.palette_layer is ActionPaletteLayer.ROOT


def test_rapid_double_right_click_yields_one_open_result(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    # Same clock tick: the trailing context event is coalesced, one open.
    env.coordinator._palette_clock = lambda: 1.0
    host = _open_palette(env)
    _right_click(env)
    assert host.isVisible()
    assert host.current_layer is ActionPaletteLayer.ROOT
    assert env.player.requests == []
    assert env.window.palette_action_requests == []


# ---------------------------------------------------------------------------
# RED M - Escape production routing
# ---------------------------------------------------------------------------


def test_escape_dismisses_at_root_and_returns_to_root_from_secondary(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    # Advancing fake clock keeps every reopen a distinct (non-rapid) event.
    clock_values = iter(range(1, 50))
    env.coordinator._palette_clock = lambda: float(next(clock_values))
    host = _open_palette(env)
    QTest.keyClick(host, Qt.Key.Key_Escape)
    env.application.processEvents()
    assert not host.isVisible()
    assert (
        env.coordinator.frontend_presentation.snapshot.foreground_overlay
        is ForegroundOverlay.NONE
    )

    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.CHARACTER)
    assert host.current_layer is ActionPaletteLayer.CHARACTER
    QTest.keyClick(host, Qt.Key.Key_Escape)
    env.application.processEvents()
    assert host.isVisible()
    assert host.current_layer is ActionPaletteLayer.ROOT
    assert (
        env.coordinator.frontend_presentation.snapshot.palette_layer
        is ActionPaletteLayer.ROOT
    )

    _click_nav(host, ActionPaletteLayer.SYSTEM)
    assert host.current_layer is ActionPaletteLayer.SYSTEM
    QTest.keyClick(host, Qt.Key.Key_Escape)
    env.application.processEvents()
    assert host.isVisible()
    assert host.current_layer is ActionPaletteLayer.ROOT


# ---------------------------------------------------------------------------
# RED N - repeated open/close never duplicates signal wiring
# ---------------------------------------------------------------------------


def test_repeated_open_close_then_select_dispatches_exactly_once(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    env.install_recording_coordinator()
    clock_values = iter(range(1, 100))
    env.coordinator._palette_clock = lambda: float(next(clock_values))
    for _step in range(10):
        host = _open_palette(env)
        assert host.isVisible()
        _right_click(env)
        assert not host.isVisible()

    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.CHARACTER)
    _click_row(host, CommandId.INTERACT)
    env.application.processEvents()

    assert env.window.palette_action_requests == [
        ProductionAction.INTERACT
    ]
    assert _conversation_intents(env) == []


# ---------------------------------------------------------------------------
# Quit / Hide keep the existing safe-exit and visibility semantics
# ---------------------------------------------------------------------------


def test_quit_uses_existing_safe_exit_semantic(production_env: _ProductionEnv) -> None:
    env = production_env
    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.SYSTEM)
    _click_row(host, CommandId.QUIT)
    env.application.processEvents()

    assert env.window.palette_safe_exit_count == 1
    assert (
        env.window.lifecycle_state is PetLifecycleState.CLOSING
    )
    assert env.main_window.safe_close_count == 1


def test_hide_pet_routes_through_existing_visibility_semantic(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    host = _open_palette(env)
    _click_nav(host, ActionPaletteLayer.SYSTEM)
    _click_row(host, CommandId.HIDE_PET)
    env.application.processEvents()

    assert not env.window.isVisible()
    assert not host.isVisible()
    assert env.player.requests == []


# ---------------------------------------------------------------------------
# Conversation context life is decoupled from Palette overlay life
# ---------------------------------------------------------------------------


def test_conversation_context_and_draft_survive_palette_cycle(
    production_env: _ProductionEnv,
) -> None:
    env = production_env
    coordinator = env.coordinator
    coordinator.frontend_presentation.dispatch(
        ConversationOpenOrRestoreIntent()
    )
    coordinator.frontend_presentation.apply_draft_edit(
        __import__(
            "arkclaw.presentation.conversation_draft_safety",
            fromlist=["DraftEditIntent"],
        ).DraftEditIntent(text="hello", caret=5)
    )
    context_before = coordinator.frontend_presentation.snapshot.conversation_context
    draft_before = coordinator.frontend_presentation.draft_snapshot
    assert context_before is not None
    assert draft_before.text == "hello"

    env.coordinator._palette_clock = lambda: 1.0
    host = _open_palette(env)
    assert host.isVisible()
    assert (
        coordinator.frontend_presentation.snapshot.foreground_overlay
        is ForegroundOverlay.PALETTE
    )
    env.coordinator._palette_clock = lambda: 2.0
    _right_click(env)
    assert not host.isVisible()

    assert (
        coordinator.frontend_presentation.snapshot.conversation_context
        == context_before
    )
    assert coordinator.frontend_presentation.draft_snapshot == draft_before
# ---------------------------------------------------------------------------
# Production lifecycle isolation (6B review-fix: no cross-test host leak)
# ---------------------------------------------------------------------------


def _build_env(
    qt_application: QApplication,
) -> tuple[_ProductionEnv, _Player]:
    player = _Player()
    window, track0 = _make_window(player, _Clock())
    window.show()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, _StubBridge()),
        cast(MainWindow, _StubMainWindow()),
        window,
    )
    env = _ProductionEnv(
        qt_application,
        window,
        track0,
        player,
        coordinator,
        _StubMainWindow(),
    )
    return env, player


def _palette_host_survivors() -> list[ActionPaletteHost]:
    application = QApplication.instance()
    assert application is not None
    return [
        widget
        for widget in application.topLevelWidgets()
        if isinstance(widget, ActionPaletteHost)
    ]


def _teardown_env(env: _ProductionEnv) -> None:
    env.coordinator.dispose()
    env.window.complete_safe_close()
    env.coordinator.deleteLater()
    QApplication.instance().processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_composition_dispose_isolates_next_composition(
    qt_application: QApplication,
) -> None:
    """Disposing composition A leaves zero Palette hosts; composition B's
    first Right Click lazily creates exactly one new host with no duplicate
    signal wiring (review-fix RED/GREEN isolation proof)."""
    # Composition A: open the Palette, then dispose the whole composition.
    env_a, _ = _build_env(qt_application)
    host_a = _open_palette(env_a)
    assert host_a is not None
    assert _palette_host_survivors() == [host_a]

    _teardown_env(env_a)

    # No A-owned Palette host may survive the owner's dispose.
    assert _palette_host_survivors() == []

    # Composition B: the first Right Click must create exactly one new host.
    env_b, _ = _build_env(qt_application)
    try:
        host_b = _open_palette(env_b)
        assert host_b is not None
        assert host_b is env_b.host
        assert _palette_host_survivors() == [host_b]
        # One selection dispatches exactly one Interact: no duplicate signal
        # can survive from A's or B's wiring.
        _click_nav(host_b, ActionPaletteLayer.CHARACTER)
        _click_row(host_b, CommandId.INTERACT)
        qt_application.processEvents()
        assert env_b.window.palette_action_requests == [
            ProductionAction.INTERACT
        ]
        assert not host_b.isVisible()
    finally:
        _teardown_env(env_b)


def test_repeated_composition_cycles_leave_no_host_or_duplicate_signal(
    qt_application: QApplication,
) -> None:
    """Five create/open/dismiss/dispose cycles must leave no owned Palette
    host and never accumulate duplicate signal wiring (review-fix RED/GREEN)."""
    for _ in range(5):
        env, _ = _build_env(qt_application)
        host = _open_palette(env)
        assert host is not None
        # Dismiss through the presentation model (same seam as a selection /
        # Escape), then dispose the whole composition.
        env.coordinator.frontend_presentation.dispatch(
            DismissForegroundOverlayIntent()
        )
        qt_application.processEvents()
        assert not host.isVisible()
        _teardown_env(env)
        assert _palette_host_survivors() == []

    # After every cycle a fresh composition still creates exactly one host
    # and one click dispatches exactly one application semantic.
    env, _ = _build_env(qt_application)
    try:
        host = _open_palette(env)
        assert host is not None
        assert _palette_host_survivors() == [host]
        _click_nav(host, ActionPaletteLayer.CHARACTER)
        _click_row(host, CommandId.INTERACT)
        qt_application.processEvents()
        assert env.window.palette_action_requests == [
            ProductionAction.INTERACT
        ]
        assert not host.isVisible()
    finally:
        _teardown_env(env)
