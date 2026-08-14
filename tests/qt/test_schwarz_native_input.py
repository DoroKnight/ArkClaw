"""Real Windows input routing for Schwarz overflow animations."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.bootstrap.pet_production import (
    create_optional_production_pet_composition,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow


def _process_until(application: QApplication, predicate: object) -> bool:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.005)
    application.processEvents()
    return bool(predicate())  # type: ignore[operator]


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows input")
@pytest.mark.parametrize(
    "initial_action",
    [ProductionAction.SIT, ProductionAction.SPECIAL],
)
def test_native_click_on_schwarz_overflow_body_immediately_enters_interact(
    initial_action: ProductionAction,
) -> None:
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
    user32.SendMessageW.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.wintypes.LPARAM
    old_cursor = ctypes.wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(old_cursor))
    try:
        window.show()
        assert (
            window.request_user_pet_action(initial_action)
            is ActionOutcome.ACCEPTED
        )
        window.physics_timer.timeout.emit()
        application.processEvents()
        overlay.repaint()
        application.processEvents()
        layout = window._active_render_layout
        assert layout is not None
        assert overlay.isVisible()
        body_center = QPoint(
            round(layout.body_window_offset.x) + window.width() // 2,
            round(layout.body_window_offset.y) + window.height() // 2,
        )
        native_rect = ctypes.wintypes.RECT()
        assert user32.GetWindowRect(int(overlay.winId()), ctypes.byref(native_rect))
        native_width = native_rect.right - native_rect.left
        native_height = native_rect.bottom - native_rect.top
        native_point = ctypes.wintypes.POINT(
            native_rect.left
            + round(body_center.x() * native_width / overlay.width()),
            native_rect.top
            + round(body_center.y() * native_height / overlay.height()),
        )
        assert user32.SetCursorPos(native_point.x, native_point.y)
        application.processEvents()
        packed = ((native_point.y & 0xFFFF) << 16) | (native_point.x & 0xFFFF)
        assert user32.SendMessageW(
            int(overlay.winId()),
            0x0084,  # WM_NCHITTEST
            0,
            packed,
        ) == 1  # HTCLIENT
        routed_handle = int(
            user32.WindowFromPoint(native_point)
        )
        assert routed_handle == int(overlay.winId())

        user32.mouse_event(0x0008, 0, 0, 0, None)  # RIGHTDOWN
        user32.mouse_event(0x0010, 0, 0, 0, None)  # RIGHTUP
        assert _process_until(
            application,
            lambda: (
                (menu := window.findChild(QMenu)) is not None
                and menu.isVisible()
            ),
        )
        menu = window.findChild(QMenu)
        assert menu is not None
        menu.close()
        application.processEvents()

        user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP
        assert _process_until(
            application,
            lambda: (
                composition.track0.state.confirmed_epoch is not None
                and composition.track0.state.confirmed_epoch.physical_name
                == "Interact"
            ),
        )

        assert (
            window.request_user_pet_action(initial_action)
            is ActionOutcome.ACCEPTED
        )
        window.physics_timer.timeout.emit()
        application.processEvents()
        layout = window._active_render_layout
        assert layout is not None
        body_center = QPoint(
            round(layout.body_window_offset.x) + window.width() // 2,
            round(layout.body_window_offset.y) + window.height() // 2,
        )
        native_rect = ctypes.wintypes.RECT()
        assert user32.GetWindowRect(int(overlay.winId()), ctypes.byref(native_rect))
        native_point = ctypes.wintypes.POINT(
            native_rect.left
            + round(body_center.x() * (native_rect.right - native_rect.left) / overlay.width()),
            native_rect.top
            + round(body_center.y() * (native_rect.bottom - native_rect.top) / overlay.height()),
        )
        assert user32.SetCursorPos(native_point.x, native_point.y)
        application.processEvents()
        drag_target = ctypes.wintypes.POINT(
            native_point.x - 40,
            native_point.y - 30,
        )
        user32.mouse_event(0x0002, 0, 0, 0, None)  # LEFTDOWN
        assert user32.SetCursorPos(drag_target.x, drag_target.y)
        assert _process_until(
            application,
            lambda: window.motion_state.value == "dragging",
        )
        assert composition.track0.state.confirmed_epoch is not None
        assert composition.track0.state.confirmed_epoch.physical_name == "Relax"
        user32.mouse_event(0x0004, 0, 0, 0, None)  # LEFTUP
        assert _process_until(
            application,
            lambda: window.motion_state.value != "dragging",
        )
    finally:
        user32.SetCursorPos(old_cursor.x, old_cursor.y)
        window.complete_safe_close()
        application.processEvents()
