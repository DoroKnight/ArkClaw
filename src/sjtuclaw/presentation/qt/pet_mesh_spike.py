"""Programmatic textured-mesh renderer spikes; never a production default."""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from enum import StrEnum
from threading import get_ident

from PySide6.QtCore import QThread
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QOffscreenSurface,
    QOpenGLContext,
    QOpenGLFunctions,
    QPainter,
    QSurfaceFormat,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from shiboken6 import VoidPtr

from sjtuclaw.application.pet_animation import PetRenderFrame
from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_mesh_model import (
    PetMeshBlendMode,
    PetMeshColor,
    PetMeshDrawCommand,
    PetMeshPoint,
    PetMeshScene,
    PetMeshTextureData,
    PetMeshVertex,
    sorted_draw_commands,
    validate_pet_mesh_scene,
)
from sjtuclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
    placeholder_animation_capability,
)


class MeshSpikeSafeCode(StrEnum):
    SOFTWARE_RENDER_FAILED = "pet_mesh_software_render_failed"
    OPENGL_UNAVAILABLE = "pet_mesh_opengl_unavailable"
    OPENGL_WRONG_THREAD = "pet_mesh_opengl_wrong_thread"
    OPENGL_INITIALIZATION_FAILED = "pet_mesh_opengl_initialization_failed"
    OPENGL_RENDER_FAILED = "pet_mesh_opengl_render_failed"
    OPENGL_CONTEXT_LOST = "pet_mesh_opengl_context_lost"


class MeshSpikeError(RuntimeError):
    """Fixed, non-sensitive failure for an explicitly selected spike."""

    _PUBLIC_MESSAGE = "The pet mesh renderer spike failed safely."

    def __init__(self, code: MeshSpikeSafeCode) -> None:
        self.code = code
        super().__init__(self._PUBLIC_MESSAGE)


@dataclass(frozen=True, slots=True)
class MeshFrameMetrics:
    frame_count: int
    allocation_count: int
    total_frame_nanoseconds: int
    maximum_frame_nanoseconds: int
    output_width: int
    output_height: int

    @property
    def average_frame_milliseconds(self) -> float:
        if self.frame_count == 0:
            return 0.0
        return self.total_frame_nanoseconds / self.frame_count / 1_000_000.0


@dataclass(frozen=True, slots=True)
class MeshBenchmarkResult:
    frame_count: int
    wall_milliseconds_per_frame: float
    cpu_milliseconds_per_frame: float
    allocation_count: int
    meets_30_fps_budget: bool
    meets_60_fps_budget: bool


