"""Replaceable Qt rendering boundary for the placeholder desktop pet."""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPolygonF,
)

from arkclaw.application.pet.pet_animation import PetRenderFrame
from arkclaw.application.pet.pet_geometry import Size
from arkclaw.application.pet.pet_renderer_model import (
    ExternalAssetConfigStatus,
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
    PetRendererConfig,
    PetRendererKind,
    placeholder_animation_capability,
    validate_pet_renderer_config,
)
from arkclaw.application.pet.pet_state import (
    PetBehaviorState,
    PetFacing,
    PetLifecycleState,
    PetMotionState,
)


@runtime_checkable
class PetRenderer(Protocol):
    def initialize(self, viewport: Size) -> None:
        """Initialize renderer-owned state for a logical viewport."""

    def set_viewport(self, viewport: Size) -> None:
        """Receive logical viewport changes."""

    def set_state(self, request: PetRendererActionRequest) -> None:
        """Receive a renderer-neutral action request."""

    def update(self, delta_seconds: float) -> None:
        """Advance renderer-owned animation without blocking."""

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        """Render one non-sensitive visual frame."""

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        """Describe support without loading or scanning external assets."""

    def pause(self) -> None:
        """Pause renderer-owned time."""

    def resume(self) -> None:
        """Resume renderer-owned time."""

    def close(self) -> None:
        """Release renderer-owned resources idempotently."""


class PetRendererSafeCode(StrEnum):
    NONE = "none"
    CONSTRUCTION_FAILED = "pet_renderer_construction_failed"
    INITIALIZATION_FAILED = "pet_renderer_initialization_failed"
    VIEWPORT_FAILED = "pet_renderer_viewport_failed"
    STATE_FAILED = "pet_renderer_state_failed"
    UPDATE_FAILED = "pet_renderer_update_failed"
    RENDER_FAILED = "pet_renderer_render_failed"
    PAUSE_FAILED = "pet_renderer_pause_failed"
    RESUME_FAILED = "pet_renderer_resume_failed"
    CLOSE_FAILED = "pet_renderer_close_failed"
    INVALID_CONFIGURATION = "pet_renderer_invalid_configuration"
    RUNTIME_UNAVAILABLE = "pet_renderer_runtime_unavailable"


