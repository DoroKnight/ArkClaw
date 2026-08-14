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
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet_geometry import Point, Rect, Size
from arkclaw.application.pet_mesh_model import PetMeshTextureFilter
from arkclaw.application.pet_render_layout import (
    PetRenderLayout,
    PetRenderLayoutQuality,
    PetRenderSurfaceMode,
    RolePackRenderProfile,
)
from arkclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
)
from arkclaw.application.pet_role_pack import RolePackFraming
from arkclaw.application.pet_state import PetFacing
from arkclaw.application.spine38_runtime import (
    Spine38AnimationInfo,
    Spine38Bounds,
    Spine38Catalog,
    Spine38FrameError,
)
from arkclaw.infrastructure.spine38_native import (
    Spine38BlendMode,
    Spine38DrawCommand,
    Spine38Vertex,
)
from arkclaw.presentation.qt.pet_renderer import SafePetRenderer


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
        from arkclaw.application.pet_mesh_model import (
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
            round(transform.viewport.width),
            round(transform.viewport.height),
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
        self.viewport = Size(160, 180)
        self.render_scene_count = 0
        self.next_image: QImage | None = None

    def initialize(self, viewport: Size) -> None:
        self.viewport = viewport

    def set_viewport(self, viewport: Size) -> None:
        self.viewport = viewport

    def set_device_pixel_ratio(self, value: float) -> None:
        self.device_pixel_ratios.append(value)

    def set_scene(self, scene: Any) -> None:
        self.scenes.append(scene)

    def render_scene(self) -> QImage:
        self.render_scene_count += 1
        if self.next_image is not None:
            return self.next_image
        return QImage(
            round(self.viewport.width),
            round(self.viewport.height),
            QImage.Format.Format_RGBA8888_Premultiplied,
        )

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


def test_render_surface_returns_the_same_frame_drawn_with_one_backend_readback(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        _FakeRuntime(),
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )
    renderer.initialize(Size(160, 180))
    source = QImage(160, 180, QImage.Format.Format_RGBA8888)
    source.fill(0)
    source.setPixelColor(23, 31, QColor(10, 20, 30, 255))
    backends[0].next_image = source
    target = QImage(160, 180, QImage.Format.Format_RGBA8888)
    target.fill(0)
    painter = QPainter(target)

    rendered = renderer.render_surface(painter)
    painter.end()

    assert rendered is source
    assert target.pixelColor(23, 31) == source.pixelColor(23, 31)
    assert backends[0].render_scene_count == 1
    renderer.close()


def test_renderer_sets_relax_once_and_only_advances_time(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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
    assert backends[0].initial_scene.foot_baseline_y == pytest.approx(180.0)
    initial_vertices = backends[0].initial_scene.draw_commands[0].vertices
    assert min(vertex.position.y for vertex in initial_vertices) == pytest.approx(18.0)
    assert max(vertex.position.y for vertex in initial_vertices) == pytest.approx(180.0)
    assert renderer.foot_baseline_y == pytest.approx(180.0)
    renderer.close()


def test_renderer_propagates_real_dpr_filters_and_one_fixed_framing(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
        min_filter=PetMeshTextureFilter.NEAREST,
        mag_filter=PetMeshTextureFilter.LINEAR,
        framing=RolePackFraming(1.0, 3.0, 179.0),
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
    assert runtime.mesh_scene_transforms[0].foot_baseline_y == 179.0
    assert runtime.visible_bounds_calls == 0
    renderer.close()


def test_renderer_keeps_visible_frame_transform_after_initialization(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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
    assert min(vertex.position.y for vertex in updated_vertices) == pytest.approx(18.0)
    assert max(vertex.position.y for vertex in updated_vertices) == pytest.approx(180.0)
    renderer.close()


def test_relax_body_priority_transform_targets_full_height_and_foot_rows(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
        session_bounds=Spine38Bounds(-0.5, 0.0, 1.0, 2.0),
    )

    renderer.initialize(Size(160, 180))

    vertices = backends[0].initial_scene.draw_commands[0].vertices
    visible_top = min(vertex.position.y for vertex in vertices)
    visible_foot = max(vertex.position.y for vertex in vertices)
    assert visible_foot - visible_top == pytest.approx(162.0)
    assert 153.0 <= visible_foot - visible_top <= 171.0
    assert 178.0 <= visible_foot <= 180.0
    assert 0.0 <= 180.0 - visible_foot <= 2.0
    assert renderer.foot_baseline_y == pytest.approx(180.0)
    renderer.close()


def test_renderer_mirrors_scene_when_facing_changes(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )
    renderer.initialize(Size(160, 180))

    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.WALK_RIGHT,
            PetFacing.RIGHT,
            True,
            0.0,
        )
    )
    renderer.update(0.016)
    right_vertices = backends[0].scenes[-1].draw_commands[0].vertices

    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.WALK_LEFT,
            PetFacing.LEFT,
            True,
            0.0,
        )
    )
    renderer.update(0.016)
    left_vertices = backends[0].scenes[-1].draw_commands[0].vertices

    assert [vertex.position.x for vertex in left_vertices] == pytest.approx(
        [160.0 - vertex.position.x for vertex in right_vertices]
    )
    renderer.close()


