"""Immutable alpha-hit snapshot derived from one already-rendered frame."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, qRgb

_ALPHA_HIT_THRESHOLD = 8
_ALPHA_THRESHOLD_TABLE = tuple(
    qRgb(0, 0, 0) if alpha < _ALPHA_HIT_THRESHOLD else qRgb(255, 255, 255)
    for alpha in range(256)
)
_INVERT_BYTES = bytes.maketrans(
    bytes(range(256)),
    bytes(255 - value for value in range(256)),
)


@dataclass(frozen=True, slots=True)
class PetSurfaceHitFrame:
    """Compact physical-pixel hit mask for one logical surface generation."""

    width: int
    height: int
    logical_width: float
    logical_height: float
    device_pixel_ratio: float
    alpha_mask: bytes
    generation: int

    @classmethod
    def from_image(
        cls,
        image: QImage,
        *,
        logical_width: float,
        logical_height: float,
        device_pixel_ratio: float,
        generation: int,
    ) -> PetSurfaceHitFrame:
        if (
            image.isNull()
            or not math.isfinite(logical_width)
            or logical_width <= 0.0
            or not math.isfinite(logical_height)
            or logical_height <= 0.0
            or not math.isfinite(device_pixel_ratio)
            or device_pixel_ratio <= 0.0
            or generation < 0
        ):
            raise ValueError("invalid pet surface hit frame")

        alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
        width = alpha.width()
        height = alpha.height()
        if width <= 0 or height <= 0:
            raise ValueError("invalid pet surface hit frame")

        indexed = QImage(
            alpha.constBits(),
            width,
            height,
            alpha.bytesPerLine(),
            QImage.Format.Format_Indexed8,
        )
        indexed.setColorTable(_ALPHA_THRESHOLD_TABLE)
        mono = indexed.convertToFormat(
            QImage.Format.Format_MonoLSB,
            Qt.ImageConversionFlag.ThresholdDither,
        )
        source = bytes(mono.constBits()[: mono.sizeInBytes()])
        source_stride = mono.bytesPerLine()
        mask_stride = (width + 7) // 8
        # Qt's threshold conversion emits zero bits for the white (hittable)
        # side of the palette, so invert only the meaningful row bytes while
        # also dropping QImage's 32-bit row padding.
        mask = b"".join(
            source[row * source_stride : row * source_stride + mask_stride].translate(
                _INVERT_BYTES
            )
            for row in range(height)
        )

        return cls(
            width=width,
            height=height,
            logical_width=logical_width,
            logical_height=logical_height,
            device_pixel_ratio=device_pixel_ratio,
            alpha_mask=mask,
            generation=generation,
        )

    def contains_logical(self, point: QPointF) -> bool:
        x = float(point.x())
        y = float(point.y())
        if (
            not math.isfinite(x)
            or not math.isfinite(y)
            or x < 0.0
            or y < 0.0
            or x >= self.logical_width
            or y >= self.logical_height
        ):
            return False
        physical_x = math.floor(x * self.device_pixel_ratio)
        physical_y = math.floor(y * self.device_pixel_ratio)
        if (
            physical_x < 0
            or physical_x >= self.width
            or physical_y < 0
            or physical_y >= self.height
        ):
            return False
        mask_stride = (self.width + 7) // 8
        byte_index = physical_y * mask_stride + (physical_x >> 3)
        return bool(
            self.alpha_mask[byte_index] & (1 << (physical_x & 7))
        )
