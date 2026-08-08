"""Explicit Windows smoke for the reusable OpenGL pet mesh backend."""

from __future__ import annotations

import json
import os
import random
import time

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ.pop("QT_QPA_FONTDIR", None)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.pet_animation import PetAnimationConfig
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
from sjtuclaw.application.pet_state import PetMotionState
from sjtuclaw.presentation.qt.pet_mesh_opengl_renderer import (
    OpenGLMeshError,
    OpenGLMeshFaultController,
    OpenGLMeshFaultPoint,
    OpenGLMeshPetRenderer,
    OpenGLMeshSafeCode,
    OpenGLTexturedMeshBackend,
)
from sjtuclaw.presentation.qt.pet_mesh_spike import (
    SoftwareTexturedMeshRenderer,
    generate_mesh_spike_scene,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow

_WHITE = PetMeshColor()


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _quad(
    texture_id: str,
    *,
    uvs: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ),
    color: PetMeshColor = _WHITE,
    blend: PetMeshBlendMode = PetMeshBlendMode.STRAIGHT_ALPHA,
    order: int = 0,
    clip: tuple[PetMeshPoint, ...] | None = None,
) -> PetMeshDrawCommand:
    positions = ((0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0))
    return PetMeshDrawCommand(
        texture_id,
        tuple(
            PetMeshVertex(PetMeshPoint(*position), *uv, color)
            for position, uv in zip(positions, uvs, strict=True)
        ),
        (0, 1, 2, 0, 2, 3),
        order,
        blend,
        clip,
    )


def _scene(
    textures: tuple[PetMeshTextureData, ...],
    commands: tuple[PetMeshDrawCommand, ...],
) -> PetMeshScene:
    return PetMeshScene(8, 8, 7.0, textures, commands)


def _render(scene: PetMeshScene, *, dpr: float = 1.0) -> tuple[QImage, object]:
    backend = OpenGLTexturedMeshBackend(scene, device_pixel_ratio=dpr)
    try:
        backend.initialize(Size(scene.width, scene.height))
        return backend.render_scene(), backend.metrics
    finally:
        backend.close()