def test_left_facing_is_applied_before_the_first_published_scene(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
    )
    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.SLEEP,
            PetFacing.LEFT,
            True,
            0.0,
        )
    )

    renderer.initialize(Size(160, 180))

    positions = [
        vertex.position.x
        for vertex in backends[0].initial_scene.draw_commands[0].vertices
    ]
    assert positions == pytest.approx([120.5, 39.5, 80.0])
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
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
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


@pytest.mark.parametrize(
    ("facing", "expected_surface", "expected_offset"),
    [
        (PetFacing.RIGHT, Rect(482.0, 905.0, 167.0, 148.0), Point(18.0, -66.0)),
        (PetFacing.LEFT, Rect(511.0, 905.0, 167.0, 148.0), Point(-11.0, -66.0)),
    ],
)
def test_sit_uses_full_sampled_surface_and_preserves_body_transform(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
    facing: PetFacing,
    expected_surface: Rect,
    expected_offset: Point,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    profile = RolePackRenderProfile(
        Spine38Bounds(
            -170.41197204589844,
            -1.9676189422607422,
            255.40875244140625,
            400.436185836792,
        ),
        {
            PetRendererAction.IDLE: Spine38Bounds(
                -170.41197204589844,
                -1.9676189422607422,
                255.40875244140625,
                400.436185836792,
            ),
            PetRendererAction.SITTING: Spine38Bounds(
                -278.8448486328125,
                -78.73991394042969,
                399.77774810791016,
                351.7436065673828,
            ),
        },
    )
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
        session_bounds=profile.body_bounds,
        render_profile=profile,
    )
    renderer.initialize(Size(160, 180))
    body_origin_y = runtime.mesh_scene_transforms[-1].origin_y

    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.SITTING, facing, True, 0.0
        )
    )
    sit = renderer.plan_layout(
        Rect(500.0, 839.0, 160.0, 180.0),
        Rect(0.0, 0.0, 1707.0, 1019.0),
        1.0,
        display=Rect(0.0, 0.0, 1707.0, 1067.0),
    )
    assert isinstance(sit, PetRenderLayout)
    assert sit.mode is PetRenderSurfaceMode.OVERFLOW
    assert sit.surface_rect == expected_surface
    assert sit.body_window_offset == expected_offset
    assert sit.resolved_body_position == Point(500.0, 839.0)
    assert sit.ground_correction == 0.0
    assert sit.effective_facing is facing
    assert sit.scale_multiplier == 1.0
    renderer.set_render_layout(sit)
    renderer.update(0.016)
    transform = runtime.mesh_scene_transforms[-1]
    assert transform.origin_y == pytest.approx(expected_offset.y + body_origin_y)
    assert transform.foot_baseline_y == pytest.approx(expected_offset.y + 180.0)
    assert backends[0].viewport == Size(167.0, 148.0)
    assert profile.body_bounds == Spine38Bounds(
        -170.41197204589844,
        -1.9676189422607422,
        255.40875244140625,
        400.436185836792,
    )

    renderer.close()