class SafePetRenderer:
    """Contain renderer failures and retain a programmatic fallback."""

    def __init__(
        self,
        renderer: PetRenderer,
        *,
        initial_safe_code: PetRendererSafeCode = PetRendererSafeCode.NONE,
    ) -> None:
        self._renderer = renderer
        self._safe_code = initial_safe_code
        self._viewport = Size(160, 180)
        self._state: PetRendererActionRequest | None = None
        self._paused = False
        self._closed = False

    @property
    def safe_code(self) -> PetRendererSafeCode:
        return self._safe_code

    @property
    def using_placeholder(self) -> bool:
        return isinstance(self._renderer, PlaceholderPetRenderer)

    @property
    def closed(self) -> bool:
        return self._closed

    def initialize(self, viewport: Size) -> None:
        if self._closed:
            return
        self._viewport = viewport
        try:
            self._renderer.initialize(viewport)
        except Exception:
            self._activate_fallback(PetRendererSafeCode.INITIALIZATION_FAILED)

    def set_viewport(self, viewport: Size) -> None:
        if self._closed:
            return
        self._viewport = viewport
        try:
            self._renderer.set_viewport(viewport)
        except Exception:
            self._activate_fallback(PetRendererSafeCode.VIEWPORT_FAILED)

    def set_device_pixel_ratio(self, value: float) -> None:
        """Forward optional DPR support without widening the renderer protocol."""

        if self._closed:
            return
        callback = getattr(self._renderer, "set_device_pixel_ratio", None)
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            self._activate_fallback(PetRendererSafeCode.VIEWPORT_FAILED)

    def set_state(self, request: PetRendererActionRequest) -> None:
        if self._closed:
            return
        self._state = request
        try:
            self._renderer.set_state(request)
        except Exception:
            self._activate_fallback(PetRendererSafeCode.STATE_FAILED)

    def update(self, delta_seconds: float) -> None:
        if self._closed or self._paused:
            return
        try:
            self._renderer.update(delta_seconds)
        except Exception:
            self._activate_fallback(PetRendererSafeCode.UPDATE_FAILED)

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        if self._closed:
            return
        failed = False
        painter.save()
        try:
            self._renderer.render(painter, frame)
        except Exception:
            failed = True
        finally:
            painter.restore()
        if failed:
            self._activate_fallback(PetRendererSafeCode.RENDER_FAILED)
            painter.save()
            try:
                self._renderer.render(painter, frame)
            finally:
                painter.restore()

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        try:
            return self._renderer.animation_capability(action)
        except Exception:
            self._activate_fallback(PetRendererSafeCode.STATE_FAILED)
            return self._renderer.animation_capability(action)

    def pause(self) -> None:
        if self._closed or self._paused:
            return
        self._paused = True
        try:
            self._renderer.pause()
        except Exception:
            self._activate_fallback(PetRendererSafeCode.PAUSE_FAILED)

    def resume(self) -> None:
        if self._closed or not self._paused:
            return
        self._paused = False
        try:
            self._renderer.resume()
        except Exception:
            self._activate_fallback(PetRendererSafeCode.RESUME_FAILED)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._renderer.close()
        except Exception:
            self._safe_code = PetRendererSafeCode.CLOSE_FAILED

    def _activate_fallback(self, safe_code: PetRendererSafeCode) -> None:
        if self._closed:
            return
        previous = self._renderer
        with suppress(Exception):
            previous.close()
        fallback = PlaceholderPetRenderer()
        fallback.initialize(self._viewport)
        if self._state is not None:
            fallback.set_state(self._state)
        if self._paused:
            fallback.pause()
        self._renderer = fallback
        self._safe_code = safe_code

    def __repr__(self) -> str:
        return (
            "SafePetRenderer("
            f"safe_code={self._safe_code.value!r}, "
            f"using_placeholder={self.using_placeholder!r}, "
            f"closed={self._closed!r})"
        )


def create_safe_pet_renderer(
    factory: Callable[[], PetRenderer],
) -> SafePetRenderer:
    """Construct a renderer without exposing its failure details."""

    try:
        renderer = factory()
    except Exception:
        return SafePetRenderer(
            PlaceholderPetRenderer(),
            initial_safe_code=PetRendererSafeCode.CONSTRUCTION_FAILED,
        )
    return SafePetRenderer(renderer)


def create_configured_pet_renderer(
    config: PetRendererConfig,
) -> SafePetRenderer:
    """Select a renderer without scanning or persisting external resources."""

    status = validate_pet_renderer_config(config)
    if (
        config.renderer_kind is PetRendererKind.PLACEHOLDER
        and status is ExternalAssetConfigStatus.VALID
    ):
        return SafePetRenderer(PlaceholderPetRenderer())
    safe_code = (
        PetRendererSafeCode.RUNTIME_UNAVAILABLE
        if (
            config.renderer_kind is PetRendererKind.SPINE38
            and status is ExternalAssetConfigStatus.VALID
        )
        or status is ExternalAssetConfigStatus.RENDERER_UNAVAILABLE
        else PetRendererSafeCode.INVALID_CONFIGURATION
    )
    return SafePetRenderer(
        PlaceholderPetRenderer(),
        initial_safe_code=safe_code,
    )