def _pixel_contracts() -> dict[str, bool]:
    orientation = PetMeshTextureData(
        "orientation",
        2,
        2,
        bytes(
            (
                255, 0, 0, 255,
                0, 255, 0, 255,
                0, 0, 255, 255,
                255, 255, 255, 255,
            )
        ),
    )
    image, _ = _render(_scene((orientation,), (_quad("orientation"),)))
    uv_top_left = (
        image.pixelColor(1, 1).red() > 240
        and image.pixelColor(6, 1).green() > 240
        and image.pixelColor(1, 6).blue() > 240
    )

    rotated = PetMeshTextureData(
        "rotated",
        2,
        2,
        bytes(
            (
                0, 0, 255, 255,
                255, 0, 0, 255,
                255, 255, 255, 255,
                0, 255, 0, 255,
            )
        ),
    )
    rotated_uvs = ((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    rotated_image, _ = _render(
        _scene((rotated,), (_quad("rotated", uvs=rotated_uvs),))
    )
    rotated_uv = all(
        image.pixelColor(x, y) == rotated_image.pixelColor(x, y)
        for x, y in ((1, 1), (6, 1), (1, 6), (6, 6))
    )

    straight = PetMeshTextureData("straight", 1, 1, bytes((200, 80, 40, 128)))
    premultiplied = PetMeshTextureData(
        "premultiplied", 1, 1, bytes((100, 40, 20, 128)), True
    )
    straight_image, _ = _render(_scene((straight,), (_quad("straight"),)))
    premultiplied_image, _ = _render(
        _scene(
            (premultiplied,),
            (_quad("premultiplied", blend=PetMeshBlendMode.PREMULTIPLIED_ALPHA),),
        )
    )
    straight_color = straight_image.pixelColor(4, 4)
    premultiplied_color = premultiplied_image.pixelColor(4, 4)
    straight_channels = (
        straight_color.red(),
        straight_color.green(),
        straight_color.blue(),
        straight_color.alpha(),
    )
    premultiplied_channels = (
        premultiplied_color.red(),
        premultiplied_color.green(),
        premultiplied_color.blue(),
        premultiplied_color.alpha(),
    )
    alpha_conventions = all(
        abs(straight_channel - premultiplied_channel) <= 1
        for straight_channel, premultiplied_channel in zip(
            straight_channels,
            premultiplied_channels,
            strict=True,
        )
    )

    red = PetMeshTextureData("red", 1, 1, bytes((255, 0, 0, 255)))
    blue = PetMeshTextureData("blue", 1, 1, bytes((0, 0, 255, 255)))
    clipped_blue = _quad(
        "blue",
        order=20,
        clip=(PetMeshPoint(0, 0), PetMeshPoint(8, 0), PetMeshPoint(0, 8)),
    )
    ordered, _ = _render(
        _scene((red, blue), (clipped_blue, _quad("red", order=10)))
    )
    stencil_clip = (
        ordered.pixelColor(1, 1).blue() == 255
        and ordered.pixelColor(7, 7).red() == 255
    )
    draw_order = ordered.pixelColor(1, 1).blue() == 255

    tinted, _ = _render(
        _scene(
            (red,),
            (_quad("red", color=PetMeshColor(64, 255, 255, 255)),),
        )
    )
    vertex_color = 55 <= tinted.pixelColor(4, 4).red() <= 70

    software = SoftwareTexturedMeshRenderer()
    try:
        reference = software.render_scene(_scene((orientation,), (_quad("orientation"),)))
        software_reference = all(
            image.pixelColor(x, y) == reference.pixelColor(x, y)
            for x, y in ((1, 1), (6, 1), (1, 6), (6, 6))
        )
    finally:
        software.close()
    return {
        "uv_top_left": uv_top_left,
        "rotated_uv": rotated_uv,
        "alpha_conventions": alpha_conventions,
        "vertex_color": vertex_color,
        "draw_order": draw_order,
        "stencil_clip": stencil_clip,
        "software_reference": software_reference,
    }


def _dpi_contracts(
    scene: PetMeshScene,
) -> tuple[dict[str, list[int]], bool, bool]:
    sizes: dict[str, list[int]] = {}
    baseline_stable = True
    reference_bounds: tuple[float, float, float, float] | None = None
    bounds_stable = True
    for dpr in (1.0, 1.25, 1.5, 2.0):
        image, _ = _render(scene, dpr=dpr)
        sizes[str(dpr)] = [image.width(), image.height()]
        baseline_stable = baseline_stable and scene.foot_baseline_y == 160.0
        opaque_points = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        ]
        logical_bounds = (
            min(point[0] for point in opaque_points) / dpr,
            min(point[1] for point in opaque_points) / dpr,
            max(point[0] for point in opaque_points) / dpr,
            max(point[1] for point in opaque_points) / dpr,
        )
        if reference_bounds is None:
            reference_bounds = logical_bounds
        else:
            bounds_stable = bounds_stable and all(
                abs(observed - expected) <= 1.0
                for observed, expected in zip(
                    logical_bounds,
                    reference_bounds,
                    strict=True,
                )
            )
    return sizes, baseline_stable, bounds_stable


def _window_contract(app: QApplication, scene: PetMeshScene) -> dict[str, bool]:
    clock = _Clock()
    backend = OpenGLTexturedMeshBackend(scene)
    renderer = OpenGLMeshPetRenderer(scene, backend=backend)
    window = PetWindow(
        always_on_top=False,
        renderer=renderer,
        clock=clock,
        rng=random.Random(17),
        animation_config=PetAnimationConfig(
            maximum_delta_seconds=0.1,
            random_action_interval_min_seconds=100.0,
            random_action_interval_max_seconds=100.0,
        ),
    )
    observed: dict[str, bool] = {}
    try:
        window.show()
        app.processEvents()
        window.repaint()
        app.processEvents()
        capture = window.grab().toImage()
        transparent_corner = capture.pixelColor(0, 0).alpha() == 0
        visible_mesh = capture.pixelColor(80, 80).alpha() > 0
        window.toggle_paused()
        paused = (
            not window.physics_timer.isActive()
            or window.lifecycle_state.value == "paused"
        )
        window.toggle_paused()
        center = window.rect().center()
        QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=center)
        falling = window.motion_state is PetMotionState.FALLING
        for _ in range(30):
            clock.advance(0.1)
            window.physics_timer.timeout.emit()
            if window.motion_state is PetMotionState.IDLE:
                break
        landed = window.motion_state is PetMotionState.IDLE
        observed.update(
            {
                "transparent_corner": transparent_corner,
                "visible_mesh": visible_mesh,
                "pause_resume": paused,
                "drag_to_falling": falling,
                "landing_to_idle": landed,
            }
        )
    finally:
        window.request_safe_exit()
        window.complete_safe_close()
        app.processEvents()
        observed["timer_stopped"] = not window.physics_timer.isActive()
        observed["renderer_closed"] = backend.closed
    return observed