def generate_checker_texture(
    *,
    premultiplied: bool = False,
) -> PetMeshTextureData:
    """Create the only texture used by the spike entirely in memory."""

    size = 64
    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            checker = ((x // 8) + (y // 8)) % 2
            red, green, blue = (245, 88, 108) if checker == 0 else (56, 190, 224)
            edge_distance = min(x, y, size - 1 - x, size - 1 - y)
            alpha = min(255, max(0, edge_distance * 32))
            if premultiplied:
                red = _multiply_channel(red, alpha)
                green = _multiply_channel(green, alpha)
                blue = _multiply_channel(blue, alpha)
            offset = (y * size + x) * 4
            pixels[offset : offset + 4] = bytes((red, green, blue, alpha))
    return PetMeshTextureData(
        texture_id=("checker-premultiplied" if premultiplied else "checker-straight"),
        width=size,
        height=size,
        rgba_bytes=bytes(pixels),
        premultiplied=premultiplied,
    )


def generate_mesh_spike_scene(
    *,
    device_pixel_ratio: float = 1.0,
    premultiplied_front: bool = False,
) -> PetMeshScene:
    """Create quads, a triangle mesh, draw order and clipping at runtime."""

    if not math.isfinite(device_pixel_ratio) or device_pixel_ratio <= 0:
        raise MeshSpikeError(MeshSpikeSafeCode.SOFTWARE_RENDER_FAILED)
    scale = device_pixel_ratio
    straight = generate_checker_texture()
    premultiplied = generate_checker_texture(premultiplied=True)
    back = _quad_command(
        "checker-straight",
        (12.0, 22.0, 105.0, 126.0),
        draw_order=10,
        scale=scale,
        color=PetMeshColor(255, 255, 255, 205),
    )
    triangle = PetMeshDrawCommand(
        texture_id="checker-straight",
        vertices=tuple(
            _scaled_vertex(x, y, u, v, scale, color)
            for x, y, u, v, color in (
                (34.0, 146.0, 0.0, 1.0, PetMeshColor(255, 255, 255, 230)),
                (86.0, 46.0, 0.5, 0.0, PetMeshColor(255, 220, 255, 230)),
                (145.0, 158.0, 1.0, 1.0, PetMeshColor(220, 255, 255, 230)),
            )
        ),
        triangle_indices=(0, 1, 2),
        draw_order=20,
    )
    front_texture = "checker-premultiplied" if premultiplied_front else "checker-straight"
    front = _quad_command(
        front_texture,
        (54.0, 72.0, 148.0, 154.0),
        draw_order=30,
        scale=scale,
        color=PetMeshColor(255, 255, 255, 190),
        blend_mode=(
            PetMeshBlendMode.PREMULTIPLIED_ALPHA
            if premultiplied_front
            else PetMeshBlendMode.STRAIGHT_ALPHA
        ),
        clip_polygon=tuple(
            PetMeshPoint(x * scale, y * scale)
            for x, y in ((66.0, 78.0), (140.0, 78.0), (140.0, 145.0), (66.0, 145.0))
        ),
    )
    scene = PetMeshScene(
        width=round(160 * scale),
        height=round(180 * scale),
        foot_baseline_y=160.0 * scale,
        textures=(straight, premultiplied),
        draw_commands=(front, triangle, back),
    )
    validate_pet_mesh_scene(scene)
    return scene


class SoftwareTexturedMeshRenderer:
    """Small correctness-oriented CPU triangle rasterizer for the spike."""

    def __init__(self) -> None:
        self._closed = False
        self._frame_count = 0
        self._allocation_count = 0
        self._total_frame_nanoseconds = 0
        self._maximum_frame_nanoseconds = 0
        self._last_size = (0, 0)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def metrics(self) -> MeshFrameMetrics:
        return MeshFrameMetrics(
            frame_count=self._frame_count,
            allocation_count=self._allocation_count,
            total_frame_nanoseconds=self._total_frame_nanoseconds,
            maximum_frame_nanoseconds=self._maximum_frame_nanoseconds,
            output_width=self._last_size[0],
            output_height=self._last_size[1],
        )

    def render_scene(self, scene: PetMeshScene) -> QImage:
        if self._closed:
            raise MeshSpikeError(MeshSpikeSafeCode.SOFTWARE_RENDER_FAILED)
        validate_pet_mesh_scene(scene)
        started = time.perf_counter_ns()
        image = QImage(
            scene.width,
            scene.height,
            QImage.Format.Format_RGBA8888_Premultiplied,
        )
        image.fill(0)
        pixels = memoryview(image.bits())
        textures = {texture.texture_id: texture for texture in scene.textures}
        allocations = 2
        for command in sorted_draw_commands(scene):
            covered_pixels: set[int] = set()
            allocations += 1
            for offset in range(0, len(command.triangle_indices), 3):
                vertices = (
                    command.vertices[command.triangle_indices[offset]],
                    command.vertices[command.triangle_indices[offset + 1]],
                    command.vertices[command.triangle_indices[offset + 2]],
                )
                self._rasterize_triangle(
                    pixels,
                    scene.width,
                    scene.height,
                    textures[command.texture_id],
                    command,
                    vertices,
                    covered_pixels,
                )
        elapsed = time.perf_counter_ns() - started
        self._frame_count += 1
        self._allocation_count += allocations
        self._total_frame_nanoseconds += elapsed
        self._maximum_frame_nanoseconds = max(self._maximum_frame_nanoseconds, elapsed)
        self._last_size = (scene.width, scene.height)
        return image

    def benchmark(self, scene: PetMeshScene, frame_count: int) -> MeshBenchmarkResult:
        if isinstance(frame_count, bool) or frame_count <= 0 or frame_count > 10_000:
            raise MeshSpikeError(MeshSpikeSafeCode.SOFTWARE_RENDER_FAILED)
        allocations_before = self._allocation_count
        wall_started = time.perf_counter_ns()
        cpu_started = time.process_time_ns()
        for _ in range(frame_count):
            self.render_scene(scene)
        cpu_elapsed = time.process_time_ns() - cpu_started
        wall_elapsed = time.perf_counter_ns() - wall_started
        wall_per_frame = wall_elapsed / frame_count / 1_000_000.0
        cpu_per_frame = cpu_elapsed / frame_count / 1_000_000.0
        return MeshBenchmarkResult(
            frame_count=frame_count,
            wall_milliseconds_per_frame=wall_per_frame,
            cpu_milliseconds_per_frame=cpu_per_frame,
            allocation_count=self._allocation_count - allocations_before,
            meets_30_fps_budget=wall_per_frame <= 1000.0 / 30.0,
            meets_60_fps_budget=wall_per_frame <= 1000.0 / 60.0,
        )

    def close(self) -> None:
        self._closed = True

    @staticmethod
    def _rasterize_triangle(
        pixels: memoryview,
        width: int,
        height: int,
        texture: PetMeshTextureData,
        command: PetMeshDrawCommand,
        vertices: tuple[PetMeshVertex, PetMeshVertex, PetMeshVertex],
        covered_pixels: set[int],
    ) -> None:
        first, second, third = vertices
        denominator = _edge(first.position, second.position, third.position)
        if abs(denominator) < 1e-9:
            return
        minimum_x = max(0, math.floor(min(vertex.position.x for vertex in vertices)))
        maximum_x = min(width - 1, math.ceil(max(vertex.position.x for vertex in vertices)))
        minimum_y = max(0, math.floor(min(vertex.position.y for vertex in vertices)))
        maximum_y = min(height - 1, math.ceil(max(vertex.position.y for vertex in vertices)))
        for y in range(minimum_y, maximum_y + 1):
            for x in range(minimum_x, maximum_x + 1):
                pixel_key = y * width + x
                if pixel_key in covered_pixels:
                    continue
                point = PetMeshPoint(x + 0.5, y + 0.5)
                weight_first = _edge(second.position, third.position, point) / denominator
                weight_second = _edge(third.position, first.position, point) / denominator
                weight_third = 1.0 - weight_first - weight_second
                if min(weight_first, weight_second, weight_third) < -1e-7:
                    continue
                if command.clip_polygon is not None and not _point_in_polygon(
                    point, command.clip_polygon
                ):
                    continue
                covered_pixels.add(pixel_key)
                u = sum(
                    weight * vertex.u
                    for weight, vertex in zip(
                        (weight_first, weight_second, weight_third), vertices, strict=True
                    )
                )
                v = sum(
                    weight * vertex.v
                    for weight, vertex in zip(
                        (weight_first, weight_second, weight_third), vertices, strict=True
                    )
                )
                color = tuple(
                    round(
                        sum(
                            weight * channel
                            for weight, channel in zip(
                                (weight_first, weight_second, weight_third),
                                channels,
                                strict=True,
                            )
                        )
                    )
                    for channels in zip(
                        *(
                            (
                                vertex.color.red,
                                vertex.color.green,
                                vertex.color.blue,
                                vertex.color.alpha,
                            )
                            for vertex in vertices
                        ),
                        strict=True,
                    )
                )
                source = _sample_texture(texture, u, v, color, command.blend_mode)
                _blend_premultiplied(pixels, pixel_key * 4, source)


class SoftwareMeshPetRenderer:
    """Explicit PetRenderer adapter used only by fallback and paint tests."""

    def __init__(self) -> None:
        self._renderer = SoftwareTexturedMeshRenderer()
        self._scene = generate_mesh_spike_scene()
        self._closed = False
        self._paused = False
        self._state: PetRendererActionRequest | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def metrics(self) -> MeshFrameMetrics:
        return self._renderer.metrics

    def initialize(self, viewport: Size) -> None:
        self.set_viewport(viewport)

    def set_viewport(self, viewport: Size) -> None:
        if self._closed:
            return
        if viewport != Size(160, 180):
            raise MeshSpikeError(MeshSpikeSafeCode.SOFTWARE_RENDER_FAILED)

    def set_state(self, request: PetRendererActionRequest) -> None:
        if not self._closed:
            self._state = request

    def update(self, delta_seconds: float) -> None:
        if not math.isfinite(delta_seconds) or delta_seconds < 0:
            raise MeshSpikeError(MeshSpikeSafeCode.SOFTWARE_RENDER_FAILED)

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del frame
        if not self._closed:
            painter.drawImage(0, 0, self._renderer.render_scene(self._scene))

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
        if self._closed:
            return
        self._closed = True
        self._renderer.close()


class OffscreenOpenGLMeshRenderer:
    """GUI-thread-only FBO experiment with explicit readback."""

    _VERTEX_SHADER = """#version 330 core
layout(location = 0) in vec2 inPosition;
layout(location = 1) in vec2 inUv;
layout(location = 2) in vec4 inColor;
out vec2 uv;
out vec4 color;
void main() { gl_Position = vec4(inPosition, 0.0, 1.0); uv = inUv; color = inColor; }
"""
    _FRAGMENT_SHADER = """#version 330 core
in vec2 uv;
in vec4 color;
uniform sampler2D sourceTexture;
out vec4 fragmentColor;
void main() { fragmentColor = texture(sourceTexture, uv) * color; }
"""

    def __init__(self) -> None:
        self._thread_id = get_ident()
        self._qt_thread = QThread.currentThread()
        self._context: QOpenGLContext | None = None
        self._surface: QOffscreenSurface | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def initialize(self) -> None:
        self._require_owner_thread()
        if self._closed or QGuiApplication.instance() is None:
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_UNAVAILABLE)
        if self._context is not None:
            return
        surface_format = QSurfaceFormat()
        surface_format.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        surface_format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        surface_format.setVersion(3, 3)
        context = QOpenGLContext()
        context.setFormat(surface_format)
        if not context.create():
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_INITIALIZATION_FAILED)
        surface = QOffscreenSurface()
        surface.setFormat(context.format())
        surface.create()
        if not surface.isValid() or not context.makeCurrent(surface):
            context.deleteLater()
            surface.deleteLater()
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_INITIALIZATION_FAILED)
        program = QOpenGLShaderProgram()
        if (
            not program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, self._VERTEX_SHADER
            )
            or not program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment, self._FRAGMENT_SHADER
            )
            or not program.link()
        ):
            context.doneCurrent()
            program.deleteLater()
            context.deleteLater()
            surface.deleteLater()
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_INITIALIZATION_FAILED)
        self._context = context
        self._surface = surface
        self._program = program
        context.doneCurrent()

    def render_scene(self, scene: PetMeshScene) -> QImage:
        self._require_owner_thread()
        if self._closed:
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_RENDER_FAILED)
        validate_pet_mesh_scene(scene)
        try:
            self.initialize()
        except MeshSpikeError:
            raise
        except Exception:
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_INITIALIZATION_FAILED) from None
        context = self._context
        surface = self._surface
        program = self._program
        if context is None or surface is None or program is None or not context.isValid():
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_CONTEXT_LOST)
        if not context.makeCurrent(surface):
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_CONTEXT_LOST)
        framebuffer: QOpenGLFramebufferObject | None = None
        try:
            framebuffer_format = QOpenGLFramebufferObjectFormat()
            framebuffer_format.setAttachment(
                QOpenGLFramebufferObject.Attachment.CombinedDepthStencil
            )
            framebuffer = QOpenGLFramebufferObject(
                scene.width,
                scene.height,
                framebuffer_format,
            )
            if not framebuffer.isValid() or not framebuffer.bind():
                raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_RENDER_FAILED)
            functions = context.functions()
            functions.glViewport(0, 0, scene.width, scene.height)
            functions.glClearColor(0.0, 0.0, 0.0, 0.0)
            functions.glClear(0x00004000)
            functions.glEnable(0x0BE2)
            textures = {texture.texture_id: texture for texture in scene.textures}
            for command in sorted_draw_commands(scene):
                self._draw_command(
                    functions,
                    program,
                    scene,
                    textures[command.texture_id],
                    command,
                )
            functions.glFinish()
            return framebuffer.toImage().convertToFormat(
                QImage.Format.Format_RGBA8888_Premultiplied
            )
        except MeshSpikeError:
            raise
        except Exception:
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_RENDER_FAILED) from None
        finally:
            if framebuffer is not None:
                framebuffer.release()
            context.doneCurrent()

    def close(self) -> None:
        self._require_owner_thread()
        if self._closed:
            return
        self._closed = True
        context = self._context
        surface = self._surface
        program = self._program
        if context is not None and surface is not None and context.makeCurrent(surface):
            if program is not None:
                program.removeAllShaders()
                program.deleteLater()
            context.doneCurrent()
        if surface is not None:
            surface.destroy()
            surface.deleteLater()
        if context is not None:
            context.deleteLater()
        self._program = None
        self._surface = None
        self._context = None

    def _require_owner_thread(self) -> None:
        if get_ident() != self._thread_id or QThread.currentThread() is not self._qt_thread:
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_WRONG_THREAD)

    @staticmethod
    def _draw_command(
        functions: QOpenGLFunctions,
        program: QOpenGLShaderProgram,
        scene: PetMeshScene,
        texture_data: PetMeshTextureData,
        command: PetMeshDrawCommand,
    ) -> None:
        # QOpenGLFunctions is intentionally kept behind Qt's stable wrapper.
        gl = functions
        vertex_bytes = bytearray()
        for vertex in command.vertices:
            ndc_x = vertex.position.x / scene.width * 2.0 - 1.0
            ndc_y = 1.0 - vertex.position.y / scene.height * 2.0
            vertex_bytes.extend(
                struct.pack(
                    "8f",
                    ndc_x,
                    ndc_y,
                    vertex.u,
                    vertex.v,
                    vertex.color.red / 255.0,
                    vertex.color.green / 255.0,
                    vertex.color.blue / 255.0,
                    vertex.color.alpha / 255.0,
                )
            )
        index_bytes = struct.pack(f"{len(command.triangle_indices)}I", *command.triangle_indices)
        vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        index_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        vertex_array = QOpenGLVertexArrayObject()
        if not vertex_array.create() or not vertex_buffer.create() or not index_buffer.create():
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_RENDER_FAILED)
        texture_image = QImage(
            texture_data.rgba_bytes,
            texture_data.width,
            texture_data.height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        texture = QOpenGLTexture(texture_image)
        try:
            vertex_array.bind()
            vertex_buffer.bind()
            vertex_buffer.allocate(bytes(vertex_bytes), len(vertex_bytes))
            index_buffer.bind()
            index_buffer.allocate(index_bytes, len(index_bytes))
            program.bind()
            texture_uniform = program.uniformLocation(b"sourceTexture")
            program.setUniformValue(texture_uniform, 0)
            texture.bind(0)
            stride = 8 * 4
            program.enableAttributeArray(0)
            program.setAttributeBuffer(0, 0x1406, 0, 2, stride)
            program.enableAttributeArray(1)
            program.setAttributeBuffer(1, 0x1406, 2 * 4, 2, stride)
            program.enableAttributeArray(2)
            program.setAttributeBuffer(2, 0x1406, 4 * 4, 4, stride)
            if command.blend_mode is PetMeshBlendMode.PREMULTIPLIED_ALPHA:
                gl.glBlendFunc(1, 0x0303)
            else:
                gl.glBlendFunc(0x0302, 0x0303)
            if command.clip_polygon is not None:
                minimum_x = math.floor(min(point.x for point in command.clip_polygon))
                maximum_x = math.ceil(max(point.x for point in command.clip_polygon))
                minimum_y = math.floor(min(point.y for point in command.clip_polygon))
                maximum_y = math.ceil(max(point.y for point in command.clip_polygon))
                gl.glEnable(0x0C11)
                gl.glScissor(
                    minimum_x,
                    scene.height - maximum_y,
                    maximum_x - minimum_x,
                    maximum_y - minimum_y,
                )
            gl.glDrawElements(
                0x0004,
                len(command.triangle_indices),
                0x1405,
                VoidPtr(0),  # type: ignore[arg-type]
            )
            if command.clip_polygon is not None:
                gl.glDisable(0x0C11)
            texture.release()
            program.disableAttributeArray(0)
            program.disableAttributeArray(1)
            program.disableAttributeArray(2)
            program.release()
            index_buffer.release()
            vertex_buffer.release()
            vertex_array.release()
        finally:
            texture.destroy()
            index_buffer.destroy()
            vertex_buffer.destroy()
            vertex_array.destroy()


class OffscreenOpenGLMeshPetRenderer:
    """Explicit FBO PetRenderer adapter; absent from production selection."""

    def __init__(self) -> None:
        self._renderer = OffscreenOpenGLMeshRenderer()
        self._scene = generate_mesh_spike_scene()
        self._closed = False
        self._paused = False
        self._state: PetRendererActionRequest | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    def initialize(self, viewport: Size) -> None:
        self.set_viewport(viewport)
        self._renderer.initialize()

    def set_viewport(self, viewport: Size) -> None:
        if self._closed:
            return
        if viewport != Size(160, 180):
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_RENDER_FAILED)

    def set_state(self, request: PetRendererActionRequest) -> None:
        if not self._closed:
            self._state = request

    def update(self, delta_seconds: float) -> None:
        if not math.isfinite(delta_seconds) or delta_seconds < 0:
            raise MeshSpikeError(MeshSpikeSafeCode.OPENGL_RENDER_FAILED)

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del frame
        if not self._closed:
            painter.drawImage(0, 0, self._renderer.render_scene(self._scene))

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
        if self._closed:
            return
        self._closed = True
        self._renderer.close()


