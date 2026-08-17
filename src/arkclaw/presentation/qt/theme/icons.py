"""Frozen 1.75 px stroke vector icons for the Qt frontend (Slice 7G polish).

Authority: docs/design/07-visual-design-freeze-v1.md "Icons" and
visual-freeze-v1.tokens.json icon map: navigation/action 20, small 16,
file/image 18, Thinking glyph 20, stroke 1.75, default hit target 40.  The
frozen inventory is exactly Home / Chat / Work / Character Animation /
Settings / Attach File-Image / Folder Context / Artifact / Open / Export /
Retry / Send.  Activity rows additionally render semantic vector marks
(check, filled dot, hollow dot, error X, warning triangle) so state is never
color-only (07 14).

All icons are QPainterPath drawings in a 20x20 design viewBox.  The pen
width scales linearly, so a 20 px icon renders at exactly the frozen
1.75 px stroke and smaller sizes stay proportional.  Colors are supplied by
the caller from the frozen theme tokens (theme.icon / theme.accent.default /
theme.state.*), keeping the Light/Dark semantic contract single-sourced in
design_tokens.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    ThemeVariant,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme

_DESIGN_SIZE = 20.0


class IconKind(StrEnum):
    """Frozen icon inventory plus semantic activity marks."""

    HOME = "home"
    CHAT_WORK = "chat_work"
    CHARACTER_ANIMATION = "character_animation"
    SETTINGS = "settings"
    ATTACH = "attach"
    FOLDER = "folder"
    ARTIFACT = "artifact"
    OPEN = "open"
    EXPORT = "export"
    RETRY = "retry"
    SEND = "send"
    ACTIVITY_COMPLETED = "activity_completed"
    ACTIVITY_CURRENT = "activity_current"
    ACTIVITY_FUTURE = "activity_future"
    ACTIVITY_ERROR = "activity_error"
    ACTIVITY_WARNING = "activity_warning"


_INVENTORY_KINDS = (
    IconKind.HOME,
    IconKind.CHAT_WORK,
    IconKind.CHARACTER_ANIMATION,
    IconKind.SETTINGS,
    IconKind.ATTACH,
    IconKind.FOLDER,
    IconKind.ARTIFACT,
    IconKind.OPEN,
    IconKind.EXPORT,
    IconKind.RETRY,
    IconKind.SEND,
)

# Keyed by DashboardPage.value (StrEnum) so the icon layer stays free of
# dashboard-package imports: theme -> dashboard -> theme would otherwise be
# a circular import chain at package-import time.
_PAGE_KIND_BY_ID = {
    "home": IconKind.HOME,
    "chat_work": IconKind.CHAT_WORK,
    "character_animation": IconKind.CHARACTER_ANIMATION,
}

_FILLED_KINDS = frozenset({IconKind.ACTIVITY_CURRENT})


def icon_kind_for_page(page: Any) -> IconKind:
    """Map a primary DashboardPage (StrEnum) to its frozen navigation icon."""
    value = getattr(page, "value", page)
    return _PAGE_KIND_BY_ID[str(value)]


def icon_color_for_theme(tokens: DesignTokens, theme: QtTheme) -> str:
    """Frozen neutral icon stroke color for a theme (theme.icon)."""
    return tokens.theme(ThemeVariant(theme.value)).icon


def accent_color_for_theme(tokens: DesignTokens, theme: QtTheme) -> str:
    """Frozen accent color for selected navigation icons."""
    return tokens.theme(ThemeVariant(theme.value)).accent.default


def stroke_for_size(
    size: float,
    tokens: DesignTokens | None = None,
) -> float:
    """Pen width for ``size`` logical px (1.75 at the 20 px design size)."""
    source = tokens if tokens is not None else load_design_tokens()
    stroke = float(source.icon["stroke"])
    return stroke * size / _DESIGN_SIZE


def draw_icon(
    painter: QPainter,
    kind: IconKind,
    rect: QRectF,
    color: str,
    stroke: float | None = None,
) -> None:
    """Paint a frozen vector icon centered in ``rect``.

    The pen is round-capped/joined so 1.75 px strokes read as Material-like
    line icons; only :attr:`IconKind.ACTIVITY_CURRENT` fills its mark.
    """
    path, filled = _build_icon(kind)
    if stroke is None:
        stroke = float(load_design_tokens().icon["stroke"])
    scale = min(rect.width() / _DESIGN_SIZE, rect.height() / _DESIGN_SIZE)
    offset_x = rect.center().x() - (_DESIGN_SIZE / 2.0) * scale
    offset_y = rect.center().y() - (_DESIGN_SIZE / 2.0) * scale
    pen = QPen(QColor(color), max(stroke * scale, 1.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QColor(color) if filled else Qt.BrushStyle.NoBrush)
    painter.drawPath(
        _scale_path(path, offset_x, offset_y, scale)
    )


def icon_pixmap(
    kind: IconKind,
    size: float,
    color: str,
    *,
    stroke: float | None = None,
    dpr: float = 1.0,
) -> QPixmap:
    """Render one frozen icon to a device-pixel-ratio aware pixmap.

    Logical size is ``size``; physical pixels are ``ceil(size * dpr)``.
    """
    physical = max(1, math.ceil(size * dpr))
    pixmap = QPixmap(physical, physical)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(
        painter,
        kind,
        QRectF(0.0, 0.0, float(size), float(size)),
        color,
        stroke,
    )
    painter.end()
    return pixmap


def _scale_path(
    path: QPainterPath,
    offset_x: float,
    offset_y: float,
    scale: float,
) -> QPainterPath:
    from PySide6.QtGui import QTransform

    transform = QTransform()
    transform.translate(offset_x, offset_y)
    transform.scale(scale, scale)
    return transform.map(path)


def _build_icon(kind: IconKind) -> tuple[QPainterPath, bool]:
    builders = {
        IconKind.HOME: _path_home,
        IconKind.CHAT_WORK: _path_chat_work,
        IconKind.CHARACTER_ANIMATION: _path_character_animation,
        IconKind.SETTINGS: _path_settings,
        IconKind.ATTACH: _path_attach,
        IconKind.FOLDER: _path_folder,
        IconKind.ARTIFACT: _path_artifact,
        IconKind.OPEN: _path_open,
        IconKind.EXPORT: _path_export,
        IconKind.RETRY: _path_retry,
        IconKind.SEND: _path_send,
        IconKind.ACTIVITY_COMPLETED: _path_activity_completed,
        IconKind.ACTIVITY_CURRENT: _path_activity_current,
        IconKind.ACTIVITY_FUTURE: _path_activity_future,
        IconKind.ACTIVITY_ERROR: _path_activity_error,
        IconKind.ACTIVITY_WARNING: _path_activity_warning,
    }
    builder = builders[kind]
    return builder(), kind in _FILLED_KINDS


def _path_home() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(8.3, 16.7)
    path.lineTo(8.3, 11.7)
    path.lineTo(11.7, 11.7)
    path.lineTo(11.7, 16.7)
    path.lineTo(15.8, 16.7)
    path.lineTo(15.8, 9.2)
    path.lineTo(17.5, 9.2)
    path.lineTo(10.0, 2.5)
    path.lineTo(2.5, 9.2)
    path.lineTo(4.2, 9.2)
    path.lineTo(4.2, 16.7)
    path.closeSubpath()
    return path


def _path_chat_work() -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(3.0, 4.0, 14.0, 10.0), 3.0, 3.0)
    path.moveTo(6.8, 14.0)
    path.lineTo(5.0, 17.0)
    path.lineTo(9.8, 14.0)
    return path


def _path_character_animation() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(7.2, 2.5, 5.6, 5.6))
    path.moveTo(3.5, 16.7)
    path.cubicTo(3.5, 12.3, 16.5, 12.3, 16.5, 16.7)
    return path


def _path_settings() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(5.8, 5.8, 8.4, 8.4))
    path.addEllipse(QRectF(8.8, 8.8, 2.4, 2.4))
    for index in range(8):
        angle = math.radians(index * 45.0)
        cos, sin = math.cos(angle), math.sin(angle)
        path.moveTo(10.0 + 6.6 * cos, 10.0 + 6.6 * sin)
        path.lineTo(10.0 + 7.9 * cos, 10.0 + 7.9 * sin)
    return path


def _path_attach() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(6.8, 10.5)
    path.cubicTo(6.8, 5.8, 13.2, 5.8, 13.2, 10.5)
    path.lineTo(13.2, 13.3)
    path.cubicTo(13.2, 15.4, 11.6, 16.8, 9.7, 16.8)
    path.cubicTo(7.8, 16.8, 6.8, 15.4, 6.8, 13.3)
    path.lineTo(6.8, 7.8)
    path.cubicTo(6.8, 6.6, 7.7, 5.9, 8.8, 5.9)
    path.lineTo(8.8, 12.2)
    return path


def _path_folder() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(3.3, 6.7)
    path.lineTo(8.3, 6.7)
    path.lineTo(9.6, 8.3)
    path.lineTo(16.7, 8.3)
    path.lineTo(16.7, 14.2)
    path.lineTo(3.3, 14.2)
    path.closeSubpath()
    return path


def _path_artifact() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(5.0, 2.5)
    path.lineTo(12.5, 2.5)
    path.lineTo(15.0, 5.0)
    path.lineTo(15.0, 17.5)
    path.lineTo(5.0, 17.5)
    path.closeSubpath()
    path.moveTo(12.5, 2.5)
    path.lineTo(12.5, 5.0)
    path.lineTo(15.0, 5.0)
    path.moveTo(7.5, 9.5)
    path.lineTo(12.5, 9.5)
    path.moveTo(7.5, 12.5)
    path.lineTo(12.5, 12.5)
    return path


def _path_open() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(4.0, 6.5)
    path.lineTo(4.0, 16.5)
    path.lineTo(16.0, 16.5)
    path.lineTo(16.0, 6.5)
    path.moveTo(6.5, 13.5)
    path.lineTo(12.5, 7.5)
    path.moveTo(12.5, 7.5)
    path.lineTo(9.8, 7.5)
    path.moveTo(12.5, 7.5)
    path.lineTo(12.5, 10.2)
    return path


def _path_export() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(10.0, 3.5)
    path.lineTo(10.0, 12.0)
    path.moveTo(6.5, 8.5)
    path.lineTo(10.0, 12.0)
    path.lineTo(13.5, 8.5)
    path.moveTo(3.5, 16.5)
    path.lineTo(16.5, 16.5)
    return path


def _path_retry() -> QPainterPath:
    path = QPainterPath()
    path.arcMoveTo(QRectF(4.0, 4.0, 12.0, 12.0), 270.0)
    path.arcTo(QRectF(4.0, 4.0, 12.0, 12.0), 270.0, 300.0)
    path.moveTo(10.0, 4.0)
    path.lineTo(7.5, 5.5)
    path.moveTo(10.0, 4.0)
    path.lineTo(7.5, 2.5)
    return path


def _path_send() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(3.5, 10.5)
    path.lineTo(16.5, 3.5)
    path.lineTo(12.5, 16.5)
    path.closeSubpath()
    path.moveTo(16.5, 3.5)
    path.lineTo(9.5, 11.0)
    path.moveTo(3.5, 10.5)
    path.lineTo(9.5, 11.0)
    return path


def _path_activity_completed() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(4.5, 10.5)
    path.lineTo(8.5, 14.5)
    path.lineTo(15.5, 6.0)
    return path


def _path_activity_current() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(6.0, 6.0, 8.0, 8.0))
    return path


def _path_activity_future() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(6.0, 6.0, 8.0, 8.0))
    return path


def _path_activity_error() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(5.0, 5.0, 10.0, 10.0))
    path.moveTo(8.0, 8.0)
    path.lineTo(12.0, 12.0)
    path.moveTo(12.0, 8.0)
    path.lineTo(8.0, 12.0)
    return path


def _path_activity_warning() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(10.0, 3.5)
    path.lineTo(17.5, 16.5)
    path.lineTo(2.5, 16.5)
    path.closeSubpath()
    path.moveTo(10.0, 8.0)
    path.lineTo(10.0, 12.5)
    path.addEllipse(QRectF(9.2, 14.0, 1.6, 1.6))
    return path