def _fault_contracts(scene: PetMeshScene) -> dict[str, bool]:
    observed: dict[str, bool] = {}
    initialization_faults = (
        (
            OpenGLMeshFaultPoint.CONTEXT_CREATE,
            OpenGLMeshSafeCode.INITIALIZATION_FAILED,
        ),
        (OpenGLMeshFaultPoint.SHADER_CREATE, OpenGLMeshSafeCode.SHADER_FAILED),
        (
            OpenGLMeshFaultPoint.SCENE_UPLOAD,
            OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED,
        ),
    )
    for point, expected_code in initialization_faults:
        controller = OpenGLMeshFaultController()
        controller.arm(point)
        backend = OpenGLTexturedMeshBackend(scene, fault_controller=controller)
        try:
            backend.initialize(Size(160, 180))
        except OpenGLMeshError as error:
            observed[point.value] = error.code is expected_code
        else:
            observed[point.value] = False
        finally:
            backend.close()

    controller = OpenGLMeshFaultController()
    backend = OpenGLTexturedMeshBackend(scene, fault_controller=controller)
    backend.initialize(Size(160, 180))
    reference = backend.render_scene()
    controller.arm(OpenGLMeshFaultPoint.SCENE_UPLOAD)
    try:
        backend.set_scene(generate_mesh_spike_scene(premultiplied_front=True))
    except OpenGLMeshError as error:
        replacement_failed = error.code is OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED
    else:
        replacement_failed = False
    retained = backend.render_scene()
    observed["transactional_scene_replacement"] = (
        replacement_failed
        and retained.pixelColor(80, 80) == reference.pixelColor(80, 80)
    )

    controller.arm(OpenGLMeshFaultPoint.VIEWPORT_CREATE)
    try:
        backend.set_device_pixel_ratio(1.25)
    except OpenGLMeshError as error:
        viewport_failed = error.code is OpenGLMeshSafeCode.VIEWPORT_FAILED
    else:
        viewport_failed = False
    observed["transactional_viewport_replacement"] = (
        viewport_failed and backend.render_scene().size().toTuple() == (160, 180)
    )

    for point, expected_code in (
        (OpenGLMeshFaultPoint.CONTEXT_CURRENT, OpenGLMeshSafeCode.CONTEXT_LOST),
        (OpenGLMeshFaultPoint.READBACK, OpenGLMeshSafeCode.READBACK_FAILED),
    ):
        controller.arm(point)
        try:
            backend.render_scene()
        except OpenGLMeshError as error:
            observed[point.value] = error.code is expected_code
        else:
            observed[point.value] = False
        observed[f"{point.value}_recovered"] = not backend.render_scene().isNull()
    backend.close()
    backend.close()
    return observed


