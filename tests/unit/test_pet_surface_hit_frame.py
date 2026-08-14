from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage

from arkclaw.presentation.qt.pet.pet_surface_hit_frame import PetSurfaceHitFrame


def _image_with_alpha(
    width: int,
    height: int,
    points: dict[tuple[int, int], int],
) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(0)
    for (x, y), alpha in points.items():
        image.setPixelColor(x, y, QColor(255, 255, 255, alpha))
    return image


@pytest.mark.parametrize("device_pixel_ratio", [1.0, 1.25, 1.5, 2.0])
def test_hit_frame_maps_logical_coordinates_to_thresholded_alpha_bitmap(
    device_pixel_ratio: float,
) -> None:
    logical_width = 32.0
    logical_height = 32.0
    physical_width = math.ceil(logical_width * device_pixel_ratio)
    physical_height = math.ceil(logical_height * device_pixel_ratio)
    image = _image_with_alpha(
        physical_width,
        physical_height,
        {
            (0, 0): 8,
            (math.floor(10.0 * device_pixel_ratio), 0): 1,
            (
                math.floor(20.0 * device_pixel_ratio),
                math.floor(20.0 * device_pixel_ratio),
            ): 255,
        },
    )

    frame = PetSurfaceHitFrame.from_image(
        image,
        logical_width=logical_width,
        logical_height=logical_height,
        device_pixel_ratio=device_pixel_ratio,
        generation=7,
    )

    assert frame.generation == 7
    assert frame.contains_logical(QPointF(0.0, 0.0))
    assert not frame.contains_logical(QPointF(10.0, 0.0))
    assert frame.contains_logical(QPointF(20.0, 20.0))
    assert not frame.contains_logical(QPointF(-0.01, 0.0))
    assert not frame.contains_logical(QPointF(0.0, -0.01))
    assert not frame.contains_logical(QPointF(logical_width, 0.0))
    assert not frame.contains_logical(QPointF(0.0, logical_height))


def test_hit_frame_copies_only_compact_alpha_bitmap_from_source_image() -> None:
    image = _image_with_alpha(32, 32, {(4, 5): 255})

    frame = PetSurfaceHitFrame.from_image(
        image,
        logical_width=32.0,
        logical_height=32.0,
        device_pixel_ratio=1.0,
        generation=1,
    )
    image.fill(0)

    assert frame.contains_logical(QPointF(4.0, 5.0))
    assert len(frame.alpha_mask) == 128


@pytest.mark.parametrize(
    ("logical_width", "logical_height", "device_pixel_ratio"),
    [
        (0.0, 32.0, 1.0),
        (32.0, 0.0, 1.0),
        (32.0, 32.0, 0.0),
        (32.0, 32.0, float("inf")),
    ],
)
def test_hit_frame_rejects_invalid_surface_geometry(
    logical_width: float,
    logical_height: float,
    device_pixel_ratio: float,
) -> None:
    image = QImage(32, 32, QImage.Format.Format_RGBA8888)

    with pytest.raises(ValueError):
        PetSurfaceHitFrame.from_image(
            image,
            logical_width=logical_width,
            logical_height=logical_height,
            device_pixel_ratio=device_pixel_ratio,
            generation=1,
        )