class PlaceholderPetRenderer:
    """Draw the original programmatic character without external assets."""

    foot_baseline_y = 160.0
    _breathing_fixed_y = 144.0
    _breathing_top_y = 24.0
    _breathing_vertical_travel = 5.0
    _breathing_horizontal_travel = 1.5

    def __init__(self) -> None:
        self._size = Size(160, 180)
        self._closed = False
        self._paused = False
        self._state: PetRendererActionRequest | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    def initialize(self, viewport: Size) -> None:
        self.set_viewport(viewport)

    def set_viewport(self, viewport: Size) -> None:
        if self._closed:
            return
        self._size = viewport

    def resize(self, size: Size) -> None:
        """Backward-compatible alias for the original renderer boundary."""

        self.set_viewport(size)

    def set_state(self, request: PetRendererActionRequest) -> None:
        if not self._closed:
            self._state = request

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        if not self._closed:
            self._paused = True

    def resume(self) -> None:
        if not self._closed:
            self._paused = False

    def close(self) -> None:
        self._closed = True

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        if self._closed:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_shadow(painter)

        painter.save()
        self._apply_character_transform(painter, frame)
        self._draw_limbs(painter, frame)
        self._draw_body(painter, frame)
        painter.restore()
        self._draw_overlay(painter, frame)

    @staticmethod
    def _draw_shadow(painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(25, 45, 55, 70))
        painter.drawEllipse(QRectF(28, 158, 104, 15))

    def _apply_character_transform(
        self,
        painter: QPainter,
        frame: PetRenderFrame,
    ) -> None:
        foot_x = self._size.width / 2
        foot_y = self.foot_baseline_y
        landing_scale = (
            0.92
            if frame.state.motion is PetMotionState.LANDING
            else 1.0
        )
        walk_bob = (
            -2.0
            * abs(math.sin(frame.intent.progress * math.tau))
            if frame.state.motion
            in {
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            }
            else 0.0
        )
        drag_rotation = frame.visual.body_wiggle * 4.0
        thinking_rotation = frame.visual.thinking_tilt * 5.0

        painter.translate(foot_x, foot_y + walk_bob)
        if frame.intent.facing is PetFacing.LEFT:
            painter.scale(-1.0, 1.0)
        painter.rotate(drag_rotation + thinking_rotation)
        painter.scale(1.0, landing_scale)
        painter.translate(-foot_x, -foot_y)

    def _breathing_point(
        self,
        point: QPointF,
        frame: PetRenderFrame,
    ) -> QPointF:
        influence = min(
            1.0,
            max(
                0.0,
                (self._breathing_fixed_y - point.y())
                / (self._breathing_fixed_y - self._breathing_top_y),
            ),
        )
        amount = frame.visual.breathing_amount * influence
        horizontal_direction = min(
            1.0,
            max(-1.0, (point.x() - self._size.width / 2) / 52.0),
        )
        return QPointF(
            point.x()
            + horizontal_direction
            * self._breathing_horizontal_travel
            * amount,
            point.y() - self._breathing_vertical_travel * amount,
        )

    def _breathing_rect(
        self,
        rect: QRectF,
        frame: PetRenderFrame,
    ) -> QRectF:
        return QRectF(
            self._breathing_point(rect.topLeft(), frame),
            self._breathing_point(rect.bottomRight(), frame),
        ).normalized()

    def _draw_limbs(
        self,
        painter: QPainter,
        frame: PetRenderFrame,
    ) -> None:
        swing = 0.0
        if frame.state.motion in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            swing = math.sin(frame.intent.progress * math.tau) * 8.0
        elif PetBehaviorState.DRAG_STRUGGLE in frame.state.behaviors:
            swing = frame.visual.body_wiggle * 12.0
        pen = QPen(QColor(25, 71, 82), 7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(51, 132),
            QPointF(46 + swing, 157),
        )
        painter.drawLine(
            QPointF(109, 132),
            QPointF(114 - swing, 157),
        )
        painter.drawLine(
            self._breathing_point(QPointF(37, 100), frame),
            self._breathing_point(QPointF(24, 116 - swing / 2), frame),
        )
        painter.drawLine(
            self._breathing_point(QPointF(123, 100), frame),
            self._breathing_point(QPointF(136, 116 + swing / 2), frame),
        )

    def _draw_body(
        self,
        painter: QPainter,
        frame: PetRenderFrame,
    ) -> None:
        outline = QPen(QColor(25, 71, 82), 5)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(outline)
        painter.setBrush(QColor(80, 207, 188))
        body = QPolygonF(
            [
                self._breathing_point(point, frame)
                for point in (
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
                )
            ]
        )
        painter.drawPolygon(body)

        eye_height = max(2.0, 31.0 * frame.visual.eye_openness)
        eye_y = 73.0 + (31.0 - eye_height) / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(235, 252, 246))
        painter.drawEllipse(
            self._breathing_rect(
                QRectF(48, eye_y, 25, eye_height),
                frame,
            )
        )
        painter.drawEllipse(
            self._breathing_rect(
                QRectF(87, eye_y, 25, eye_height),
                frame,
            )
        )
        if frame.visual.eye_openness > 0.25:
            pupil_height = max(2.0, 12.0 * frame.visual.eye_openness)
            pupil_y = 84.0 + (12.0 - pupil_height) / 2.0
            painter.setBrush(QColor(24, 57, 69))
            painter.drawEllipse(
                self._breathing_rect(
                    QRectF(58, pupil_y, 8, pupil_height),
                    frame,
                )
            )
            painter.drawEllipse(
                self._breathing_rect(
                    QRectF(97, pupil_y, 8, pupil_height),
                    frame,
                )
            )
        else:
            painter.setPen(QPen(QColor(24, 57, 69), 3))
            painter.drawLine(
                self._breathing_point(QPointF(51, 89), frame),
                self._breathing_point(QPointF(70, 89), frame),
            )
            painter.drawLine(
                self._breathing_point(QPointF(90, 89), frame),
                self._breathing_point(QPointF(109, 89), frame),
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(24, 57, 69))
        painter.drawEllipse(
            self._breathing_rect(QRectF(75, 107, 10, 8), frame)
        )
        painter.setPen(QPen(QColor(25, 71, 82), 4))
        painter.drawArc(
            self._breathing_rect(QRectF(62, 109, 18, 16), frame),
            200 * 16,
            110 * 16,
        )
        painter.drawArc(
            self._breathing_rect(QRectF(80, 109, 18, 16), frame),
            230 * 16,
            110 * 16,
        )

    @staticmethod
    def _draw_overlay(painter: QPainter, frame: PetRenderFrame) -> None:
        if frame.state.lifecycle is PetLifecycleState.PAUSED:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 220))
            painter.drawRoundedRect(QRectF(112, 8, 38, 30), 8, 8)
            painter.setBrush(QColor(25, 71, 82))
            painter.drawRect(QRectF(124, 15, 5, 16))
            painter.drawRect(QRectF(134, 15, 5, 16))
            return
        if PetBehaviorState.THINKING in frame.state.behaviors:
            PlaceholderPetRenderer._draw_badge(
                painter,
                "?",
                QColor(253, 246, 185, 235),
                1.0,
            )
        elif PetBehaviorState.REMINDING in frame.state.behaviors:
            PlaceholderPetRenderer._draw_badge(
                painter,
                "!",
                QColor(255, 205, 112, 235),
                1.0 + frame.visual.reminder_pulse * 0.08,
            )

    @staticmethod
    def _draw_badge(
        painter: QPainter,
        text: str,
        color: QColor,
        scale: float,
    ) -> None:
        painter.save()
        painter.translate(130, 22)
        painter.scale(scale, scale)
        painter.translate(-130, -22)
        painter.setPen(QPen(QColor(25, 71, 82), 2))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(112, 4, 36, 36))
        marker_pen = QPen(QColor(25, 71, 82), 4)
        marker_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(marker_pen)
        painter.setBrush(QColor(25, 71, 82))
        if text == "?":
            painter.drawArc(
                QRectF(120, 9, 20, 17),
                20 * 16,
                220 * 16,
            )
            painter.drawLine(QPointF(130, 24), QPointF(130, 28))
        else:
            painter.drawLine(QPointF(130, 11), QPointF(130, 27))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(128, 31, 4, 4))
        painter.restore()
