"""Top-level overflow surface with selective body-input proxying."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from typing import Protocol

from PySide6.QtCore import QByteArray, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QContextMenuEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from arkclaw.application.pet_render_layout import (
    PetRenderLayout,
    PetRenderSurfaceMode,
)
from arkclaw.presentation.qt.pet_surface_hit_frame import PetSurfaceHitFrame


class _WindowsTaskbarZOrder:
    """Keep an overlapping effect surface directly above Windows taskbars."""

    _GW_HWNDPREV = 3
    _HWND_TOPMOST = -1
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOACTIVATE = 0x0010

    def __init__(self) -> None:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
        ]
        user32.FindWindowW.restype = ctypes.wintypes.HWND
        user32.FindWindowExW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
        ]
        user32.FindWindowExW.restype = ctypes.wintypes.HWND
        user32.GetWindow.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
        ]
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
        self._user32 = user32

    def restore_if_taskbar_is_above(self, overlay_handle: int) -> None:
        overlay_rect = self._window_rect(overlay_handle)
        if overlay_rect is None:
            return
        for taskbar_handle in self._taskbar_handles():
            taskbar_rect = self._window_rect(taskbar_handle)
            if (
                taskbar_rect is None
                or not self._rects_intersect(overlay_rect, taskbar_rect)
                or self._is_above(overlay_handle, taskbar_handle)
            ):
                continue
            predecessor = self._user32.GetWindow(
                taskbar_handle,
                self._GW_HWNDPREV,
            )
            insert_after = (
                predecessor
                if predecessor
                else ctypes.wintypes.HWND(self._HWND_TOPMOST)
            )
            self._user32.SetWindowPos(
                overlay_handle,
                insert_after,
                0,
                0,
                0,
                0,
                self._SWP_NOSIZE | self._SWP_NOMOVE | self._SWP_NOACTIVATE,
            )
            return

    def _taskbar_handles(self) -> tuple[int, ...]:
        handles: list[int] = []
        primary = self._user32.FindWindowW("Shell_TrayWnd", None)
        if primary:
            handles.append(int(primary))
        previous = ctypes.wintypes.HWND()
        while True:
            secondary = self._user32.FindWindowExW(
                None,
                previous,
                "Shell_SecondaryTrayWnd",
                None,
            )
            if not secondary:
                break
            handles.append(int(secondary))
            previous = secondary
        return tuple(handles)

    def _window_rect(self, handle: int) -> ctypes.wintypes.RECT | None:
        rect = ctypes.wintypes.RECT()
        if not self._user32.GetWindowRect(handle, ctypes.byref(rect)):
            return None
        return rect

    def _is_above(self, candidate: int, reference: int) -> bool:
        current = self._user32.GetWindow(reference, self._GW_HWNDPREV)
        for _ in range(4096):
            if not current:
                return False
            if int(current) == candidate:
                return True
            current = self._user32.GetWindow(current, self._GW_HWNDPREV)
        return False

    @staticmethod
    def _rects_intersect(
        first: ctypes.wintypes.RECT,
        second: ctypes.wintypes.RECT,
    ) -> bool:
        return (
            first.left < second.right
            and first.right > second.left
            and first.top < second.bottom
            and first.bottom > second.top
        )


class _WindowsHitTestCoordinates:
    """Map native screen pixels onto one Qt logical client surface."""

    def __init__(self) -> None:
        user32 = ctypes.windll.user32
        user32.ScreenToClient.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.POINTER(ctypes.wintypes.POINT),
        ]
        user32.ScreenToClient.restype = ctypes.wintypes.BOOL
        user32.GetClientRect.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.POINTER(ctypes.wintypes.RECT),
        ]
        user32.GetClientRect.restype = ctypes.wintypes.BOOL
        self._user32 = user32

    def to_logical(
        self,
        window_handle: int,
        screen_x: int,
        screen_y: int,
        *,
        logical_width: int,
        logical_height: int,
    ) -> QPointF | None:
        point = ctypes.wintypes.POINT(screen_x, screen_y)
        client_rect = ctypes.wintypes.RECT()
        if (
            logical_width <= 0
            or logical_height <= 0
            or not self._user32.ScreenToClient(window_handle, ctypes.byref(point))
            or not self._user32.GetClientRect(
                window_handle,
                ctypes.byref(client_rect),
            )
        ):
            return None
        native_width = client_rect.right - client_rect.left
        native_height = client_rect.bottom - client_rect.top
        if native_width <= 0 or native_height <= 0:
            return None
        return QPointF(
            point.x * logical_width / native_width,
            point.y * logical_height / native_height,
        )


class _EffectSurfaceRenderer(Protocol):
    def render_surface(self, painter: QPainter) -> QImage | None: ...


class PetEffectOverlayWindow(QWidget):
    """Overflow surface that proxies body input to the authoritative window."""

    def __init__(
        self,
        renderer: _EffectSurfaceRenderer,
        *,
        input_target: QWidget,
    ) -> None:
        super().__init__(None)
        self._renderer = renderer
        self._input_target = input_target
        self._body_input_rect = QRectF()
        self._published_hit_frame: PetSurfaceHitFrame | None = None
        self._expected_render_generation: int | None = None
        self._proxy_pointer_active = False
        self._surface_retired = False
        self._applied_always_on_top: bool | None = None
        self._applied_geometry: QRect | None = None
        self._taskbar_z_order = _WindowsTaskbarZOrder() if os.name == "nt" else None
        self._native_hit_coordinates = (
            _WindowsHitTestCoordinates() if os.name == "nt" else None
        )
        self.setObjectName("petEffectOverlayWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._apply_flags(always_on_top=True)

    def show_layout(
        self,
        layout: PetRenderLayout,
        *,
        always_on_top: bool,
    ) -> None:
        if layout.mode is not PetRenderSurfaceMode.OVERFLOW:
            raise ValueError("overlay requires overflow layout")
        self._surface_retired = False
        generation = self._renderer_generation()
        if generation != self._expected_render_generation:
            self._published_hit_frame = None
            self._expected_render_generation = generation
        flags_changed = always_on_top != self._applied_always_on_top
        if flags_changed:
            self._apply_flags(always_on_top=always_on_top)
            self._applied_always_on_top = always_on_top
        rect = layout.surface_rect
        geometry = QRect(
            round(rect.x),
            round(rect.y),
            round(rect.width),
            round(rect.height),
        )
        if geometry != self._applied_geometry:
            self.setGeometry(geometry)
            self._applied_geometry = geometry
        offset = layout.body_window_offset
        self._body_input_rect = QRectF(
            offset.x,
            offset.y,
            self._input_target.width(),
            self._input_target.height(),
        )
        if not self.isVisible():
            self.show()
            self.raise_()
        elif flags_changed:
            self.raise_()
        if always_on_top and self._taskbar_z_order is not None:
            self._taskbar_z_order.restore_if_taskbar_is_above(int(self.winId()))
        self.update()

    def hide_surface(self) -> None:
        self._proxy_pointer_active = False
        self._surface_retired = False
        self._published_hit_frame = None
        self._expected_render_generation = None
        self.hide()

    def retire_surface(self) -> None:
        """Clear the scene but preserve an active proxy gesture until release."""

        self._surface_retired = True
        self._published_hit_frame = None
        if not self._proxy_pointer_active:
            self.hide_surface()
            return
        self.repaint()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        try:
            if self._surface_retired:
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Source
                )
                painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            else:
                self._published_hit_frame = None
                image = self._renderer.render_surface(painter)
                generation = self._renderer_generation()
                if (
                    isinstance(image, QImage)
                    and not image.isNull()
                    and generation == self._expected_render_generation
                ):
                    ratio = float(
                        getattr(
                            self._renderer,
                            "device_pixel_ratio",
                            image.width() / max(1, self.width()),
                        )
                    )
                    self._published_hit_frame = PetSurfaceHitFrame.from_image(
                        image,
                        logical_width=float(self.width()),
                        logical_height=float(self.height()),
                        device_pixel_ratio=ratio,
                        generation=generation,
                    )
        finally:
            painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._forward_mouse_event(event, require_body_hit=True)
        self._proxy_pointer_active = (
            event.button() is Qt.MouseButton.LeftButton
            and event.isAccepted()
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._proxy_pointer_active:
            event.ignore()
            return
        self._forward_mouse_event(event, require_body_hit=False)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._proxy_pointer_active:
            event.ignore()
            return
        self._forward_mouse_event(event, require_body_hit=False)
        if event.button() is Qt.MouseButton.LeftButton:
            self._proxy_pointer_active = False
            if self._surface_retired:
                self.hide_surface()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        global_position = event.globalPos()
        if not self._contains_global_point(
            float(global_position.x()),
            float(global_position.y()),
        ):
            event.ignore()
            return
        local_position = self._input_target.mapFromGlobal(global_position)
        forwarded = QContextMenuEvent(
            event.reason(),
            local_position,
            global_position,
            event.modifiers(),
        )
        QApplication.sendEvent(self._input_target, forwarded)
        event.setAccepted(forwarded.isAccepted())

    def nativeEvent(
        self,
        event_type: QByteArray | bytes | bytearray | memoryview[int],
        message: int,
    ) -> object:
        native_type = (
            event_type.data()
            if isinstance(event_type, QByteArray)
            else bytes(event_type)
        )
        if os.name == "nt" and native_type in {
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        }:
            native_message = ctypes.wintypes.MSG.from_address(int(message))
            if native_message.message == 0x0084:  # WM_NCHITTEST
                packed_position = int(native_message.lParam)
                screen_x = ctypes.c_short(packed_position & 0xFFFF).value
                screen_y = ctypes.c_short(
                    (packed_position >> 16) & 0xFFFF
                ).value
                coordinates = self._native_hit_coordinates
                local_point = (
                    None
                    if coordinates is None
                    else coordinates.to_logical(
                        int(self.winId()),
                        screen_x,
                        screen_y,
                        logical_width=self.width(),
                        logical_height=self.height(),
                    )
                )
                if local_point is not None and self._contains_local_point(
                    local_point.x(),
                    local_point.y(),
                ):
                    return True, 1  # HTCLIENT: proxy the body interaction.
                return True, -1  # HTTRANSPARENT outside the body hit area.
        return super().nativeEvent(event_type, message)

    def _forward_mouse_event(
        self,
        event: QMouseEvent,
        *,
        require_body_hit: bool,
    ) -> None:
        global_position = event.globalPosition()
        if require_body_hit and not self._contains_global_point(
            global_position.x(), global_position.y()
        ):
            event.ignore()
            return
        target_position = self._input_target.mapFromGlobal(
            global_position.toPoint()
        )
        forwarded = QMouseEvent(
            event.type(),
            QPointF(target_position),
            global_position,
            event.button(),
            event.buttons(),
            event.modifiers(),
            event.pointingDevice(),
        )
        QApplication.sendEvent(self._input_target, forwarded)
        event.setAccepted(forwarded.isAccepted())

    def _contains_global_point(self, screen_x: float, screen_y: float) -> bool:
        return self._contains_local_point(
            screen_x - self.x(),
            screen_y - self.y(),
        )

    def _contains_local_point(self, local_x: float, local_y: float) -> bool:
        if self._body_input_rect.contains(local_x, local_y):
            return True
        frame = self._published_hit_frame
        return (
            frame is not None
            and frame.generation == self._expected_render_generation
            and frame.generation == self._renderer_generation()
            and frame.contains_logical(QPointF(local_x, local_y))
        )

    def _renderer_generation(self) -> int:
        value = getattr(self._renderer, "render_generation", 0)
        return int(value) if isinstance(value, int) and value >= 0 else 0

    def _apply_flags(self, *, always_on_top: bool) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