def test_special_overflow_expands_surface_without_moving_body_transform(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    profile = RolePackRenderProfile(
        Spine38Bounds(-0.5, 0.0, 1.0, 2.0),
        {PetRendererAction.SPECIAL: Spine38Bounds(-0.8, -0.01, 4.5, 3.2)},
    )
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
        session_bounds=profile.body_bounds,
        render_profile=profile,
    )
    renderer.initialize(Size(160, 180))
    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.SPECIAL, PetFacing.RIGHT, False, 0.0
        )
    )

    special = renderer.plan_layout(
        Rect(500.0, 700.0, 160.0, 180.0),
        Rect(0.0, 0.0, 1920.0, 880.0),
        1.0,
    )

    assert isinstance(special, PetRenderLayout)
    assert special.mode is PetRenderSurfaceMode.OVERFLOW
    assert special.ground_correction == 0.0
    renderer.set_render_layout(special)
    renderer.update(0.016)
    transform = runtime.mesh_scene_transforms[-1]
    assert transform.origin_y == pytest.approx(
        special.body_window_offset.y + 180.0
    )
    assert backends[0].viewport == Size(
        special.surface_rect.width,
        special.surface_rect.height,
    )
    assert backends[0].scenes[-1].width == round(special.surface_rect.width)
    renderer.close()


def test_real_schwarz_profile_plans_full_scale_at_both_desktop_edges(
    qt_application: QApplication,
    verified_texture_bytes: bytes,
) -> None:
    """Drive the real Schwarz Special envelope through the renderer planner.

    The profile uses the production Schwarz session bounds and the Special
    sampled bounds that project onto the documented real envelope
    (``Rect(-31.91, -546.04, 477.87, 741.90)`` at body anchor ``(80, 180)``,
    scale 1.0). Both desktop edges must stay ``FULL_SCALE`` with a minimal
    horizontal avoidance and no facing change.
    """

    del qt_application
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    runtime = _FakeRuntime()
    backends: list[_FakeBackend] = []
    profile = RolePackRenderProfile(
        Spine38Bounds(-80.0, 0.0, 160.0, 162.0),
        {
            PetRendererAction.IDLE: Spine38Bounds(-80.0, 0.0, 160.0, 162.0),
            PetRendererAction.SPECIAL: Spine38Bounds(
                -111.91,
                -15.86,
                477.87,
                741.90,
            ),
        },
    )
    renderer = module.Spine38PetRenderer(
        runtime,
        verified_texture_bytes,
        backend_factory=_backend_factory(backends),
        session_bounds=profile.body_bounds,
        render_profile=profile,
    )
    renderer.initialize(Size(160, 180))

    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.SPECIAL, PetFacing.RIGHT, False, 0.0
        )
    )
    left_edge = renderer.plan_layout(
        Rect(0.0, 700.0, 160.0, 180.0),
        workspace,
        1.0,
    )
    assert isinstance(left_edge, PetRenderLayout)
    assert left_edge.quality is PetRenderLayoutQuality.FULL_SCALE
    assert left_edge.scale_multiplier == 1.0
    assert left_edge.effective_facing is PetFacing.RIGHT
    assert left_edge.resolved_body_position == Point(32.0, 700.0)
    assert left_edge.mode is PetRenderSurfaceMode.OVERFLOW

    renderer.set_state(
        PetRendererActionRequest(
            PetRendererAction.SPECIAL, PetFacing.LEFT, False, 0.0
        )
    )
    right_edge = renderer.plan_layout(
        Rect(1760.0, 700.0, 160.0, 180.0),
        workspace,
        1.0,
    )
    assert isinstance(right_edge, PetRenderLayout)
    assert right_edge.quality is PetRenderLayoutQuality.FULL_SCALE
    assert right_edge.scale_multiplier == 1.0
    assert right_edge.effective_facing is PetFacing.LEFT
    assert right_edge.resolved_body_position == Point(1728.0, 700.0)
    assert right_edge.mode is PetRenderSurfaceMode.OVERFLOW

    renderer.close()
