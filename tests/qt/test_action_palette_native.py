"""Slice 6A - native Windows Tool-vs-Popup Palette window strategy spike.

Authority: 08 15.1 (Slice 6A), 09 5.1 (K/L routing), 06 4.1/4.2/6/7/9.4,
07 21/23.  This harness measures real Windows top-level behaviour for both
candidates against the frozen interaction contract:

K - explicit Schwarz Left Click while Palette open
    -> Palette dismiss -> exactly one Interact -> zero Conversation
    -> no replay / no second click
L - ordinary outside target != Schwarz
    -> Palette dismiss -> event consumed -> zero Character/Conversation

The harness is spike-only: it composes the inactive ActionPaletteEffectSink
with the real production Schwarz composition and drives real native mouse
input.  Production Schwarz Right Click is untouched (Slice 6B owns the
cutover).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_render_layout import PetRenderSurfaceMode
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.bootstrap.pet_production import (
    create_optional_production_pet_composition,
)
from arkclaw.presentation.command_descriptor_adapter import (
    CommandDescriptorSource,
)
from arkclaw.presentation.frontend_presentation import (
    ActionPaletteLayer,
    ConversationOpenOrRestoreIntent,
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
    FrontendPresentationIntent,
    FrontendPresentationModel,
    SetPaletteLayerIntent,
    ShowForegroundOverlayIntent,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.pet.pet_window import (
    PetLifecycleState,
    PetWindow,
)
from arkclaw.presentation.qt.ui.action_palette import (
    ActionPaletteEffectSink,
    ActionPaletteHost,
    ActionPaletteWindowStrategy,
)

_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080

_EVIDENCE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    ".pytest_tmp_slice6a_evidence.json",
)


def _process_until(
    application: QApplication,
    predicate: Callable[[], bool],
    timeout: float = 4.0,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    application.processEvents()
    return bool(predicate())


def _load_user32() -> Any:
    user32 = ctypes.windll.user32
    user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
    user32.GetCursorPos.restype = ctypes.wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = ctypes.wintypes.BOOL
    user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
    user32.WindowFromPoint.restype = ctypes.wintypes.HWND
    user32.GetWindowRect.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.POINTER(ctypes.wintypes.RECT),
    ]
    user32.GetWindowRect.restype = ctypes.wintypes.BOOL
    user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.wintypes.LONG
    user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
    user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
    return user32


class _ProductionPaletteSource:
    """Read-only CommandDescriptorSource projection of the live PetWindow."""

    def __init__(self, window: PetWindow) -> None:
        self._window = window

    @property
    def pet_visible(self) -> bool:
        return self._window.isVisible()

    @property
    def pet_paused(self) -> bool:
        return self._window.lifecycle_state is PetLifecycleState.PAUSED

    @property
    def pet_always_on_top(self) -> bool:
        return self._window.always_on_top

    @property
    def pet_closing(self) -> bool:
        return self._window.lifecycle_state is PetLifecycleState.CLOSING

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]:
        return self._window.available_pet_actions

    @property
    def autostart_snapshot(self) -> AutostartSnapshot:
        return AutostartSnapshot.for_status(AutostartStatus.DISABLED)

    @property
    def autostart_busy(self) -> bool:
        return False


class _ProductionPaletteDispatcher:
    """Routes Palette selection back to the existing PetWindow callbacks."""

    def __init__(self, window: PetWindow) -> None:
        self._window = window
        self.selection_calls: list[tuple[str, tuple[object, ...]]] = []

    @property
    def pet_always_on_top(self) -> bool:
        return self._window.always_on_top

    @property
    def autostart_enabled(self) -> bool:
        return False

    def request_pet_action(self, action: ProductionAction) -> object:
        self.selection_calls.append(("request_pet_action", (action,)))
        return self._window.request_user_pet_action(action)

    def resume_pet_autonomous(self) -> object:
        self.selection_calls.append(("resume_pet_autonomous", ()))
        return self._window.resume_pet_autonomous()

    def toggle_paused(self) -> None:
        self.selection_calls.append(("toggle_paused", ()))
        self._window.toggle_paused()

    def set_always_on_top(self, enabled: bool) -> None:
        self.selection_calls.append(("set_always_on_top", (enabled,)))
        self._window.set_always_on_top(enabled)

    def set_autostart_enabled(self, enabled: bool) -> None:
        self.selection_calls.append(("set_autostart_enabled", (enabled,)))

    def open_agent_window(self) -> None:
        self.selection_calls.append(("open_agent_window", ()))

    def toggle_pet_visibility(self) -> None:
        self.selection_calls.append(("toggle_pet_visibility", ()))

    def request_safe_exit(self) -> None:
        self.selection_calls.append(("request_safe_exit", ()))

    def dispatch_presentation_intent(
        self,
        intent: FrontendPresentationIntent,
    ) -> object:
        self.selection_calls.append(("dispatch_presentation_intent", (intent,)))
        return None


class _PaletteHarness:
    """One Palette integration (sink + coordinator) for a given strategy."""

    def __init__(
        self,
        window: PetWindow,
        strategy: ActionPaletteWindowStrategy,
    ) -> None:
        self.window = window
        self.strategy = strategy
        self.conversation_intents: list[FrontendPresentationIntent] = []
        self.source: CommandDescriptorSource = _ProductionPaletteSource(window)
        self.dispatcher = _ProductionPaletteDispatcher(window)
        self.sink = ActionPaletteEffectSink(
            source=self.source,
            dispatcher=self.dispatcher,
            strategy=strategy,
        )
        self.coordinator = FrontendPresentationCoordinator(
            model=FrontendPresentationModel(),
            effect_sink=self.sink,
        )
        self.sink.attach_intent_handler(self._route_intent)

    def _route_intent(self, intent: FrontendPresentationIntent) -> None:
        if isinstance(intent, ConversationOpenOrRestoreIntent):
            self.conversation_intents.append(intent)
        self.coordinator.dispatch(intent)

    @property
    def host(self) -> ActionPaletteHost | None:
        return self.sink.host

    def open(self) -> ActionPaletteHost:
        """Open at ROOT through the model/coordinator (blocks for POPUP)."""
        self.coordinator.dispatch(
            ShowForegroundOverlayIntent(ForegroundOverlay.PALETTE)
        )
        host = self.sink.host
        assert host is not None
        return host

    def dismiss(self) -> None:
        self.coordinator.dispatch(DismissForegroundOverlayIntent())


@pytest.fixture(scope="module")
def native_env() -> Iterator[dict[str, Any]]:
    if os.name != "nt":
        pytest.skip("requires native Windows input")
    if (
        os.environ.get("ARKCLAW_SPINE38_BRIDGE_DLL") is None
        or os.environ.get("ARKCLAW_PET_ROLE_MANIFEST") is None
    ):
        pytest.skip("requires the production Schwarz manifest and bridge")
    application = QApplication.instance() or QApplication([])
    if application.platformName() != "windows":
        pytest.skip("requires the Qt windows platform plugin")
    composition = create_optional_production_pet_composition()
    assert composition is not None
    window = PetWindow(
        renderer=composition.renderer,
        track0=composition.track0,
        active_role_pack_id=composition.role_pack_id,
        available_production_actions=composition.available_actions,
        playback_event_source=composition.playback_event_source,
    )
    overlay = window._effect_overlay
    assert overlay is not None
    window.show()
    application.processEvents()
    user32 = _load_user32()
    old_cursor = ctypes.wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(old_cursor))
    tool = _PaletteHarness(window, ActionPaletteWindowStrategy.TOOL)
    popup = _PaletteHarness(window, ActionPaletteWindowStrategy.POPUP)
    created_harnesses = [tool, popup]

    def make_harness(
        strategy: ActionPaletteWindowStrategy,
    ) -> _PaletteHarness:
        harness = _PaletteHarness(window, strategy)
        created_harnesses.append(harness)
        return harness

    evidence: dict[str, Any] = {}
    env: dict[str, Any] = {
        "application": application,
        "composition": composition,
        "window": window,
        "overlay": overlay,
        "user32": user32,
        "tool": tool,
        "popup": popup,
        "make_harness": make_harness,
        "evidence": evidence,
    }
    try:
        yield env
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, None)  # safety LEFTUP
        user32.mouse_event(0x0010, 0, 0, 0, None)  # safety RIGHTUP
        user32.ReleaseCapture()
        # Teardown hygiene (6B review-fix): dispose every harness sink so no
        # owned ActionPaletteHost survives this module, then flush Qt deferred
        # deletion before the shared application proceeds to later suites.
        for harness in created_harnesses:
            harness.sink.dispose()
        application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.complete_safe_close()
        window.deleteLater()
        application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        user32.SetCursorPos(old_cursor.x, old_cursor.y)
        with open(_EVIDENCE_PATH, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2)


def _publish_initial_action(env: dict[str, Any], action: ProductionAction) -> None:
    application = env["application"]
    window = env["window"]
    overlay = env["overlay"]
    user32 = env["user32"]
    # Safety: release any stuck native drag left by an earlier scenario.
    user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP
    application.processEvents()
    if window.motion_state.value == "dragging":
        assert _process_until(
            application,
            lambda: window.motion_state.value != "dragging",
            timeout=2.0,
        )
    outcome = window.request_user_pet_action(action)
    deadline = time.monotonic() + 8.0
    # A previous scenario (e.g. an Interact click) may still own the track:
    # drive the animation forward until the requested action is accepted.
    while outcome is not ActionOutcome.ACCEPTED and time.monotonic() < deadline:
        window.physics_timer.timeout.emit()
        application.processEvents()
        time.sleep(0.01)
        outcome = window.request_user_pet_action(action)
    assert outcome is ActionOutcome.ACCEPTED, outcome
    window.physics_timer.timeout.emit()
    application.processEvents()
    overlay.repaint()
    application.processEvents()
    # K/L drive the real Schwarz overflow surface, so the pet must publish
    # an OVERFLOW layout with the overlay visible (SIT / SPECIAL; RELAX
    # renders a BODY layout with the overlay hidden).
    assert _process_until(application, lambda: overlay.isVisible()), (
        f"overlay did not become visible after {action}"
    )
    layout = window._active_render_layout
    assert layout is not None
    assert layout.mode is PetRenderSurfaceMode.OVERFLOW


def _schwarz_native_point(env: dict[str, Any]) -> ctypes.wintypes.POINT:
    application = env["application"]
    window = env["window"]
    overlay = env["overlay"]
    user32 = env["user32"]
    layout = window._active_render_layout
    assert layout is not None
    assert layout.mode is PetRenderSurfaceMode.OVERFLOW
    assert _process_until(application, lambda: overlay.isVisible())
    body_center = QPoint(
        round(layout.body_window_offset.x) + window.width() // 2,
        round(layout.body_window_offset.y) + window.height() // 2,
    )
    native_rect = ctypes.wintypes.RECT()
    assert user32.GetWindowRect(
        int(overlay.winId()), ctypes.byref(native_rect)
    )
    native_width = native_rect.right - native_rect.left
    native_height = native_rect.bottom - native_rect.top
    return ctypes.wintypes.POINT(
        native_rect.left
        + round(body_center.x() * native_width / overlay.width()),
        native_rect.top
        + round(body_center.y() * native_height / overlay.height()),
    )


def _far_corner_from(
    point: ctypes.wintypes.POINT,
    geometry: Any,
) -> tuple[int, int]:
    corners = (
        (geometry.left(), geometry.top()),
        (geometry.right() - 260, geometry.top()),
        (geometry.left(), geometry.bottom() - 320),
        (geometry.right() - 260, geometry.bottom() - 320),
    )
    return max(
        corners,
        key=lambda corner: (corner[0] - point.x) ** 2
        + (corner[1] - point.y) ** 2,
    )


def _outside_native_point(
    env: dict[str, Any],
    excluded: tuple[int, ...],
) -> ctypes.wintypes.POINT | None:
    user32 = env["user32"]
    screen = QApplication.primaryScreen()
    assert screen is not None
    geometry = screen.availableGeometry()
    candidates = (
        (geometry.left() + 6, geometry.top() + 6),
        (geometry.right() - 8, geometry.top() + 6),
        (geometry.left() + 6, geometry.bottom() - 8),
        (geometry.right() - 8, geometry.bottom() - 8),
    )
    for x, y in candidates:
        point = ctypes.wintypes.POINT(x, y)
        handle = int(user32.WindowFromPoint(point))
        if handle not in excluded:
            return point
    return None


def _click(user32: Any, point: ctypes.wintypes.POINT) -> None:
    assert user32.SetCursorPos(point.x, point.y)
    user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
    time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP


def _drag(
    user32: Any,
    start: ctypes.wintypes.POINT,
    target: ctypes.wintypes.POINT,
) -> None:
    assert user32.SetCursorPos(start.x, start.y)
    user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
    assert user32.SetCursorPos(target.x, target.y)


def _position_away(
    env: dict[str, Any],
    host: ActionPaletteHost,
    anchor: ctypes.wintypes.POINT,
) -> None:
    screen = QApplication.primaryScreen()
    assert screen is not None
    corner = _far_corner_from(anchor, screen.availableGeometry())
    host.move(corner[0], corner[1])
    env["application"].processEvents()


# ---------------------------------------------------------------------------
# TOOL candidate
# ---------------------------------------------------------------------------


def test_tool_candidate_focus_and_root_escape(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    harness = native_env["tool"]
    host = harness.open()
    assert host.isVisible()
    # The focus contract is proven by the Qt focus owner: activate the host
    # explicitly (a background pytest process cannot win the OS foreground
    # lock on its own), then assert the focus widget lives inside the host
    # and that Escape reaches that widget.
    host.activateWindow()
    application.setActiveWindow(host)
    host.setFocus()
    application.processEvents()
    focus_widget = application.focusWidget()
    focus_in_host = focus_widget is not None and (
        focus_widget is host or host.isAncestorOf(focus_widget)
    )
    native_env["evidence"]["tool_focus"] = (
        "PASS-focus-in-host"
        if focus_in_host
        else f"focus-not-in-host:{focus_widget!r}"
    )
    native_env["evidence"]["tool_native_active"] = bool(host.isActiveWindow())
    assert focus_in_host
    QTest.keyClick(host, Qt.Key.Key_Escape)
    assert _process_until(application, lambda: not host.isVisible())
    assert harness.dispatcher.selection_calls == []
    assert harness.conversation_intents == []
    native_env["evidence"]["tool_root_escape"] = "PASS"


def test_tool_candidate_secondary_escape_returns_to_root(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    harness = native_env["tool"]
    host = harness.open()
    assert host.isVisible()
    harness.coordinator.dispatch(
        SetPaletteLayerIntent(ActionPaletteLayer.CHARACTER)
    )
    assert _process_until(
        application,
        lambda: host.current_layer is ActionPaletteLayer.CHARACTER,
    )
    QTest.keyClick(host, Qt.Key.Key_Escape)
    assert _process_until(
        application,
        lambda: host.current_layer is ActionPaletteLayer.ROOT,
    )
    assert host.isVisible()
    assert harness.dispatcher.selection_calls == []
    native_env["evidence"]["tool_secondary_escape"] = "PASS"


def test_tool_candidate_l_outside_click_no_pass_through(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    composition = native_env["composition"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    harness = native_env["tool"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    before = composition.track0.state.confirmed_epoch
    host = harness.open()
    screen = QApplication.primaryScreen()
    assert screen is not None
    anchor = ctypes.wintypes.POINT(
        screen.availableGeometry().center().x(),
        screen.availableGeometry().center().y(),
    )
    _position_away(native_env, host, anchor)
    excluded = (int(overlay.winId()), int(window.winId()), int(host.winId()))
    outside = _outside_native_point(native_env, excluded)
    assert outside is not None
    _click(user32, outside)
    application.processEvents()
    after = composition.track0.state.confirmed_epoch
    assert (after is None) == (before is None)
    if after is not None and before is not None:
        assert after.generation == before.generation
        assert after.physical_name == before.physical_name
    assert harness.conversation_intents == []
    assert harness.dispatcher.selection_calls == []
    # Tool has no native auto-dismiss: the ordinary outside click is not
    # swallowed and the Palette stays open until the presentation seam
    # routes the dismissal (the frozen 6B design).
    assert host.isVisible()
    harness.dismiss()
    assert _process_until(application, lambda: not host.isVisible())
    native_env["evidence"]["tool_outside_dismiss"] = "PASS-with-seam"
    native_env["evidence"]["tool_outside_leakage"] = "PASS-zero-action"


def test_tool_candidate_k_schwarz_click_exactly_one_interact(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    composition = native_env["composition"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    harness = native_env["tool"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)
    assert int(user32.WindowFromPoint(point)) == int(overlay.winId())

    host = harness.open()
    _position_away(native_env, host, point)
    _click(user32, point)
    assert _process_until(
        application,
        lambda: (
            composition.track0.state.confirmed_epoch is not None
            and composition.track0.state.confirmed_epoch.physical_name
            == "Interact"
        ),
    )
    epoch = composition.track0.state.confirmed_epoch
    assert epoch is not None
    generation = epoch.generation
    # No replay / no second click: the single physical click produced one
    # confirmed Interact epoch that stays stable.
    time.sleep(0.35)
    application.processEvents()
    assert composition.track0.state.confirmed_epoch is not None
    assert composition.track0.state.confirmed_epoch.generation == generation
    assert harness.conversation_intents == []
    assert harness.dispatcher.selection_calls == []
    # Tool has no native grab: the Schwarz click reached PetWindow and the
    # Palette dismisses through the presentation seam (frozen 6B design).
    assert host.isVisible()
    harness.dismiss()
    assert _process_until(application, lambda: not host.isVisible())
    native_env["evidence"]["tool_k_interact"] = "PASS-exactly-one"
    native_env["evidence"]["tool_k_dismiss"] = "PASS-presentation-seam"


def test_tool_candidate_drag_continuity_while_palette_open(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    composition = native_env["composition"]
    user32 = native_env["user32"]
    harness = native_env["tool"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    start = _schwarz_native_point(native_env)
    target = ctypes.wintypes.POINT(start.x - 40, start.y - 30)
    before = composition.track0.state.confirmed_epoch
    assert before is not None
    host = harness.open()
    _position_away(native_env, host, start)
    _drag(user32, start, target)
    assert _process_until(
        application,
        lambda: window.motion_state.value == "dragging",
    )
    after = composition.track0.state.confirmed_epoch
    assert after is not None
    # Drag must never emit Interact.  The pet may settle to its autonomous
    # Relax epoch while the drag gesture owns motion, but never Interact.
    assert after.physical_name != "Interact"
    assert harness.conversation_intents == []
    assert harness.dispatcher.selection_calls == []
    # Authority 06 4.2: Drag starts -> Palette dismisses.
    harness.dismiss()
    assert _process_until(application, lambda: not host.isVisible())
    user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP
    assert _process_until(
        application,
        lambda: window.motion_state.value != "dragging",
    )
    native_env["evidence"]["tool_drag_continuity"] = "PASS"


def test_tool_candidate_z_order_stable_under_overlay_publication(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    harness = native_env["tool"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    host = harness.open()
    win_id = int(host.winId())
    assert user32.IsWindowVisible(win_id)
    for _ in range(60):
        window.physics_timer.timeout.emit()
        application.processEvents()
        overlay.repaint()
        application.processEvents()
    assert host.isVisible()
    assert int(host.winId()) == win_id
    assert user32.IsWindowVisible(win_id)
    # Independent top-level: not a child of the continuously published
    # OVERFLOW surface and no native handle churn.
    assert host.window() is host
    assert win_id != int(overlay.winId())
    harness.dismiss()
    assert _process_until(application, lambda: not host.isVisible())
    native_env["evidence"]["tool_z_order_stable"] = "PASS"


def test_tool_candidate_transient_identity_and_show_hide_stability(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    user32 = native_env["user32"]
    harness = native_env["tool"]
    first_win_id: int | None = None
    host: ActionPaletteHost | None = None
    for _ in range(5):
        host = harness.open()
        win_id = int(host.winId())
        if first_win_id is None:
            first_win_id = win_id
        assert win_id == first_win_id
        exstyle = user32.GetWindowLongW(win_id, _GWL_EXSTYLE)
        assert exstyle & _WS_EX_APPWINDOW == 0
        assert exstyle & _WS_EX_TOOLWINDOW != 0
        harness.dismiss()
        assert _process_until(application, lambda h=host: not h.isVisible())
    assert host is not None
    assert harness.sink.host is host
    native_env["evidence"]["tool_taskbar"] = "PASS-no-appwindow"
    native_env["evidence"]["tool_handle_stable"] = "PASS-5-cycles"


# ---------------------------------------------------------------------------
# POPUP candidate
# ---------------------------------------------------------------------------


def _run_popup_scenario(
    native_env: dict[str, Any],
    harness: _PaletteHarness,
    driver: Callable[[ActionPaletteHost], None],
    *,
    watchdog_ms: int = 8000,
) -> None:
    application = native_env["application"]
    watchdog = QTimer()
    watchdog.setSingleShot(True)

    def force_close() -> None:
        host = harness.sink.host
        if host is not None:
            host.close()

    watchdog.timeout.connect(force_close)

    def run() -> None:
        host = harness.sink.host
        if host is not None:
            driver(host)
        else:
            watchdog.stop()

    QTimer.singleShot(0, run)
    watchdog.start(watchdog_ms)
    harness.open()  # blocks until the popup closes
    watchdog.stop()
    application.processEvents()


def test_popup_candidate_k_first_schwarz_click_is_swallowed(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    composition = native_env["composition"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    harness = native_env["make_harness"](ActionPaletteWindowStrategy.POPUP)
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)
    assert int(user32.WindowFromPoint(point)) == int(overlay.winId())

    measured: dict[str, Any] = {}

    def driver(host: ActionPaletteHost) -> None:
        assert _process_until(application, lambda: host.isVisible())
        _position_away(native_env, host, point)
        measured["palette_visible"] = bool(host.isVisible())
        measured["popup_active_window"] = bool(host.isActiveWindow())
        win_id = int(host.winId())
        exstyle = user32.GetWindowLongW(win_id, _GWL_EXSTYLE)
        measured["popup_exstyle_appwindow"] = bool(exstyle & _WS_EX_APPWINDOW)
        measured["popup_exstyle_toolwindow"] = bool(exstyle & _WS_EX_TOOLWINDOW)
        measured["window_under_schwarz"] = int(user32.WindowFromPoint(point))
        _click(user32, point)

    _run_popup_scenario(native_env, harness, driver)
    host = harness.sink.host
    assert host is not None
    auto_dismissed = _process_until(
        application, lambda: not host.isVisible(), timeout=2.0
    )
    measured["popup_auto_dismiss_after_click"] = auto_dismissed
    if host.isVisible():
        host.close()  # release the native popup grab
        application.processEvents()
    epoch = composition.track0.state.confirmed_epoch
    measured["epoch_after_first_click"] = (
        None if epoch is None else epoch.physical_name
    )
    measured["conversation_intents"] = len(harness.conversation_intents)
    native_env["evidence"]["popup_k_measured"] = measured
    # K contract: one physical Schwarz click must yield exactly one Interact.
    # A native popup grab consumes the first click, so the pet sees zero
    # Interact -> the POPUP candidate fails contract K.
    assert epoch is None or epoch.physical_name != "Interact"
    assert harness.conversation_intents == []
    assert harness.dispatcher.selection_calls == []


def test_popup_candidate_l_outside_click_auto_dismiss_zero_pass_through(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    composition = native_env["composition"]
    window = native_env["window"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    harness = native_env["make_harness"](ActionPaletteWindowStrategy.POPUP)
    _publish_initial_action(native_env, ProductionAction.SIT)
    before = composition.track0.state.confirmed_epoch
    screen = QApplication.primaryScreen()
    assert screen is not None
    anchor = ctypes.wintypes.POINT(
        screen.availableGeometry().center().x(),
        screen.availableGeometry().center().y(),
    )

    def driver(host: ActionPaletteHost) -> None:
        assert _process_until(application, lambda: host.isVisible())
        _position_away(native_env, host, anchor)
        excluded = (
            int(overlay.winId()),
            int(window.winId()),
            int(host.winId()),
        )
        outside = _outside_native_point(native_env, excluded)
        assert outside is not None
        _click(user32, outside)

    _run_popup_scenario(native_env, harness, driver)
    host = harness.sink.host
    assert host is not None
    auto_dismissed = _process_until(
        application, lambda: not host.isVisible(), timeout=2.0
    )
    if host.isVisible():
        host.close()  # release the native popup grab
        application.processEvents()
    after = composition.track0.state.confirmed_epoch
    assert (after is None) == (before is None)
    if after is not None and before is not None:
        assert after.generation == before.generation
        assert after.physical_name == before.physical_name
    assert harness.conversation_intents == []
    assert harness.dispatcher.selection_calls == []
    native_env["evidence"]["popup_l_measured"] = (
        "PASS-native-auto-dismiss"
        if auto_dismissed
        else "PASS-seam-close-zero-pass-through"
    )


def test_popup_candidate_focus_and_escape_routing(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    harness = native_env["make_harness"](ActionPaletteWindowStrategy.POPUP)
    measured: dict[str, Any] = {}

    def driver(host: ActionPaletteHost) -> None:
        application.processEvents()
        measured["popup_active_window"] = bool(host.isActiveWindow())
        measured["focus_in_host"] = bool(
            application.focusWidget() is not None
            and (
                application.focusWidget() is host
                or host.isAncestorOf(application.focusWidget())
            )
        )
        QTest.keyClick(host, Qt.Key.Key_Escape)

    _run_popup_scenario(native_env, harness, driver)
    host = harness.sink.host
    assert host is not None
    measured["popup_closed_after_escape"] = bool(not host.isVisible())
    measured["model_overlay_after_escape"] = (
        harness.coordinator.snapshot.foreground_overlay.value
    )
    native_env["evidence"]["popup_escape_measured"] = measured
    assert measured["focus_in_host"]
    assert not host.isVisible()
    assert harness.dispatcher.selection_calls == []
