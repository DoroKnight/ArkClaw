"""Pixel-accurate tests for the programmatic mesh-rendering spike."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_mesh_model import (
    PetMeshBlendMode,
    PetMeshColor,
    PetMeshDrawCommand,
    PetMeshPoint,
    PetMeshScene,
    PetMeshTextureData,
    PetMeshVertex,
)
from sjtuclaw.presentation.qt.pet_mesh_spike import (
    MeshSpikeError,
    MeshSpikeSafeCode,
    OffscreenOpenGLMeshPetRenderer,
    OffscreenOpenGLMeshRenderer,
    SoftwareMeshPetRenderer,
    SoftwareTexturedMeshRenderer,
    generate_mesh_spike_scene,
)
from sjtuclaw.presentation.qt.pet_renderer import SafePetRenderer


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


def _quad(
    texture_id: str,
    *,
    draw_order: int = 0,
    blend_mode: PetMeshBlendMode = PetMeshBlendMode.STRAIGHT_ALPHA,
    uvs: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ),
    clip: tuple[PetMeshPoint, ...] | None = None,
) -> PetMeshDrawCommand:
    positions = ((0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0))
    return PetMeshDrawCommand(
        texture_id=texture_id,
        vertices=tuple(
            PetMeshVertex(PetMeshPoint(*position), *uv, PetMeshColor())
            for position, uv in zip(positions, uvs, strict=True)
        ),
        triangle_indices=(0, 1, 2, 0, 2, 3),
        draw_order=draw_order,
        blend_mode=blend_mode,
        clip_polygon=clip,
    )


def _scene(
    textures: tuple[PetMeshTextureData, ...],
    commands: tuple[PetMeshDrawCommand, ...],
) -> PetMeshScene:
    return PetMeshScene(8, 8, 7.0, textures, commands)


def _raw_pixel(image: QImage, x: int, y: int) -> tuple[int, int, int, int]:
    bits = memoryview(image.bits())
    offset = (y * image.width() + x) * 4
    return tuple(bits[offset + index] for index in range(4))  # type: ignore[return-value]


def test_programmatic_scene_has_transparent_background_and_fixed_size(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = SoftwareTexturedMeshRenderer()
    scene = generate_mesh_spike_scene()

    image = renderer.render_scene(scene)

    assert image.size().toTuple() == (160, 180)
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(80, 80).alpha() > 0
    assert scene.foot_baseline_y == 160.0
    assert renderer.metrics.output_width == 160
    assert renderer.metrics.output_height == 180


def test_uv_origin_is_top_left(qt_application: QApplication) -> None:
    del qt_application
    texture = PetMeshTextureData(
        "orientation",
        2,
        2,
        bytes(
            (
                255,
                0,
                0,
                255,
                0,
                255,
                0,
                255,
                0,
                0,
                255,
                255,
                255,
                255,
                255,
                255,
            )
        ),
    )

    image = SoftwareTexturedMeshRenderer().render_scene(_scene((texture,), (_quad("orientation"),)))

    assert image.pixelColor(1, 1).red() > 240
    assert image.pixelColor(6, 1).green() > 240
    assert image.pixelColor(1, 6).blue() > 240


def test_rotated_texture_uv_mapping_is_equivalent(
    qt_application: QApplication,
) -> None:
    del qt_application
    original = PetMeshTextureData(
        "original",
        2,
        2,
        bytes((255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255)),
    )
    rotated_clockwise = PetMeshTextureData(
        "rotated",
        2,
        2,
        bytes((0, 0, 255, 255, 255, 0, 0, 255, 255, 255, 255, 255, 0, 255, 0, 255)),
    )
    rotated_uvs = ((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    renderer = SoftwareTexturedMeshRenderer()

    first = renderer.render_scene(_scene((original,), (_quad("original"),)))
    second = renderer.render_scene(
        _scene((rotated_clockwise,), (_quad("rotated", uvs=rotated_uvs),))
    )

    assert bytes(first.bits()) == bytes(second.bits())


def test_straight_and_premultiplied_alpha_conventions(
    qt_application: QApplication,
) -> None:
    del qt_application
    straight = PetMeshTextureData("straight", 1, 1, bytes((200, 80, 40, 128)))
    correct_premultiplied = PetMeshTextureData(
        "premultiplied", 1, 1, bytes((100, 40, 20, 128)), premultiplied=True
    )
    incorrect_premultiplied = PetMeshTextureData(
        "incorrect", 1, 1, bytes((200, 80, 40, 128)), premultiplied=True
    )
    renderer = SoftwareTexturedMeshRenderer()
    straight_image = renderer.render_scene(_scene((straight,), (_quad("straight"),)))
    correct_image = renderer.render_scene(
        _scene(
            (correct_premultiplied,),
            (_quad("premultiplied", blend_mode=PetMeshBlendMode.PREMULTIPLIED_ALPHA),),
        )
    )
    incorrect_image = renderer.render_scene(
        _scene(
            (incorrect_premultiplied,),
            (_quad("incorrect", blend_mode=PetMeshBlendMode.PREMULTIPLIED_ALPHA),),
        )
    )

    assert _raw_pixel(straight_image, 4, 4) == _raw_pixel(correct_image, 4, 4)
    assert _raw_pixel(incorrect_image, 4, 4) != _raw_pixel(straight_image, 4, 4)


def test_draw_order_and_clipping(qt_application: QApplication) -> None:
    del qt_application
    red = PetMeshTextureData("red", 1, 1, bytes((255, 0, 0, 255)))
    blue = PetMeshTextureData("blue", 1, 1, bytes((0, 0, 255, 255)))
    clip = (
        PetMeshPoint(0.0, 0.0),
        PetMeshPoint(4.0, 0.0),
        PetMeshPoint(4.0, 8.0),
        PetMeshPoint(0.0, 8.0),
    )
    image = SoftwareTexturedMeshRenderer().render_scene(
        _scene(
            (red, blue),
            (
                _quad("blue", draw_order=20, clip=clip),
                _quad("red", draw_order=10),
            ),
        )
    )

    assert image.pixelColor(2, 4).blue() == 255
    assert image.pixelColor(6, 4).red() == 255


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_dpi_scales_pixels_but_preserves_logical_ground_baseline(
    qt_application: QApplication,
    scale: float,
) -> None:
    del qt_application
    scene = generate_mesh_spike_scene(device_pixel_ratio=scale)
    image = SoftwareTexturedMeshRenderer().render_scene(scene)

    assert image.width() == round(160 * scale)
    assert image.height() == round(180 * scale)
    assert scene.foot_baseline_y / scale == 160.0


def test_close_is_idempotent_and_safe_renderer_falls_back(
    qt_application: QApplication,
) -> None:
    del qt_application
    software = SoftwareTexturedMeshRenderer()
    software.close()
    software.close()
    with pytest.raises(MeshSpikeError):
        software.render_scene(generate_mesh_spike_scene())

    safe = SafePetRenderer(SoftwareMeshPetRenderer())
    safe.initialize(Size(161, 180))

    assert safe.using_placeholder is True
    safe.close()
    safe.close()


def test_opengl_rejects_cross_thread_context_work(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = OffscreenOpenGLMeshRenderer()
    observed: list[MeshSpikeSafeCode] = []

    def initialize_from_worker() -> None:
        try:
            renderer.initialize()
        except MeshSpikeError as error:
            observed.append(error.code)

    worker = threading.Thread(target=initialize_from_worker)
    worker.start()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert observed == [MeshSpikeSafeCode.OPENGL_WRONG_THREAD]
    renderer.close()
    renderer.close()


def test_opengl_adapter_can_fall_back_before_context_creation(
    qt_application: QApplication,
) -> None:
    del qt_application
    safe = SafePetRenderer(OffscreenOpenGLMeshPetRenderer())

    safe.initialize(Size(160, 181))

    assert safe.using_placeholder is True
    safe.close()
