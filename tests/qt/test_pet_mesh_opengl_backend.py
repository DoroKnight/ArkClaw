"""Lifecycle and real-driver tests for the reusable OpenGL mesh backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

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
    PetMeshTextureFilter,
    PetMeshVertex,
)
from sjtuclaw.presentation.qt.pet_mesh_opengl_renderer import (
    OpenGLMeshError,
    OpenGLMeshPetRenderer,
    OpenGLMeshSafeCode,
    OpenGLTexturedMeshBackend,
    physical_viewport_size,
    qt_texture_filter,
)
from sjtuclaw.presentation.qt.pet_mesh_spike import (
    SoftwareTexturedMeshRenderer,
    generate_mesh_spike_scene,
)
from sjtuclaw.presentation.qt.pet_renderer import SafePetRenderer

_WHITE = PetMeshColor()


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (1.0, (161, 181)),
        (1.25, (202, 227)),
        (1.5, (242, 272)),
        (2.0, (322, 362)),
    ],
)
def test_physical_viewport_uses_ceil_for_real_dpr(
    ratio: float,
    expected: tuple[int, int],
) -> None:
    assert physical_viewport_size(Size(161, 181), ratio) == expected


def test_texture_filters_are_independent_and_default_to_linear() -> None:
    texture = PetMeshTextureData("page", 1, 1, b"\xff\xff\xff\xff")

    assert texture.min_filter is PetMeshTextureFilter.LINEAR
    assert texture.mag_filter is PetMeshTextureFilter.LINEAR
    assert qt_texture_filter(PetMeshTextureFilter.NEAREST).name == "Nearest"
    assert qt_texture_filter(PetMeshTextureFilter.LINEAR).name == "Linear"


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


class _FakeImageBackend:
    def __init__(self, *, fail_initialize: bool = False) -> None:
        self.fail_initialize = fail_initialize
        self.closed = False
        self.calls: list[str] = []
        self.scene: PetMeshScene | None = None

    def initialize(self, viewport: Size) -> None:
        del viewport
        self.calls.append("initialize")
        if self.fail_initialize:
            raise OpenGLMeshError(OpenGLMeshSafeCode.INITIALIZATION_FAILED)

    def set_viewport(self, viewport: Size) -> None:
        del viewport
        self.calls.append("set_viewport")

    def set_scene(self, scene: PetMeshScene) -> None:
        self.scene = scene
        self.calls.append("set_scene")

    def render_scene(self) -> QImage:
        self.calls.append("render_scene")
        return QImage(160, 180, QImage.Format.Format_RGBA8888_Premultiplied)

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True


def test_adapter_lifecycle_uses_injected_generic_backend() -> None:
    scene = generate_mesh_spike_scene()
    backend = _FakeImageBackend()
    renderer = OpenGLMeshPetRenderer(scene, backend=backend)

    renderer.initialize(Size(160, 180))
    renderer.set_viewport(Size(200, 225))
    renderer.set_scene(scene)
    renderer.pause()
    renderer.pause()
    renderer.resume()
    renderer.resume()
    renderer.close()
    renderer.close()

    assert backend.calls == [
        "initialize",
        "set_viewport",
        "set_scene",
        "pause",
        "resume",
        "close",
    ]
    assert backend.closed is True


def test_safe_renderer_falls_back_when_backend_initialization_fails() -> None:
    scene = generate_mesh_spike_scene()
    backend = _FakeImageBackend(fail_initialize=True)
    safe = SafePetRenderer(OpenGLMeshPetRenderer(scene, backend=backend))

    safe.initialize(Size(160, 180))

    assert safe.using_placeholder is True
    assert backend.closed is True
    safe.close()


def test_backend_rejects_cross_thread_context_work(
    qt_application: QApplication,
) -> None:
    del qt_application
    backend = OpenGLTexturedMeshBackend(generate_mesh_spike_scene())
    observed: list[OpenGLMeshSafeCode] = []

    def initialize_from_worker() -> None:
        try:
            backend.initialize(Size(160, 180))
        except OpenGLMeshError as error:
            observed.append(error.code)

    worker = threading.Thread(target=initialize_from_worker)
    worker.start()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert observed == [OpenGLMeshSafeCode.WRONG_THREAD]
    backend.close()


def test_backend_errors_are_fixed_and_do_not_expose_driver_details() -> None:
    error = OpenGLMeshError(OpenGLMeshSafeCode.CONTEXT_LOST)

    assert error.code is OpenGLMeshSafeCode.CONTEXT_LOST
    assert str(error) == "The OpenGL pet renderer failed safely."
    assert "context" not in str(error).lower()


def _blend_quad(
    texture_id: str,
    blend_mode: PetMeshBlendMode,
    draw_order: int,
    color: PetMeshColor = _WHITE,
) -> PetMeshDrawCommand:
    return PetMeshDrawCommand(
        texture_id=texture_id,
        vertices=(
            PetMeshVertex(PetMeshPoint(0.0, 0.0), 0.0, 0.0, color),
            PetMeshVertex(PetMeshPoint(8.0, 0.0), 1.0, 0.0, color),
            PetMeshVertex(PetMeshPoint(8.0, 8.0), 1.0, 1.0, color),
            PetMeshVertex(PetMeshPoint(0.0, 8.0), 0.0, 1.0, color),
        ),
        triangle_indices=(0, 1, 2, 0, 2, 3),
        draw_order=draw_order,
        blend_mode=blend_mode,
    )


def _render_blend_probe() -> dict[str, list[int]]:
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    background = PetMeshTextureData(
        "background",
        1,
        1,
        bytes((40, 80, 120, 255)),
    )
    straight = PetMeshTextureData(
        "straight",
        1,
        1,
        bytes((200, 100, 50, 128)),
    )
    premultiplied = PetMeshTextureData(
        "premultiplied",
        1,
        1,
        bytes((100, 50, 25, 128)),
        premultiplied=True,
    )
    observed: dict[str, list[int]] = {}
    cases = (
        (PetMeshBlendMode.NORMAL_STRAIGHT, straight),
        (PetMeshBlendMode.NORMAL_PREMULTIPLIED, premultiplied),
        (PetMeshBlendMode.ADDITIVE, straight),
        (PetMeshBlendMode.MULTIPLY, straight),
        (PetMeshBlendMode.SCREEN, straight),
    )
    for blend_mode, foreground in cases:
        scene = PetMeshScene(
            width=8,
            height=8,
            foot_baseline_y=7.0,
            textures=(background, foreground),
            draw_commands=(
                _blend_quad("background", PetMeshBlendMode.NORMAL_STRAIGHT, 0),
                _blend_quad(foreground.texture_id, blend_mode, 1),
            ),
        )
        backend = OpenGLTexturedMeshBackend(scene)
        try:
            backend.initialize(Size(8, 8))
            color = backend.render_scene().pixelColor(4, 4)
            observed[blend_mode.name] = [
                color.red(),
                color.green(),
                color.blue(),
                color.alpha(),
            ]
        finally:
            backend.close()
    faded_premultiplied_scene = PetMeshScene(
        width=8,
        height=8,
        foot_baseline_y=7.0,
        textures=(background, premultiplied),
        draw_commands=(
            _blend_quad("background", PetMeshBlendMode.NORMAL_STRAIGHT, 0),
            _blend_quad(
                "premultiplied",
                PetMeshBlendMode.NORMAL_PREMULTIPLIED,
                1,
                PetMeshColor(alpha=128),
            ),
        ),
    )
    backend = OpenGLTexturedMeshBackend(faded_premultiplied_scene)
    software = SoftwareTexturedMeshRenderer()
    try:
        backend.initialize(Size(8, 8))
        gpu_color = backend.render_scene().pixelColor(4, 4)
        software_color = software.render_scene(
            faded_premultiplied_scene
        ).pixelColor(4, 4)
        observed["PMA_VERTEX_ALPHA_GPU"] = [
            gpu_color.red(),
            gpu_color.green(),
            gpu_color.blue(),
            gpu_color.alpha(),
        ]
        observed["PMA_VERTEX_ALPHA_SOFTWARE"] = [
            software_color.red(),
            software_color.green(),
            software_color.blue(),
            software_color.alpha(),
        ]
    finally:
        software.close()
        backend.close()
    del application
    return observed


def test_real_backend_applies_renderer_neutral_blend_modes_per_command() -> None:
    repository = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    environment.pop("QT_QPA_FONTDIR", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(repository / "src"), environment.get("PYTHONPATH", "")),
        )
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--blend-probe"],
        cwd=repository,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    observed = json.loads(completed.stdout)
    pma_gpu = observed.pop("PMA_VERTEX_ALPHA_GPU")
    pma_software = observed.pop("PMA_VERTEX_ALPHA_SOFTWARE")
    assert all(
        abs(actual - reference) <= 2
        for actual, reference in zip(pma_gpu, pma_software, strict=True)
    )
    expected = {
        "NORMAL_STRAIGHT": [120, 90, 85, 255],
        "NORMAL_PREMULTIPLIED": [120, 90, 85, 255],
        "ADDITIVE": [140, 130, 145, 255],
        "MULTIPLY": [51, 71, 83, 255],
        "SCREEN": [209, 149, 146, 255],
    }
    assert observed.keys() == expected.keys()
    for mode, expected_rgba in expected.items():
        assert all(
            abs(actual - wanted) <= 2
            for actual, wanted in zip(
                observed[mode],
                expected_rgba,
                strict=True,
            )
        ), mode


def test_real_windows_backend_smoke_and_metrics() -> None:
    repository = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    environment.pop("QT_QPA_FONTDIR", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(repository / "scripts" / "qt_pet_opengl_backend_smoke.py"),
        ],
        cwd=repository,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["qt_pet_opengl_backend_smoke"] is True
    assert result["safe_code"] == "none"
    assert all(result["pixel_contracts"].values())
    assert all(result["window_contracts"].values())
    assert all(result["fault_contracts"].values())
    assert result["warmed_frames"] >= 1000
    assert result["lifecycle_cycles"] == 50
    assert result["persistent_uploads"] is True
    assert result["scene_replacements"] == 20
    assert result["framebuffer_replacements"] == 4
    assert result["dpi"]["sizes"] == {
        "1.0": [160, 180],
        "1.25": [200, 225],
        "1.5": [240, 270],
        "2.0": [320, 360],
    }
    assert result["dpi"]["logical_baseline_stable"] is True
    assert result["dpi"]["logical_bounds_stable"] is True


if __name__ == "__main__" and sys.argv[1:] == ["--blend-probe"]:
    print(json.dumps(_render_blend_probe(), sort_keys=True))
