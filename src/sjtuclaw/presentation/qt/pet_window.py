"""Transparent, frameless window for the original placeholder desktop pet."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QContextMenuEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from sjtuclaw.application.pet_geometry import Point, Rect, Size
from sjtuclaw.application.pet_motion import PetMotionModel
from sjtuclaw.application.pet_state import PetState, PetStateTransitionError

_PET_WIDTH = 160
_PET_HEIGHT = 180
_TIMER_INTERVAL_MS = 16


class PetWindow(QWidget):
    """Render and move a small programmatic character without runtime access."""

    open_agent_requested = Signal()
    safe_exit_requested = Signal()

    def __init__(self, *, always_on_top: bool = True) -> None:
        super().__init__()
        self._always_on_top = always_on_top
        self._allow_final_close = False
        self._exit_emitted = False
        self._drag_offset: Point | None = None
        self._context_menu: QMenu | None = None
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
        self._motion = PetMotionModel(
            initial,
            Size(_PET_WIDTH, _PET_HEIGHT),
        )
        self.move(round(initial.x), round(initial.y))

        self._physics_timer = QTimer(self)
        self._physics_timer.setObjectName("petPhysicsTimer")
        self._physics_timer.setInterval(_TIMER_INTERVAL_MS)
        self._physics_timer.timeout.connect(self._advance_motion)
        self._physics_timer.start()

    @property
    def state(self) -> PetState:
        return self._motion.state

    @property
    def always_on_top(self) -> bool:
        return self._always_on_top

    @property
    def physics_timer(self) -> QTimer:
        """Expose the owned timer for lifecycle diagnostics."""

        return self._physics_timer

    def toggle_paused(self) -> None:
        if self.state is PetState.CLOSING:
            return
        try:
            if self.state is PetState.PAUSED:
                self._motion.resume()
            else:
                self._motion.pause()
        except PetStateTransitionError:
            return
        self.update()

    def set_always_on_top(self, enabled: bool) -> None:
        if self.state is PetState.CLOSING or enabled == self._always_on_top:
            return
        self._always_on_top = enabled
        visible = self.isVisible()
        self._apply_window_flags()
        if visible:
            self.show()

    def request_safe_exit(self) -> None:
        if self._exit_emitted:
            return
        try:
            self._motion.begin_closing()
        except PetStateTransitionError:
            return
        self._exit_emitted = True
        self._drag_offset = None
        self._physics_timer.stop()
        self.update()
        self.safe_exit_requested.emit()

    def recover_from_failed_close(self) -> None:
        if self.state is not PetState.CLOSING:
            return
        self._motion.recover_failed_close()
        self._exit_emitted = False
        self._physics_timer.start()
        self.update()

    def complete_safe_close(self) -> None:
        self._allow_final_close = True
        self._physics_timer.stop()
        self.close()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        landing_scale = 0.92 if self.state is PetState.LANDING else 1.0
        painter.translate(self.width() / 2, self.height())
        painter.scale(1.0, landing_scale)
        painter.translate(-self.width() / 2, -self.height())

        shadow = QColor(25, 45, 55, 70)
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(28, 158, 104, 15))

        outline = QPen(QColor(25, 71, 82), 5)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(outline)
        painter.setBrush(QColor(80, 207, 188))
        body = QPolygonF(
            [
                QPointF(35, 56),
                QPointF(48, 24),
                QPointF(66, 48),
                QPointF(94, 48),
                QPointF(112, 24),
                QPointF(125, 56),
                QPointF(132, 112),
                QPointF(116, 148),
                QPointF(80, 160),
                QPointF(44, 148),
                QPointF(28, 112),
            ]
        )
        painter.drawPolygon(body)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(235, 252, 246))
        painter.drawEllipse(QRectF(48, 73, 25, 31))
        painter.drawEllipse(QRectF(87, 73, 25, 31))
        painter.setBrush(QColor(24, 57, 69))
        painter.drawEllipse(QRectF(58, 84, 8, 12))
        painter.drawEllipse(QRectF(97, 84, 8, 12))
        painter.drawEllipse(QRectF(75, 107, 10, 8))

        painter.setPen(QPen(QColor(25, 71, 82), 4))
        painter.drawArc(QRectF(62, 109, 18, 16), 200 * 16, 110 * 16)
        painter.drawArc(QRectF(80, 109, 18, 16), 230 * 16, 110 * 16)

        if self.state is PetState.PAUSED:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 210))
            painter.drawRoundedRect(QRectF(112, 8, 38, 30), 8, 8)
            painter.setBrush(QColor(25, 71, 82))
            painter.drawRect(QRectF(124, 15, 5, 16))
            painter.drawRect(QRectF(134, 15, 5, 16))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() is Qt.MouseButton.LeftButton
            and self._motion.accepts_interaction
        ):
            try:
                self._motion.start_dragging()
            except PetStateTransitionError:
                event.ignore()
                return
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
            self.state is PetState.DRAGGING
            and self._drag_offset is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
        ):
            global_position = event.globalPosition()
            snapshot = self._motion.drag_to(
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
            and self.state is PetState.DRAGGING
        ):
            self._drag_offset = None
            self._motion.release_drag()
            self.update()
            event.accept()
            return
        event.ignore()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self.state is PetState.CLOSING:
            event.ignore()
            return
        if self._context_menu is not None:
            self._context_menu.deleteLater()
        menu = QMenu(self)
        self._context_menu = menu

        pause_action = QAction(
            "Continue" if self.state is PetState.PAUSED else "Pause",
            menu,
        )
        pause_action.triggered.connect(lambda checked=False: self.toggle_paused())
        menu.addAction(pause_action)

        top_action = QAction("Always on top", menu)
        top_action.setCheckable(True)
        top_action.setChecked(self._always_on_top)
        top_action.toggled.connect(self.set_always_on_top)
        menu.addAction(top_action)
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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_final_close:
            self._physics_timer.stop()
            event.accept()
            return
        event.ignore()
        self.request_safe_exit()

    def _advance_motion(self) -> None:
        snapshot = self._motion.update(
            _TIMER_INTERVAL_MS / 1_000,
            self._workspaces(),
        )
        self.move(
            round(snapshot.position.x),
            round(snapshot.position.y),
        )
        self.update()

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