def _quad_command(
    texture_id: str,
    bounds: tuple[float, float, float, float],
    *,
    draw_order: int,
    scale: float,
    color: PetMeshColor,
    blend_mode: PetMeshBlendMode = PetMeshBlendMode.STRAIGHT_ALPHA,
    clip_polygon: tuple[PetMeshPoint, ...] | None = None,
) -> PetMeshDrawCommand:
    left, top, right, bottom = bounds
    vertices = (
        _scaled_vertex(left, top, 0.0, 0.0, scale, color),
        _scaled_vertex(right, top, 1.0, 0.0, scale, color),
        _scaled_vertex(right, bottom, 1.0, 1.0, scale, color),
        _scaled_vertex(left, bottom, 0.0, 1.0, scale, color),
    )
    return PetMeshDrawCommand(
        texture_id=texture_id,
        vertices=vertices,
        triangle_indices=(0, 1, 2, 0, 2, 3),
        draw_order=draw_order,
        blend_mode=blend_mode,
        clip_polygon=clip_polygon,
    )


def _scaled_vertex(
    x: float,
    y: float,
    u: float,
    v: float,
    scale: float,
    color: PetMeshColor,
) -> PetMeshVertex:
    return PetMeshVertex(PetMeshPoint(x * scale, y * scale), u, v, color)


