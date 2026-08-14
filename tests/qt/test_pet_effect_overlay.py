"""Qt contracts for the selectively input-proxying Special surface."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QImage,
    QMouseEvent,
    QPainter,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from arkclaw.application.pet_geometry import Point, Rect, Size
from arkclaw.application.pet_render_layout import (
    PetRenderLayout,
    PetRenderLayoutQuality,
    PetRenderSurfaceMode,
)
from arkclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererAnimationCapability,
    placeholder_animation_capability,
)
from arkclaw.application.pet_state import PetFacing
from arkclaw.presentation.qt.pet_effect_overlay import PetEffectOverlayWindow
from arkclaw.presentation.qt.pet_window import PetWindow


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


class _SurfaceRenderer:
    def __init__(self) -> None:
        self.render_count = 0
        self.render_generation = 1
        self.device_pixel_ratio = 1.0
        self.image = QImage(376, 268, QImage.Format.Format_RGBA8888)
        self.image.fill(0)

    def render_surface(self, painter: QPainter) -> QImage:
        self.render_count += 1
        painter.drawImage(QRectF(0.0, 0.0, 376.0, 268.0), self.image)
        return self.image


class _FailingSurfaceRenderer(_SurfaceRenderer):
    def render_surface(self, painter: QPainter) -> QImage:
        del painter
        raise RuntimeError("injected render failure")


class _InputTarget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.left_press_count = 0
        self.left_move_count = 0
        self.left_release_count = 0
        self.context_menu_count = 0
        self.last_context_global = QPoint()

    def mousePressEvent(self, event: object) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.left_press_count += 1
            event.accept()

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.left_release_count += 1
            event.accept()

    def mouseMoveEvent(self, event: object) -> None:
        if bool(event.buttons() & Qt.MouseButton.LeftButton):
            self.left_move_count += 1
            event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.context_menu_count += 1
        self.last_context_global = event.globalPos()
        event.accept()


class _ObservedOverlay(PetEffectOverlayWindow):
    def __init__(self, renderer: object, *, input_target: QWidget) -> None:
        self.raise_count = 0
        self.flag_apply_count = 0
        super().__init__(renderer, input_target=input_target)  # type: ignore[arg-type]

    def raise_(self) -> None:
        self.raise_count += 1
        super().raise_()

    def _apply_flags(self, *, always_on_top: bool) -> None:
        self.flag_apply_count += 1
        super()._apply_flags(always_on_top=always_on_top)


def _native_hit_test(overlay: QWidget, local: QPoint) -> int:
    user32 = ctypes.windll.user32
    user32.GetClientRect.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.POINTER(ctypes.wintypes.RECT),
    ]
    user32.GetClientRect.restype = ctypes.wintypes.BOOL
    user32.ClientToScreen.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.POINTER(ctypes.wintypes.POINT),
    ]
    user32.ClientToScreen.restype = ctypes.wintypes.BOOL
    handle = int(overlay.winId())
    client_rect = ctypes.wintypes.RECT()
    assert user32.GetClientRect(handle, ctypes.byref(client_rect))
    point = ctypes.wintypes.POINT(
        round(local.x() * client_rect.right / overlay.width()),
        round(local.y() * client_rect.bottom / overlay.height()),
    )
    assert user32.ClientToScreen(handle, ctypes.byref(point))
    packed = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
    return int(user32.SendMessageW(handle, 0x0084, 0, packed))


def test_overlay_uses_body_hit_proxy_without_taking_focus(
    qt_application: QApplication,
) -> None:
    renderer = _SurfaceRenderer()
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = _ObservedOverlay(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )

    overlay.show_layout(layout, always_on_top=True)
    qt_application.processEvents()

    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not overlay.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    assert not overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert overlay.geometry().getRect() == (100, 120, 376, 268)
    assert overlay.isVisible()
    if QApplication.platformName() == "windows":
        inside_hit_test = _native_hit_test(overlay, QPoint(50, 90))
        outside_hit_test = _native_hit_test(overlay, QPoint(10, 10))
        assert inside_hit_test == 1
        assert outside_hit_test == -1
    overlay.close()
    input_target.close()


def test_overlay_forwards_body_click_to_input_owner(
    qt_application: QApplication,
) -> None:
    renderer = _SurfaceRenderer()
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = _ObservedOverlay(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    qt_application.processEvents()

    QTest.mouseClick(
        overlay,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(80, 100),
    )

    assert input_target.left_press_count == 1
    assert input_target.left_release_count == 1
    overlay.close()
    input_target.close()


def test_overlay_forwards_visible_pixels_outside_body_but_not_transparent_padding(
    qt_application: QApplication,
) -> None:
    renderer = _SurfaceRenderer()
    renderer.image.setPixelColor(10, 10, QColor(255, 255, 255, 255))
    renderer.image.setPixelColor(80, 265, QColor(255, 255, 255, 255))
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = _ObservedOverlay(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    paint_target = QImage(376, 268, QImage.Format.Format_RGBA8888)
    paint_target.fill(0)
    painter = QPainter(paint_target)
    overlay.render(painter, QPoint())
    painter.end()

    for local_point in (QPoint(10, 10), QPoint(80, 265), QPoint(10, 30)):
        global_point = overlay.mapToGlobal(local_point)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(local_point),
            QPointF(global_point),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(local_point),
            QPointF(global_point),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(overlay, press)
        QApplication.sendEvent(overlay, release)

    assert input_target.left_press_count == 2
    assert input_target.left_release_count == 2
    if QApplication.platformName() == "windows":
        for local, expected in (
            (QPoint(10, 10), 1),
            (QPoint(80, 265), 1),
            (QPoint(10, 30), -1),
        ):
            assert _native_hit_test(overlay, local) == expected
    overlay.close()
    input_target.close()


def test_overlay_forwards_context_menu_once_from_visible_pixel_outside_body(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _SurfaceRenderer()
    renderer.image.setPixelColor(10, 10, QColor(255, 255, 255, 255))
    input_target = _InputTarget()
    input_target.setGeometry(-160, -100, 160, 180)
    input_target.show()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(-200.0, -180.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(-160.0, -100.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    paint_target = QImage(376, 268, QImage.Format.Format_RGBA8888)
    painter = QPainter(paint_target)
    overlay.render(painter, QPoint())
    painter.end()
    local_point = QPoint(10, 10)
    global_point = overlay.mapToGlobal(local_point)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        local_point,
        global_point,
        Qt.KeyboardModifier.NoModifier,
    )

    QApplication.sendEvent(overlay, event)

    assert event.isAccepted()
    assert input_target.context_menu_count == 1
    assert input_target.last_context_global == global_point
    overlay.close()
    input_target.close()


def test_overlay_invalidates_old_alpha_until_new_generation_is_painted(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _SurfaceRenderer()
    renderer.image.setPixelColor(10, 10, QColor(255, 255, 255, 255))
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    paint_target = QImage(376, 268, QImage.Format.Format_RGBA8888)
    painter = QPainter(paint_target)
    overlay.render(painter, QPoint())
    painter.end()
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert input_target.left_press_count == 1

    renderer.render_generation += 1
    renderer.image.fill(0)

    # A semantic action replacement advances the renderer generation before
    # Qt necessarily schedules the next paint.  The old alpha snapshot must
    # stop participating in hit testing during that interval.
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert input_target.left_press_count == 1
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 100))
    assert input_target.left_press_count == 2

    overlay.show_layout(layout, always_on_top=True)
    overlay.close()
    input_target.close()


def test_overlay_render_failure_publishes_no_hit_snapshot(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _FailingSurfaceRenderer()
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    target = QImage(376, 268, QImage.Format.Format_RGBA8888)
    painter = QPainter(target)

    with pytest.raises(RuntimeError, match="injected render failure"):
        overlay.render(painter, QPoint())
    painter.end()

    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert input_target.left_press_count == 0
    overlay.close()
    input_target.close()


def test_republishing_identical_layout_keeps_the_same_native_window(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _SurfaceRenderer()
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = _ObservedOverlay(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    native_id = int(overlay.winId())
    initial_raise_count = overlay.raise_count
    initial_flag_apply_count = overlay.flag_apply_count

    for _ in range(120):
        overlay.show_layout(layout, always_on_top=True)

    assert int(overlay.winId()) == native_id
    assert overlay.geometry().getRect() == (100, 120, 376, 268)
    assert overlay.isVisible()
    assert overlay.raise_count == initial_raise_count
    assert overlay.flag_apply_count == initial_flag_apply_count
    overlay.close()
    input_target.close()


@pytest.mark.skipif(os.name != "nt", reason="requires the Windows taskbar")
def test_republishing_sit_layout_restores_overlay_above_activated_taskbar(
    qt_application: QApplication,
) -> None:
    if QApplication.platformName() != "windows":
        pytest.skip("requires the Qt windows platform plugin")

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.LPCWSTR,
    ]
    user32.FindWindowW.restype = ctypes.wintypes.HWND
    user32.GetWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT]
    user32.GetWindow.restype = ctypes.wintypes.HWND
    user32.GetWindowRect.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.POINTER(ctypes.wintypes.RECT),
    ]
    user32.GetWindowRect.restype = ctypes.wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.wintypes.UINT,
    ]
    user32.SetWindowPos.restype = ctypes.wintypes.BOOL

    taskbar = user32.FindWindowW("Shell_TrayWnd", None)
    if not taskbar:
        pytest.skip("primary Windows taskbar was not found")
    taskbar_rect = ctypes.wintypes.RECT()
    assert user32.GetWindowRect(taskbar, ctypes.byref(taskbar_rect))

    def is_above(candidate: int, reference: int) -> bool:
        current = user32.GetWindow(reference, 3)  # GW_HWNDPREV
        while current:
            if int(current) == candidate:
                return True
            current = user32.GetWindow(current, 3)
        return False

    renderer = _SurfaceRenderer()
    input_target = _InputTarget()
    input_target.setGeometry(
        taskbar_rect.left + 40,
        taskbar_rect.top - 100,
        160,
        180,
    )
    input_target.show()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(
            float(taskbar_rect.left + 20),
            float(taskbar_rect.top - 120),
            376.0,
            268.0,
        ),
        Point(20.0, 20.0),
        Point(float(taskbar_rect.left + 40), float(taskbar_rect.top - 100)),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    qt_application.processEvents()
    overlay_handle = int(overlay.winId())

    # Win32 taskbar rectangles use physical desktop coordinates while Qt
    # widget geometry is logical under fractional DPI.  Position the native
    # test HWND directly so the prerequisite overlap is unambiguous.
    assert user32.SetWindowPos(
        overlay_handle,
        None,
        taskbar_rect.left + 20,
        taskbar_rect.top - 120,
        376,
        268,
        0x0010,  # SWP_NOACTIVATE
    )

    # Simulate the ordering effect of clicking the taskbar: Explorer moves its
    # topmost taskbar ahead of the already-visible Sit overflow window.
    no_move_or_activate = 0x0001 | 0x0002 | 0x0010
    assert user32.SetWindowPos(
        taskbar,
        ctypes.wintypes.HWND(-1),  # HWND_TOPMOST
        0,
        0,
        0,
        0,
        no_move_or_activate,
    )
    assert is_above(int(taskbar), overlay_handle)

    # The next existing display publication must repair only native Z-order;
    # it must not rebuild the overlay or alter the Sit layout.
    overlay.show_layout(layout, always_on_top=True)
    qt_application.processEvents()

    assert int(overlay.winId()) == overlay_handle
    assert is_above(overlay_handle, int(taskbar))

    popup = QWidget()
    popup.setWindowFlags(
        Qt.WindowType.Tool
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
    )
    popup.setGeometry(50, 50, 100, 60)
    popup.show()
    popup.raise_()
    qt_application.processEvents()
    popup_handle = int(popup.winId())
    assert user32.SetWindowPos(
        taskbar,
        popup_handle,
        0,
        0,
        0,
        0,
        no_move_or_activate,
    )
    assert is_above(popup_handle, int(taskbar))
    assert is_above(int(taskbar), overlay_handle)

    overlay.show_layout(layout, always_on_top=True)
    qt_application.processEvents()

    assert is_above(popup_handle, overlay_handle)
    assert is_above(overlay_handle, int(taskbar))
    popup.close()
    overlay.close()
    input_target.close()


def test_overlay_keeps_forwarding_an_active_drag_outside_body_hit_area(
    qt_application: QApplication,
) -> None:
    renderer = _SurfaceRenderer()
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    qt_application.processEvents()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 100))
    overlay.retire_surface()
    assert overlay.isVisible()
    outside_local = QPointF(320.0, 220.0)
    outside_global = QPointF(
        overlay.x() + outside_local.x(),
        overlay.y() + outside_local.y(),
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        outside_local,
        outside_global,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(overlay, move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        outside_local,
        outside_global,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(overlay, release)

    assert input_target.left_move_count == 1
    assert input_target.left_release_count == 1
    assert not overlay.isVisible()
    overlay.close()
    input_target.close()


def test_overlay_keeps_active_gesture_across_render_generation_change(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _SurfaceRenderer()
    renderer.image.setPixelColor(10, 10, QColor(255, 255, 255, 255))
    input_target = _InputTarget()
    input_target.setGeometry(140, 200, 160, 180)
    input_target.show()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)
    layout = PetRenderLayout(
        PetRenderSurfaceMode.OVERFLOW,
        Rect(100.0, 120.0, 376.0, 268.0),
        Point(40.0, 80.0),
        Point(140.0, 200.0),
        0.7,
        PetFacing.RIGHT,
        1.0,
        PetRenderLayoutQuality.FULL_SCALE,
    )
    overlay.show_layout(layout, always_on_top=True)
    target = QImage(376, 268, QImage.Format.Format_RGBA8888)
    painter = QPainter(target)
    overlay.render(painter, QPoint())
    painter.end()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))

    renderer.render_generation += 1
    renderer.image.fill(0)
    overlay.show_layout(layout, always_on_top=True)
    outside = QPointF(320.0, 220.0)
    outside_global = QPointF(overlay.x() + 320.0, overlay.y() + 220.0)
    QApplication.sendEvent(
        overlay,
        QMouseEvent(
            QEvent.Type.MouseMove,
            outside,
            outside_global,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    QApplication.sendEvent(
        overlay,
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            outside,
            outside_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    assert input_target.left_press_count == 1
    assert input_target.left_move_count == 1
    assert input_target.left_release_count == 1
    overlay.close()
    input_target.close()


class _Clock:
    value = 1.0

    def now(self) -> float:
        return self.value


class _OverflowRenderer(_SurfaceRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.body_render_count = 0
        self.body_render_positions: list[tuple[int, int]] = []
        self.surface_mode = PetRenderSurfaceMode.OVERFLOW
        self.window: QWidget | None = None

    def initialize(self, viewport: Size) -> None:
        del viewport

    def set_viewport(self, viewport: Size) -> None:
        del viewport

    def set_state(self, request: object) -> None:
        del request

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def render(self, painter: object, frame: object) -> None:
        del painter, frame
        self.body_render_count += 1
        if self.window is not None:
            self.body_render_positions.append(
                (self.window.x(), self.window.y())
            )

    def animation_capability(
        self, action: PetRendererAction
    ) -> PetRendererAnimationCapability:
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        return

    def resume(self) -> None:
        return

    def close(self) -> None:
        return

    def plan_layout(
        self, body_rect: Rect, workspace: Rect, device_pixel_ratio: float
    ) -> PetRenderLayout:
        del workspace, device_pixel_ratio
        surface_rect = body_rect
        body_window_offset = Point(0.0, 0.0)
        if self.surface_mode is PetRenderSurfaceMode.OVERFLOW:
            surface_rect = Rect(
                body_rect.x - 20.0,
                body_rect.y - 30.0,
                200.0,
                220.0,
            )
            body_window_offset = Point(20.0, 30.0)
        return PetRenderLayout(
            self.surface_mode,
            surface_rect,
            body_window_offset,
            Point(body_rect.x, body_rect.y),
            0.0,
            PetFacing.RIGHT,
            1.0,
            PetRenderLayoutQuality.FULL_SCALE,
        )

    def set_render_layout(self, layout: PetRenderLayout) -> None:
        del layout


def test_pet_window_publishes_overflow_owner_after_renderer_update(
    qt_application: QApplication,
) -> None:
    renderer = _OverflowRenderer()
    window = PetWindow(renderer=renderer, clock=_Clock())
    window.show()

    window.physics_timer.timeout.emit()
    qt_application.processEvents()
    overlays = [
        widget
        for widget in QApplication.topLevelWidgets()
        if widget.objectName() == "petEffectOverlayWindow"
    ]

    assert len(overlays) == 1
    assert overlays[0].isVisible()
    assert renderer.render_count >= 1
    window.complete_safe_close()
    qt_application.processEvents()


def test_body_is_painted_before_old_overflow_owner_is_hidden(
    qt_application: QApplication,
) -> None:
    renderer = _OverflowRenderer()
    window = PetWindow(renderer=renderer, clock=_Clock())
    renderer.window = window
    window.show()
    window.physics_timer.timeout.emit()
    qt_application.processEvents()
    overlay = next(
        widget
        for widget in QApplication.topLevelWidgets()
        if widget.objectName() == "petEffectOverlayWindow"
    )
    assert overlay.isVisible()

    renderer.surface_mode = PetRenderSurfaceMode.BODY
    window.move(0, 0)
    body_frames_before_publish = renderer.body_render_count
    window.physics_timer.timeout.emit()

    assert renderer.body_render_count > body_frames_before_publish
    assert renderer.body_render_positions[-1] == (window.x(), window.y())
    assert not overlay.isVisible()
    window.complete_safe_close()
    qt_application.processEvents()
