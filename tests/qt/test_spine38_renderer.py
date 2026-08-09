"""Qt boundary tests for the opt-in Spine 3.8 renderer."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_mesh_model import PetMeshTextureFilter
from sjtuclaw.application.pet_renderer_model import PetRendererAction
from sjtuclaw.application.pet_role_pack import RolePackFraming
from sjtuclaw.application.spine38_runtime import (
    Spine38AnimationInfo,
    Spine38Bounds,
    Spine38Catalog,
    Spine38FrameError,
)
from sjtuclaw.infrastructure.spine38_native import (
    Spine38BlendMode,
    Spine38DrawCommand,
    Spine38Vertex,
)
from sjtuclaw.presentation.qt.pet_renderer import SafePetRenderer


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


@pytest.fixture
def verified_texture_bytes() -> bytes:
    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    image.fill(0x336699CC)
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, cast(bytes, "PNG"))
    buffer.close()
    data = encoded.data()
    assert isinstance(data, bytes)
    return data


class _FakeRuntime:
    def __init__(self, events: list[str] | None = None) -> None:
        self.catalog = Spine38Catalog((Spine38AnimationInfo("Relax", 3.2),))
        self.setup_bounds = Spine38Bounds(-0.5, 0.0, 1.0, 2.0)
        self.atlas_size = Size(2, 2)
        self.set_animation_calls: list[tuple[int, str, bool]] = []
        self.update_calls: list[float] = []
        self.visible_bounds_calls = 0
        self.initialization_events: list[str] = []
        self.mesh_scene_transforms: list[Any] = []
        self.close_count = 0
        self.fail_update = False
        self.fail_zero_delta_update = False
        self.fail_visible_bounds = False
        self.visible_bounds_values = [
            Spine38Bounds(-0.5, 0.0, 1.0, 2.0),
            Spine38Bounds(-10.0, -10.0, 20.0, 20.0),
        ]
        self._events = events

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        self.set_animation_calls.append((track, name, loop))
        self.initialization_events.append("set_animation")

    def update(self, delta_seconds: float) -> None:
        if self.fail_update:
            raise RuntimeError("sensitive-native-detail")
        if self.fail_zero_delta_update and delta_seconds == 0.0:
            raise Spine38FrameError
        self.update_calls.append(delta_seconds)
        self.initialization_events.append(f"update({delta_seconds})")

    def visible_bounds(self) -> Spine38Bounds:
        self.visible_bounds_calls += 1
        if self.fail_visible_bounds:
            raise Spine38FrameError
        self.initialization_events.append("visible_bounds")
        index = min(self.visible_bounds_calls - 1, len(self.visible_bounds_values) - 1)
        return self.visible_bounds_values[index]

    def draw_commands(self) -> tuple[Spine38DrawCommand, ...]:
        return (
            Spine38DrawCommand(
                vertices=(
                    Spine38Vertex(-0.5, 0.0, 0.0, 0.0, 255, 255, 255, 255),
                    Spine38Vertex(0.5, 0.0, 1.0, 0.0, 255, 255, 255, 255),
                    Spine38Vertex(0.0, 2.0, 0.5, 1.0, 255, 255, 255, 255),
                ),
                indices=(0, 1, 2),
                texture_page=0,
                blend_mode=Spine38BlendMode.NORMAL,
                draw_order=0,
            ),
        )

    def mesh_scene(self, transform: Any, texture: Any) -> Any:
        from sjtuclaw.application.pet_mesh_model import (
            PetMeshDrawCommand,
            PetMeshScene,
            PetMeshVertex,
        )

        self.mesh_scene_transforms.append(transform)
        self.initialization_events.append("mesh_scene")
        commands = tuple(
            PetMeshDrawCommand(
                texture_id=texture.texture_id,
                vertices=tuple(
                    PetMeshVertex(
                        transform.point(vertex.x, vertex.y),
                        vertex.u,
                        vertex.v,
                    )
                    for vertex in command.vertices
                ),
                triangle_indices=command.indices,
                draw_order=command.draw_order,
            )
            for command in self.draw_commands()
        )
        return PetMeshScene(
            160,
            180,
            transform.foot_baseline_y,
            (texture,),
            commands,
        )

    def close(self) -> None:
        self.close_count += 1
        if self._events is not None:
            self._events.append("runtime.close")


class _FakeBackend:
    def __init__(self, scene: Any, events: list[str] | None = None) -> None:
        self.initial_scene = scene
        self.scenes: list[Any] = []
        self.closed = False
        self._events = events
        self.device_pixel_ratios: list[float] = []

    def initialize(self, viewport: Size) -> None:
        assert viewport == Size(160, 180)

    def set_viewport(self, viewport: Size) -> None:
        assert viewport == Size(160, 180)

    def set_device_pixel_ratio(self, value: float) -> None:
        self.device_pixel_ratios.append(value)

    def set_scene(self, scene: Any) -> None:
        self.scenes.append(scene)

    def render_scene(self) -> QImage:
        return QImage(160, 180, QImage.Format.Format_RGBA8888_Premultiplied)

    def pause(self) -> None:
        return

    def resume(self) -> None:
        return

    def close(self) -> None:
        self.closed = True
        if self._events is not None:
            self._events.append("backend.close")


def _backend_factory(
    captured: list[_FakeBackend],
    events: list[str] | None = None,
) -> Callable[[Any], _FakeBackend]:
    def create(scene: Any) -> _FakeBackend:
        backend = _FakeBackend(scene, events)
        captured.append(backend)
        return backend

    return create


def test_renderer_sets_relax_once_and_only_advances_time(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )

    renderer.initialize(Size(160, 180))
    renderer.initialize(Size(160, 180))
    renderer.update(0.016)
    renderer.update(0.016)

    assert runtime.set_animation_calls == [(0, "Relax", True)]
    assert runtime.update_calls == [0.0, 0.016, 0.016]
    assert runtime.visible_bounds_calls == 1
    assert runtime.initialization_events[:4] == [
        "set_animation",
        "update(0.0)",
        "visible_bounds",
        "mesh_scene",
    ]
    assert len(backends) == 1
    assert len(backends[0].scenes) == 2
    assert backends[0].initial_scene.foot_baseline_y == pytest.approx(176.0)
    initial_vertices = backends[0].initial_scene.draw_commands[0].vertices
    assert min(vertex.position.y for vertex in initial_vertices) == pytest.approx(4.0)
    assert max(vertex.position.y for vertex in initial_vertices) == pytest.approx(176.0)
    assert renderer.foot_baseline_y == pytest.approx(176.0)
    renderer.close()


def test_renderer_propagates_real_dpr_filters_and_one_fixed_framing(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
        min_filter=PetMeshTextureFilter.NEAREST,
        mag_filter=PetMeshTextureFilter.LINEAR,
        framing=RolePackFraming(0.9, 3.0, 175.0),
        session_bounds=Spine38Bounds(-0.5, 0.0, 1.0, 2.0),
    )

    renderer.set_device_pixel_ratio(1.5)
    renderer.initialize(Size(160, 180))
    renderer.set_device_pixel_ratio(2.0)
    renderer.update(0.016)

    backend = backends[0]
    texture = backend.initial_scene.textures[0]
    assert backend.device_pixel_ratios == [1.5, 2.0]
    assert texture.min_filter is PetMeshTextureFilter.NEAREST
    assert texture.mag_filter is PetMeshTextureFilter.LINEAR
    assert all(
        transform is runtime.mesh_scene_transforms[0]
        for transform in runtime.mesh_scene_transforms
    )
    assert runtime.mesh_scene_transforms[0].foot_baseline_y == 175.0
    assert runtime.visible_bounds_calls == 0
    renderer.close()


def test_renderer_keeps_visible_frame_transform_after_initialization(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )

    renderer.initialize(Size(160, 180))
    renderer.update(0.016)
    renderer.update(0.016)

    assert runtime.visible_bounds_calls == 1
    assert len(runtime.mesh_scene_transforms) == 3
    assert all(
        transform is runtime.mesh_scene_transforms[0]
        for transform in runtime.mesh_scene_transforms
    )
    updated_vertices = backends[0].scenes[-1].draw_commands[0].vertices
    assert min(vertex.position.y for vertex in updated_vertices) == pytest.approx(4.0)
    assert max(vertex.position.y for vertex in updated_vertices) == pytest.approx(176.0)
    renderer.close()


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("zero_delta", "MESH_INVALID"),
        ("visible_bounds", "MESH_INVALID"),
    ],
)
def test_renderer_initialization_visible_frame_failure_publishes_no_scene(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
    failure: str,
    expected_code: str,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    runtime.fail_zero_delta_update = failure == "zero_delta"
    runtime.fail_visible_bounds = failure == "visible_bounds"
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )

    with pytest.raises(module.Spine38RendererError) as caught:
        renderer.initialize(Size(160, 180))

    assert caught.value.code is getattr(
        module.Spine38RendererCode,
        expected_code,
    )
    assert backends == []
    renderer.close()


def test_renderer_decodes_rgba_and_requires_exact_atlas_dimensions(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )

    renderer.initialize(Size(160, 180))

    texture = backends[0].initial_scene.textures[0]
    assert (texture.width, texture.height) == (2, 2)
    assert len(texture.rgba_bytes) == 16
    renderer.close()

    mismatch = _FakeRuntime()
    mismatch.atlas_size = Size(1, 2)
    bad_renderer = module.Spine38PetRenderer(
        mismatch,
        verified_texture_bytes,
        backend_factory=_backend_factory([]),
    )
    with pytest.raises(module.Spine38RendererError) as caught:
        bad_renderer.initialize(Size(160, 180))
    assert caught.value.code is module.Spine38RendererCode.TEXTURE_INVALID
    bad_renderer.close()


def test_renderer_redacts_unexpected_catalog_failure(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()

    def fail_catalog(name: str) -> None:
        del name
        raise RuntimeError("sensitive-catalog-detail")

    runtime.catalog = cast(
        Any,
        SimpleNamespace(require_animation=fail_catalog),
    )
    renderer = module.Spine38PetRenderer(runtime, verified_texture_bytes)

    with pytest.raises(module.Spine38RendererError) as caught:
        renderer.initialize(Size(160, 180))

    assert caught.value.code is module.Spine38RendererCode.CATALOG_INVALID
    assert str(caught.value) == "The Spine pet renderer failed safely."
    assert "sensitive" not in str(caught.value)
    renderer.close()


def test_renderer_failure_is_contained_and_close_order_is_idempotent(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    events: list[str] = []
    runtime = _FakeRuntime(events)
    asset_owner = SimpleNamespace(
        close=lambda: events.append("assets.close"),
    )
    backends: list[_FakeBackend] = []
    safe = SafePetRenderer(
        module.Spine38PetRenderer(
            runtime,
            verified_texture_bytes,
            asset_owner=asset_owner,
            backend_factory=_backend_factory(backends, events),
        )
    )
    safe.initialize(Size(160, 180))
    runtime.fail_update = True

    safe.update(0.016)
    safe.close()
    safe.close()

    assert safe.using_placeholder is True
    assert events == ["backend.close", "runtime.close", "assets.close"]
    assert runtime.close_count == 1


def test_renderer_advertises_only_idle_without_completion_metadata(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("sjtuclaw.presentation.qt.spine38_renderer")
    renderer = module.Spine38PetRenderer(_FakeRuntime(), verified_texture_bytes)

    idle = renderer.animation_capability(PetRendererAction.IDLE)
    walking = renderer.animation_capability(PetRendererAction.WALK_LEFT)

    assert idle.animation_supported is True
    assert idle.loop is True
    assert idle.duration_seconds is None
    assert idle.fallback_animation is PetRendererAction.IDLE
    assert walking.animation_supported is False
    assert walking.duration_seconds is None
    assert walking.fallback_animation is PetRendererAction.IDLE
    renderer.close()