def _edge(first: PetMeshPoint, second: PetMeshPoint, point: PetMeshPoint) -> float:
    return (point.x - first.x) * (second.y - first.y) - (point.y - first.y) * (second.x - first.x)


def _point_in_polygon(point: PetMeshPoint, polygon: tuple[PetMeshPoint, ...]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current.y > point.y) != (previous.y > point.y):
            intersection_x = (previous.x - current.x) * (point.y - current.y) / (
                previous.y - current.y
            ) + current.x
            if point.x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _sample_texture(
    texture: PetMeshTextureData,
    u: float,
    v: float,
    vertex_color: tuple[int, int, int, int],
    blend_mode: PetMeshBlendMode,
) -> tuple[int, int, int, int]:
    texture_x = min(texture.width - 1, max(0, round(u * (texture.width - 1))))
    texture_y = min(texture.height - 1, max(0, round(v * (texture.height - 1))))
    offset = (texture_y * texture.width + texture_x) * 4
    red, green, blue, alpha = texture.rgba_bytes[offset : offset + 4]
    color_red, color_green, color_blue, color_alpha = vertex_color
    alpha = _multiply_channel(alpha, color_alpha)
    if blend_mode is PetMeshBlendMode.PREMULTIPLIED_ALPHA:
        red = _multiply_channel(red, color_red)
        green = _multiply_channel(green, color_green)
        blue = _multiply_channel(blue, color_blue)
        red = _multiply_channel(red, color_alpha)
        green = _multiply_channel(green, color_alpha)
        blue = _multiply_channel(blue, color_alpha)
    else:
        red = _multiply_channel(_multiply_channel(red, color_red), alpha)
        green = _multiply_channel(_multiply_channel(green, color_green), alpha)
        blue = _multiply_channel(_multiply_channel(blue, color_blue), alpha)
    return red, green, blue, alpha


def _blend_premultiplied(
    pixels: memoryview,
    offset: int,
    source: tuple[int, int, int, int],
) -> None:
    source_red, source_green, source_blue, source_alpha = source
    inverse_alpha = 255 - source_alpha
    destination_red = pixels[offset]
    destination_green = pixels[offset + 1]
    destination_blue = pixels[offset + 2]
    destination_alpha = pixels[offset + 3]
    pixels[offset] = min(255, source_red + _multiply_channel(destination_red, inverse_alpha))
    pixels[offset + 1] = min(
        255, source_green + _multiply_channel(destination_green, inverse_alpha)
    )
    pixels[offset + 2] = min(255, source_blue + _multiply_channel(destination_blue, inverse_alpha))
    pixels[offset + 3] = min(
        255, source_alpha + _multiply_channel(destination_alpha, inverse_alpha)
    )


def _multiply_channel(first: int, second: int) -> int:
    return (first * second + 127) // 255
