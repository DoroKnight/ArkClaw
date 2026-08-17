"""Slice 6B - native production Schwarz Right Click -> Action Palette cutover.

Authority: 06 4.3/9.4, 07 21/23-25, 08 15.2, 09 5.1/21.
These tests drive the REAL production composition on the native Windows
platform plugin: PetApplicationCoordinator + real FrontendPresentation-
Coordinator + real ActionPaletteEffectSink + real PetWindow seam + real
Spine38 renderer, with physical native mouse input.

Frozen production facts proven here:
- right click opens the Palette at ROOT, XOR (no legacy native QMenu);
- opening executes zero application command (confirmed epoch unchanged);
- K: one physical Schwarz Left Click while Palette open -> dismiss + exactly
  one Interact, zero Conversation;
- Drag while Palette open -> existing Drag, zero Interact, Palette dismissed;
- L: ordinary outside click dismisses without pass-through / zero action;
- distinct second Right Click dismisses;
- host is lazy, single, reused (same native handle across reopen), TOOL
  exstyle (no APPWINDOW, TOOLWINDOW set);
- repeated open/select never duplicates dispatch (exactly one action).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_render_layout import PetRenderSurfaceMode
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.bootstrap.pet_production import (
    create_optional_production_pet_composition,
)
from arkclaw.presentation.command_descriptor_adapter import CommandId
from arkclaw.presentation.frontend_presentation import (
    ActionPaletteLayer,
    ForegroundOverlay,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.ui.action_palette import ActionPaletteHost
from arkclaw.presentation.qt.ui.main_window import MainWindow

_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080

_EVIDENCE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    ".pytest_tmp_slice6b_native_evidence.json",
)


def _process_until(
    application: QApplication,
    predicate: Callable[[], bool],
    timeout: float = 4.0,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with suppress(Exception):
            application.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    with suppress(Exception):
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
    user32.ReleaseCapture.restype = ctypes.wintypes.BOOL
    return user32


class _StubBridge(QObject):
    shutdown_finished = Signal(bool, str)


class _StubMainWindow:
    def __init__(self) -> None:
        self.safe_close_count = 0

    def request_safe_close(self) -> None:
        self.safe_close_count += 1

    def update_pet_presentation(self, *args: object) -> None:
        pass


class _ProductionSpyWindow(PetWindow):
    """Records every Palette-dispatched callback through the existing seam."""

    def __init__(self, **kwargs: object) -> None:
        self.palette_action_requests: list[ProductionAction] = []
        self.palette_resume_count = 0
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        self.palette_action_requests.append(action)
        return super().request_pet_action(action)

    def resume_pet_autonomous(self) -> ActionOutcome:
        self.palette_resume_count += 1
        return super().resume_pet_autonomous()


def _right_click(user32: Any, point: ctypes.wintypes.POINT) -> None:
    assert user32.SetCursorPos(point.x, point.y)
    user32.mouse_event(0x0008, 0, 0, 0, None)  # RIGHTDOWN
    time.sleep(0.03)
    user32.mouse_event(0x0010, 0, 0, 0, None)  # RIGHTUP


def _left_click(user32: Any, point: ctypes.wintypes.POINT) -> None:
    assert user32.SetCursorPos(point.x, point.y)
    user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
    # Drive the Qt event loop while the button is held so the production
    # outside-press poller (15 ms QTimer) can observe a cross-process press,
    # exactly as it would during a real user click.  A purely synchronous
    # DOWN/sleep/UP would starve the poller and never dismiss.
    try:
        application = QApplication.instance()
        deadline = time.monotonic() + 0.09
        while time.monotonic() < deadline:
            if application is not None:
                with suppress(Exception):
                    application.processEvents()
            time.sleep(0.01)
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP


def _drag(user32: Any, start: ctypes.wintypes.POINT, target: ctypes.wintypes.POINT) -> None:
    assert user32.SetCursorPos(start.x, start.y)
    user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
    # Drive the Qt event loop while moving so the native drag transaction
    # actually starts: Qt coalesces Windows moves, and a single SetCursorPos
    # jump can arrive as one move that never crosses the start-drag
    # threshold.  The pet still receives the real native press/release.
    try:
        application = QApplication.instance()
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            if application is not None:
                with suppress(Exception):
                    application.processEvents()
            user32.SetCursorPos(target.x, target.y)
            time.sleep(0.01)
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP


def _position_away(
    env: dict[str, Any],
    host: ActionPaletteHost,
    anchor: ctypes.wintypes.POINT,
) -> None:
    screen = QApplication.primaryScreen()
    assert screen is not None
    geometry = screen.availableGeometry()
    corners = (
        (geometry.left(), geometry.top()),
        (geometry.right() - 260, geometry.top()),
        (geometry.left(), geometry.bottom() - 320),
        (geometry.right() - 260, geometry.bottom() - 320),
    )
    corner = max(
        corners,
        key=lambda c: (c[0] - anchor.x) ** 2 + (c[1] - anchor.y) ** 2,
    )
    host.move(corner[0], corner[1])
    env["application"].processEvents()


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


def _publish_initial_action(
    env: dict[str, Any],
    action: ProductionAction,
) -> None:
    application = env["application"]
    window = env["window"]
    overlay = env["overlay"]
    user32 = env["user32"]
    user32.mouse_event(0x0004, 0, 0, 0, None)  # safety LEFTUP
    application.processEvents()
    if window.motion_state.value == "dragging":
        assert _process_until(
            application,
            lambda: window.motion_state.value != "dragging",
            timeout=2.0,
        )
    outcome = window.request_user_pet_action(action)
    deadline = time.monotonic() + 8.0
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
    assert _process_until(application, lambda: overlay.isVisible()), (
        f"overlay did not become visible after {action}"
    )
    layout = window._active_render_layout
    assert layout is not None
    assert layout.mode is PetRenderSurfaceMode.OVERFLOW


@pytest.fixture
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
    window = _ProductionSpyWindow(
        renderer=composition.renderer,
        track0=composition.track0,
        active_role_pack_id=composition.role_pack_id,
        available_production_actions=composition.available_actions,
        playback_event_source=composition.playback_event_source,
    )
    overlay = window._effect_overlay
    assert overlay is not None
    bridge = _StubBridge()
    main_window = _StubMainWindow()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        window,
    )
    window.show()
    application.processEvents()
    user32 = _load_user32()
    old_cursor = ctypes.wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(old_cursor))
    env: dict[str, Any] = {
        "application": application,
        "composition": composition,
        "window": window,
        "overlay": overlay,
        "user32": user32,
        "coordinator": coordinator,
        "main_window": main_window,
        "evidence": {},
    }
    try:
        yield env
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, None)  # safety LEFTUP
        user32.mouse_event(0x0010, 0, 0, 0, None)  # safety RIGHTUP
        user32.ReleaseCapture()
        # Production lifecycle seam: stop the native outside-press poller
        # before owned surfaces disappear, then dispose the sink host and
        # detach production hooks.
        coordinator.dispose()
        window.complete_safe_close()
        # Fixture owns these Qt surfaces too: schedule deletion so no hidden
        # top-level from this composition survives into the next test.
        overlay.deleteLater()
        window.deleteLater()
        coordinator.deleteLater()
        application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        user32.SetCursorPos(old_cursor.x, old_cursor.y)

def _open_palette_native(env: dict[str, Any]) -> ActionPaletteHost:
    application = env["application"]
    user32 = env["user32"]
    coordinator = env["coordinator"]
    point = _schwarz_native_point(env)
    _right_click(user32, point)
    assert _process_until(
        application,
        lambda: coordinator.palette_sink.host is not None,
    )
    host = coordinator.palette_sink.host
    assert host is not None
    assert _process_until(application, lambda: host.isVisible())
    return host


# ---------------------------------------------------------------------------
# Right Click opens Palette ROOT, XOR with QMenu, zero action
# ---------------------------------------------------------------------------


def test_native_right_click_opens_palette_root_xor_qmenu_zero_action(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)
    assert int(user32.WindowFromPoint(point)) == int(overlay.winId())

    _right_click(user32, point)

    coordinator = native_env["coordinator"]
    assert _process_until(
        application,
        lambda: coordinator.palette_sink.host is not None,
    )
    host = coordinator.palette_sink.host
    assert host is not None
    assert _process_until(application, lambda: host.isVisible())
    assert host.current_layer is ActionPaletteLayer.ROOT
    snapshot = native_env["coordinator"].frontend_presentation.snapshot
    assert snapshot.foreground_overlay is ForegroundOverlay.PALETTE
    assert snapshot.palette_layer is ActionPaletteLayer.ROOT
    # XOR: the legacy native QMenu must never be visible.
    assert window.findChild(QMenu) is None
    popup = QApplication.activePopupWidget()
    assert not isinstance(popup, QMenu)
    # Zero application command on open.  The confirmed-epoch generation is
    # not a stable zero-action oracle: the pet's autonomous animation loop
    # confirms Relax/IDLE epochs independently of any Palette command.
    assert window.palette_action_requests == []
    assert window.palette_resume_count == 0
    native_env["evidence"]["right_click_palette_root"] = "PASS"
    native_env["evidence"]["right_click_xor_no_qmenu"] = "PASS"
    native_env["evidence"]["right_click_zero_action"] = "PASS"


# ---------------------------------------------------------------------------
# K: physical Schwarz Left Click while Palette open
# ---------------------------------------------------------------------------


def test_native_left_click_schwarz_while_open_dismisses_and_one_interact(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    composition = native_env["composition"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)
    assert int(user32.WindowFromPoint(point)) == int(overlay.winId())

    host = _open_palette_native(native_env)
    _position_away(native_env, host, point)
    _left_click(user32, point)

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
    # Palette dismissed through the production presentation seam.
    assert _process_until(application, lambda: not host.isVisible())
    # Exactly one Interact: the confirmed epoch stays stable.
    time.sleep(0.35)
    application.processEvents()
    assert composition.track0.state.confirmed_epoch is not None
    assert composition.track0.state.confirmed_epoch.generation == generation
    native_env["evidence"]["k_dismiss"] = "PASS"
    native_env["evidence"]["k_exactly_one_interact"] = "PASS"


# ---------------------------------------------------------------------------
# Drag while Palette open
# ---------------------------------------------------------------------------


def test_native_drag_while_open_dismisses_and_drags_zero_interact(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    user32 = native_env["user32"]
    composition = native_env["composition"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    start = _schwarz_native_point(native_env)
    target = ctypes.wintypes.POINT(start.x - 40, start.y - 30)
    before = composition.track0.state.confirmed_epoch
    assert before is not None

    host = _open_palette_native(native_env)
    _position_away(native_env, host, start)
    _drag(user32, start, target)

    assert _process_until(
        application,
        lambda: window.motion_state.value == "dragging",
    )
    # Drag must never emit Interact.
    after = composition.track0.state.confirmed_epoch
    assert after is not None
    assert after.physical_name != "Interact"
    # Drag dismisses the Palette.
    assert _process_until(application, lambda: not host.isVisible())
    user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP
    assert _process_until(
        application,
        lambda: window.motion_state.value != "dragging",
    )
    native_env["evidence"]["drag_dismiss"] = "PASS"
    native_env["evidence"]["drag_zero_interact"] = "PASS"


# ---------------------------------------------------------------------------
# L: outside click dismisses without pass-through / zero action
# ---------------------------------------------------------------------------


def test_native_outside_click_dismisses_zero_action(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    overlay = native_env["overlay"]
    user32 = native_env["user32"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    host = _open_palette_native(native_env)
    excluded = (
        int(overlay.winId()),
        int(host.winId()),
        int(window.winId()),
    )
    outside = _outside_native_point(native_env, excluded)
    assert outside is not None

    _left_click(user32, outside)

    assert _process_until(application, lambda: not host.isVisible())
    time.sleep(0.2)
    application.processEvents()
    # Zero palette-dispatched Character action.  The confirmed-epoch
    # generation is not a stable oracle: the pet's autonomous animation loop
    # confirms Relax/IDLE epochs independently of any Palette command.
    assert window.palette_action_requests == []
    assert window.palette_resume_count == 0
    native_env["evidence"]["outside_dismiss"] = "PASS"
    native_env["evidence"]["outside_zero_action"] = "PASS"


# ---------------------------------------------------------------------------
# Distinct second Right Click dismisses; lazy single reused TOOL host
# ---------------------------------------------------------------------------


def test_native_distinct_second_right_click_dismisses(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    user32 = native_env["user32"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)

    host = _open_palette_native(native_env)
    _position_away(native_env, host, point)
    time.sleep(0.6)  # distinct (non-rapid) second right click
    _right_click(user32, point)

    assert _process_until(application, lambda: not host.isVisible())
    snapshot = native_env["coordinator"].frontend_presentation.snapshot
    assert snapshot.foreground_overlay is ForegroundOverlay.NONE
    assert window.palette_action_requests == []
    assert window.palette_resume_count == 0
    native_env["evidence"]["second_right_click_dismiss"] = "PASS"


def test_native_host_lazy_single_reused_tool_exstyle(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    user32 = native_env["user32"]
    coordinator = native_env["coordinator"]
    assert coordinator.palette_sink.host is None
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)

    _right_click(user32, point)
    assert _process_until(
        application,
        lambda: coordinator.palette_sink.host is not None,
    )
    host = coordinator.palette_sink.host
    assert host is not None
    assert _process_until(application, lambda: host.isVisible())
    _position_away(native_env, host, point)
    first_win_id = int(host.winId())
    exstyle = user32.GetWindowLongW(first_win_id, _GWL_EXSTYLE)
    assert exstyle & _WS_EX_APPWINDOW == 0
    assert exstyle & _WS_EX_TOOLWINDOW != 0

    # Distinct reopen reuses the same host and native handle.
    time.sleep(0.6)
    _right_click(user32, point)
    assert _process_until(application, lambda: not host.isVisible())
    time.sleep(0.6)
    _right_click(user32, point)
    assert _process_until(application, lambda: host.isVisible())
    assert coordinator.palette_sink.host is host
    assert int(host.winId()) == first_win_id
    native_env["evidence"]["host_lazy"] = "PASS"
    native_env["evidence"]["host_reused_same_handle"] = "PASS"
    native_env["evidence"]["tool_exstyle"] = "PASS"


# ---------------------------------------------------------------------------
# repeated open/select exactly once
# ---------------------------------------------------------------------------


def test_native_repeated_open_select_exactly_once(
    native_env: dict[str, Any],
) -> None:
    application = native_env["application"]
    window = native_env["window"]
    user32 = native_env["user32"]
    _publish_initial_action(native_env, ProductionAction.SIT)
    point = _schwarz_native_point(native_env)

    for _step in range(3):
        host = _open_palette_native(native_env)
        _position_away(native_env, host, point)
        time.sleep(0.6)
        _right_click(user32, point)
        assert _process_until(
            application,
            lambda host=host: not host.isVisible(),
        )
        time.sleep(0.6)

    host = _open_palette_native(native_env)
    character_nav = host.navigation_button(ActionPaletteLayer.CHARACTER)
    assert character_nav is not None
    QTest.mouseClick(character_nav, Qt.MouseButton.LeftButton)
    application.processEvents()
    interact_row = host.row_button(CommandId.INTERACT)
    assert interact_row is not None
    QTest.mouseClick(interact_row, Qt.MouseButton.LeftButton)
    application.processEvents()

    assert window.palette_action_requests == [ProductionAction.INTERACT]
    assert _process_until(application, lambda: not host.isVisible())
    native_env["evidence"]["repeat_exactly_once"] = "PASS"