def main() -> int:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    scene = generate_mesh_spike_scene()
    pixel = _pixel_contracts()
    dpi_sizes, logical_baseline_stable, dpi_bounds_stable = _dpi_contracts(scene)
    window = _window_contract(app, scene)
    faults = _fault_contracts(scene)

    backend = OpenGLTexturedMeshBackend(scene)
    backend.initialize(Size(160, 180))
    backend.initialize(Size(160, 180))
    backend.render_scene()
    timer_intervals_ms: list[float] = []
    last_timer_tick = time.perf_counter_ns()

    def record_timer_tick() -> None:
        nonlocal last_timer_tick
        current = time.perf_counter_ns()
        timer_intervals_ms.append((current - last_timer_tick) / 1_000_000.0)
        last_timer_tick = current

    gui_timer = QTimer()
    gui_timer.setInterval(16)
    gui_timer.timeout.connect(record_timer_tick)
    gui_timer.start()
    started = time.perf_counter_ns()
    for index in range(1000):
        backend.render_scene()
        if index % 10 == 0:
            app.processEvents()
    gui_timer.stop()
    benchmark_elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    uploads_before_replace = (
        backend.metrics.texture_upload_count,
        backend.metrics.mesh_upload_count,
    )
    for replacement_index in range(20):
        backend.set_scene(
            generate_mesh_spike_scene(
                premultiplied_front=replacement_index % 2 == 0
            )
        )
        backend.render_scene()
    for replacement_ratio in (1.25, 1.5, 2.0, 1.0):
        backend.set_device_pixel_ratio(replacement_ratio)
        backend.render_scene()
    metrics = backend.metrics
    persistent_uploads = uploads_before_replace == (
        len(scene.textures),
        len(scene.draw_commands) + sum(
            command.clip_polygon is not None for command in scene.draw_commands
        ),
    )
    backend.close()
    backend.close()

    lifecycle_started = time.perf_counter_ns()
    for _ in range(50):
        cycle = OpenGLTexturedMeshBackend(scene)
        cycle.initialize(Size(160, 180))
        cycle.render_scene()
        cycle.pause()
        cycle.resume()
        cycle.close()
        cycle.close()
    lifecycle_ms = (time.perf_counter_ns() - lifecycle_started) / 1_000_000.0

    passed = (
        all(pixel.values())
        and all(window.values())
        and all(faults.values())
        and logical_baseline_stable
        and dpi_bounds_stable
    )
    result = {
        "schema_version": 1,
        "qt_pet_opengl_backend_smoke": passed,
        "pixel_contracts": pixel,
        "dpi": {
            "sizes": dpi_sizes,
            "logical_baseline_stable": logical_baseline_stable,
            "logical_bounds_stable": dpi_bounds_stable,
        },
        "window_contracts": window,
        "fault_contracts": faults,
        "warmed_frames": metrics.warmed_frame_count,
        "benchmark_elapsed_ms": round(benchmark_elapsed_ms, 3),
        "initialization_ms": round(metrics.initialization_milliseconds, 3),
        "first_frame_ms": round(metrics.first_frame_milliseconds, 3),
        "warmed_mean_ms": round(metrics.warmed_mean_milliseconds, 3),
        "warmed_p50_ms": round(metrics.warmed_p50_milliseconds, 3),
        "warmed_p95_ms": round(metrics.warmed_p95_milliseconds, 3),
        "warmed_max_ms": round(metrics.warmed_max_milliseconds, 3),
        "readback_mean_ms": round(metrics.readback_mean_milliseconds, 3),
        "gui_timer_sample_count": len(timer_intervals_ms),
        "gui_timer_mean_delay_ms": round(
            sum(timer_intervals_ms) / len(timer_intervals_ms), 3
        ) if timer_intervals_ms else 0.0,
        "gui_timer_max_delay_ms": round(max(timer_intervals_ms, default=0.0), 3),
        "meets_30_fps": metrics.meets_30_fps_budget,
        "meets_60_fps": metrics.meets_60_fps_budget,
        "persistent_uploads": persistent_uploads,
        "scene_replacements": metrics.scene_replacement_count,
        "framebuffer_replacements": metrics.framebuffer_replacement_count,
        "frame_readback_allocations": metrics.frame_readback_allocation_count,
        "lifecycle_cycles": 50,
        "lifecycle_elapsed_ms": round(lifecycle_ms, 3),
        "safe_code": "none" if passed else "pet_mesh_opengl_smoke_failed",
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
