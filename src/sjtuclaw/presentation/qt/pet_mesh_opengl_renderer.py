"""Reusable GUI-thread OpenGL backend for renderer-neutral pet meshes.

The backend deliberately renders into an offscreen FBO and returns a QImage.
It does not own a window, animation timer, movement, physics, or external assets.
"""

from __future__ import annotations

import math
import statistics
import struct
import time
from dataclasses import dataclass
from enum import StrEnum
from threading import get_ident
from typing import Protocol

from PySide6.QtCore import QRectF, QThread
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
from shiboken6 import VoidPtr, delete

from sjtuclaw.application.pet_animation import PetRenderFrame
from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_mesh_model import (
    PetMeshBlendMode,
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


class OpenGLMeshSafeCode(StrEnum):
    UNAVAILABLE = "pet_mesh_opengl_unavailable"
    WRONG_THREAD = "pet_mesh_opengl_wrong_thread"
    INITIALIZATION_FAILED = "pet_mesh_opengl_initialization_failed"
    SHADER_FAILED = "pet_mesh_opengl_shader_failed"
    SCENE_UPLOAD_FAILED = "pet_mesh_opengl_scene_upload_failed"
    VIEWPORT_FAILED = "pet_mesh_opengl_viewport_failed"
    RENDER_FAILED = "pet_mesh_opengl_render_failed"
    READBACK_FAILED = "pet_mesh_opengl_readback_failed"
    CONTEXT_LOST = "pet_mesh_opengl_context_lost"
    CLOSED = "pet_mesh_opengl_closed"


class OpenGLMeshFaultPoint(StrEnum):
    """Deterministic diagnostic seams; production leaves every point disarmed."""

    CONTEXT_CREATE = "context_create"
    SHADER_CREATE = "shader_create"
    SCENE_UPLOAD = "scene_upload"
    VIEWPORT_CREATE = "viewport_create"
    CONTEXT_CURRENT = "context_current"
    READBACK = "readback"


class OpenGLMeshFaultController:
    """One-shot GUI-thread fault controller used by deterministic tests."""

    def __init__(self) -> None:
        self._armed: set[OpenGLMeshFaultPoint] = set()

    def arm(self, point: OpenGLMeshFaultPoint) -> None:
        self._armed.add(point)

    def consume(self, point: OpenGLMeshFaultPoint) -> bool:
        if point not in self._armed:
            return False
        self._armed.remove(point)
        return True


class OpenGLMeshError(RuntimeError):
    """Fixed, content-free OpenGL failure exposed to SafePetRenderer."""

    _PUBLIC_MESSAGE = "The OpenGL pet renderer failed safely."

    def __init__(self, code: OpenGLMeshSafeCode) -> None:
        self.code = code
        super().__init__(self._PUBLIC_MESSAGE)


@dataclass(frozen=True, slots=True)
class OpenGLMeshMetrics:
    initialization_milliseconds: float
    first_frame_milliseconds: float
    warmed_frame_count: int
    warmed_mean_milliseconds: float
    warmed_p50_milliseconds: float
    warmed_p95_milliseconds: float
    warmed_max_milliseconds: float
    readback_mean_milliseconds: float
    texture_upload_count: int
    mesh_upload_count: int
    scene_replacement_count: int
    framebuffer_replacement_count: int
    frame_readback_allocation_count: int

    @property
    def meets_30_fps_budget(self) -> bool:
        return self.warmed_mean_milliseconds <= 1000.0 / 30.0

    @property
    def meets_60_fps_budget(self) -> bool:
        return self.warmed_mean_milliseconds <= 1000.0 / 60.0


@dataclass(slots=True)
class _GpuTexture:
    texture: QOpenGLTexture

    def destroy(self) -> None:
        self.texture.destroy()


@dataclass(slots=True)
class _GpuGeometry:
    vertex_buffer: QOpenGLBuffer
    index_buffer: QOpenGLBuffer
    vertex_array: QOpenGLVertexArrayObject
    index_count: int

    def destroy(self) -> None:
        self.index_buffer.destroy()
        self.vertex_buffer.destroy()
        self.vertex_array.destroy()


@dataclass(slots=True)
class _GpuDrawCommand:
    source: PetMeshDrawCommand
    geometry: _GpuGeometry
    clip_geometry: _GpuGeometry | None

    def destroy(self) -> None:
        if self.clip_geometry is not None:
            self.clip_geometry.destroy()
        self.geometry.destroy()


@dataclass(slots=True)
class _GpuScene:
    source: PetMeshScene
    textures: dict[str, _GpuTexture]
    commands: tuple[_GpuDrawCommand, ...]

    def destroy(self) -> None:
        for command in self.commands:
            command.destroy()
        for texture in self.textures.values():
            texture.destroy()


class PetMeshImageBackend(Protocol):
    @property
    def closed(self) -> bool: ...

    def initialize(self, viewport: Size) -> None: ...

    def set_viewport(self, viewport: Size) -> None: ...

    def set_scene(self, scene: PetMeshScene) -> None: ...

    def render_scene(self) -> QImage: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def close(self) -> None: ...


class OpenGLTexturedMeshBackend:
    """Persistent offscreen OpenGL resources with transactional replacement."""

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
uniform int associateVertexAlpha;
out vec4 fragmentColor;
void main() {
    fragmentColor = texture(sourceTexture, uv) * color;
    if (associateVertexAlpha != 0) { fragmentColor.rgb *= color.a; }
}
"""

    def __init__(
        self,
        scene: PetMeshScene,
        *,
        device_pixel_ratio: float = 1.0,
        fault_controller: OpenGLMeshFaultController | None = None,
    ) -> None:
        validate_pet_mesh_scene(scene)
        if not math.isfinite(device_pixel_ratio) or device_pixel_ratio <= 0.0:
            raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED)
        self._thread_id = get_ident()
        self._qt_thread = QThread.currentThread()
        self._scene = scene
        self._device_pixel_ratio = device_pixel_ratio
        self._fault_controller = fault_controller or OpenGLMeshFaultController()
        self._viewport = Size(scene.width, scene.height)
        self._context: QOpenGLContext | None = None
        self._surface: QOffscreenSurface | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._gpu_scene: _GpuScene | None = None
        self._framebuffer: QOpenGLFramebufferObject | None = None
        self._closed = False
        self._paused = False
        self._initialization_ns = 0
        self._frame_ns: list[int] = []
        self._readback_ns: list[int] = []
        self._texture_upload_count = 0
        self._mesh_upload_count = 0
        self._scene_replacement_count = 0
        self._framebuffer_replacement_count = 0
        self._frame_readback_allocation_count = 0

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def physical_size(self) -> tuple[int, int]:
        return (
            round(self._viewport.width * self._device_pixel_ratio),
            round(self._viewport.height * self._device_pixel_ratio),
        )

    @property
    def metrics(self) -> OpenGLMeshMetrics:
        first = self._frame_ns[0] / 1_000_000.0 if self._frame_ns else 0.0
        warmed = tuple(value / 1_000_000.0 for value in self._frame_ns[1:])
        readbacks = tuple(value / 1_000_000.0 for value in self._readback_ns)
        return OpenGLMeshMetrics(
            initialization_milliseconds=self._initialization_ns / 1_000_000.0,
            first_frame_milliseconds=first,
            warmed_frame_count=len(warmed),
            warmed_mean_milliseconds=statistics.fmean(warmed) if warmed else 0.0,
            warmed_p50_milliseconds=_percentile(warmed, 0.50),
            warmed_p95_milliseconds=_percentile(warmed, 0.95),
            warmed_max_milliseconds=max(warmed, default=0.0),
            readback_mean_milliseconds=(statistics.fmean(readbacks) if readbacks else 0.0),
            texture_upload_count=self._texture_upload_count,
            mesh_upload_count=self._mesh_upload_count,
            scene_replacement_count=self._scene_replacement_count,
            framebuffer_replacement_count=self._framebuffer_replacement_count,
            frame_readback_allocation_count=self._frame_readback_allocation_count,
        )

    def initialize(self, viewport: Size) -> None:
        self._require_owner_thread()
        if self._closed:
            raise OpenGLMeshError(OpenGLMeshSafeCode.CLOSED)
        if self._context is not None:
            self.set_viewport(viewport)
            return
        if QGuiApplication.instance() is None:
            raise OpenGLMeshError(OpenGLMeshSafeCode.UNAVAILABLE)
        started = time.perf_counter_ns()
        context: QOpenGLContext | None = None
        surface: QOffscreenSurface | None = None
        program: QOpenGLShaderProgram | None = None
        try:
            surface_format = QSurfaceFormat()
            surface_format.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
            surface_format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            surface_format.setVersion(3, 3)
            context = QOpenGLContext()
            context.setFormat(surface_format)
            if self._fault_controller.consume(OpenGLMeshFaultPoint.CONTEXT_CREATE):
                raise OpenGLMeshError(OpenGLMeshSafeCode.INITIALIZATION_FAILED)
            if not context.create():
                raise OpenGLMeshError(OpenGLMeshSafeCode.INITIALIZATION_FAILED)
            surface = QOffscreenSurface()
            surface.setFormat(context.format())
            surface.create()
            if not surface.isValid() or not context.makeCurrent(surface):
                raise OpenGLMeshError(OpenGLMeshSafeCode.INITIALIZATION_FAILED)
            program = self._create_program()
            self._context = context
            self._surface = surface
            self._program = program
            self._viewport = viewport
            self._gpu_scene = self._upload_scene(self._scene)
            self._framebuffer = self._create_framebuffer(viewport)
            context.doneCurrent()
            self._initialization_ns = time.perf_counter_ns() - started
        except OpenGLMeshError:
            self._dispose_failed_initialization(context, surface, program)
            raise
        except Exception:
            self._dispose_failed_initialization(context, surface, program)
            raise OpenGLMeshError(OpenGLMeshSafeCode.INITIALIZATION_FAILED) from None

    def set_scene(self, scene: PetMeshScene) -> None:
        self._require_owner_thread()
        if self._closed:
            raise OpenGLMeshError(OpenGLMeshSafeCode.CLOSED)
        validate_pet_mesh_scene(scene)
        if self._context is None:
            self._scene = scene
            return
        context = self._make_current()
        candidate: _GpuScene | None = None
        try:
            candidate = self._upload_scene(scene)
            previous = self._gpu_scene
            self._gpu_scene = candidate
            self._scene = scene
            self._scene_replacement_count += 1
            if previous is not None:
                previous.destroy()
        except OpenGLMeshError:
            if candidate is not None:
                candidate.destroy()
            raise
        except Exception:
            if candidate is not None:
                candidate.destroy()
            raise OpenGLMeshError(OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED) from None
        finally:
            context.doneCurrent()

    def set_viewport(self, viewport: Size) -> None:
        self._require_owner_thread()
        if self._closed:
            raise OpenGLMeshError(OpenGLMeshSafeCode.CLOSED)
        _validate_viewport(viewport, self._device_pixel_ratio)
        if viewport == self._viewport:
            return
        if self._context is None:
            self._viewport = viewport
            return
        context = self._make_current()
        candidate: QOpenGLFramebufferObject | None = None
        try:
            candidate = self._create_framebuffer(viewport)
            previous = self._framebuffer
            self._framebuffer = candidate
            self._viewport = viewport
            self._framebuffer_replacement_count += 1
            if previous is not None:
                previous.release()
                delete(previous)
        except OpenGLMeshError:
            if candidate is not None:
                delete(candidate)
            raise
        except Exception:
            if candidate is not None:
                delete(candidate)
            raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED) from None
        finally:
            context.doneCurrent()

    def set_device_pixel_ratio(self, value: float) -> None:
        self._require_owner_thread()
        if not math.isfinite(value) or value <= 0.0:
            raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED)
        if math.isclose(value, self._device_pixel_ratio):
            return
        previous = self._device_pixel_ratio
        self._device_pixel_ratio = value
        try:
            if self._context is not None:
                self._replace_framebuffer_for_current_viewport()
        except Exception:
            self._device_pixel_ratio = previous
            raise

    def pause(self) -> None:
        if not self._closed:
            self._paused = True

    def resume(self) -> None:
        if not self._closed:
            self._paused = False

    def render_scene(self) -> QImage:
        self._require_owner_thread()
        if self._closed:
            raise OpenGLMeshError(OpenGLMeshSafeCode.CLOSED)
        if self._context is None:
            self.initialize(self._viewport)
        context = self._make_current()
        framebuffer = self._framebuffer
        gpu_scene = self._gpu_scene
        program = self._program
        if framebuffer is None or gpu_scene is None or program is None:
            context.doneCurrent()
            raise OpenGLMeshError(OpenGLMeshSafeCode.RENDER_FAILED)
        started = time.perf_counter_ns()
        try:
            if not framebuffer.bind():
                raise OpenGLMeshError(OpenGLMeshSafeCode.RENDER_FAILED)
            functions = context.functions()
            physical_width, physical_height = self.physical_size
            functions.glViewport(0, 0, physical_width, physical_height)
            functions.glClearColor(0.0, 0.0, 0.0, 0.0)
            functions.glClear(0x00004000 | 0x00000400)
            functions.glEnable(0x0BE2)
            for command in gpu_scene.commands:
                self._render_command(functions, program, gpu_scene, command)
            if self._fault_controller.consume(OpenGLMeshFaultPoint.READBACK):
                raise OpenGLMeshError(OpenGLMeshSafeCode.READBACK_FAILED)
            readback_started = time.perf_counter_ns()
            image = framebuffer.toImage().convertToFormat(
                QImage.Format.Format_RGBA8888_Premultiplied
            )
            readback_elapsed = time.perf_counter_ns() - readback_started
            if image.isNull() or image.size().toTuple() != self.physical_size:
                raise OpenGLMeshError(OpenGLMeshSafeCode.READBACK_FAILED)
            self._readback_ns.append(readback_elapsed)
            self._frame_readback_allocation_count += 1
            self._frame_ns.append(time.perf_counter_ns() - started)
            return image
        except OpenGLMeshError:
            raise
        except Exception:
            raise OpenGLMeshError(OpenGLMeshSafeCode.RENDER_FAILED) from None
        finally:
            framebuffer.release()
            context.doneCurrent()

    def close(self) -> None:
        self._require_owner_thread()
        if self._closed:
            return
        self._closed = True
        context = self._context
        surface = self._surface
        if context is not None and surface is not None and context.makeCurrent(surface):
            if self._gpu_scene is not None:
                self._gpu_scene.destroy()
            if self._framebuffer is not None:
                self._framebuffer.release()
                delete(self._framebuffer)
            if self._program is not None:
                self._program.removeAllShaders()
                delete(self._program)
            context.doneCurrent()
        self._gpu_scene = None
        self._framebuffer = None
        self._program = None
        if surface is not None:
            surface.destroy()
            delete(surface)
        if context is not None:
            delete(context)
        self._surface = None
        self._context = None

    def _create_program(self) -> QOpenGLShaderProgram:
        if self._fault_controller.consume(OpenGLMeshFaultPoint.SHADER_CREATE):
            raise OpenGLMeshError(OpenGLMeshSafeCode.SHADER_FAILED)
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
            delete(program)
            raise OpenGLMeshError(OpenGLMeshSafeCode.SHADER_FAILED)
        return program

    def _upload_scene(self, scene: PetMeshScene) -> _GpuScene:
        if self._fault_controller.consume(OpenGLMeshFaultPoint.SCENE_UPLOAD):
            raise OpenGLMeshError(OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED)
        program = self._program
        if program is None:
            raise OpenGLMeshError(OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED)
        textures: dict[str, _GpuTexture] = {}
        commands: list[_GpuDrawCommand] = []
        try:
            for texture_data in scene.textures:
                textures[texture_data.texture_id] = _GpuTexture(
                    self._upload_texture(texture_data)
                )
                self._texture_upload_count += 1
            for command in sorted_draw_commands(scene):
                geometry: _GpuGeometry | None = None
                clip_geometry: _GpuGeometry | None = None
                try:
                    geometry = self._upload_geometry(
                        scene,
                        command.vertices,
                        command.triangle_indices,
                        program,
                    )
                    clip_geometry = (
                        self._upload_clip_geometry(
                            scene,
                            command.clip_polygon,
                            program,
                        )
                        if command.clip_polygon is not None
                        else None
                    )
                    commands.append(
                        _GpuDrawCommand(command, geometry, clip_geometry)
                    )
                except Exception:
                    if clip_geometry is not None:
                        clip_geometry.destroy()
                    if geometry is not None:
                        geometry.destroy()
                    raise
                self._mesh_upload_count += 1 + (clip_geometry is not None)
            return _GpuScene(scene, textures, tuple(commands))
        except Exception:
            for uploaded_command in commands:
                uploaded_command.destroy()
            for texture in textures.values():
                texture.destroy()
            raise OpenGLMeshError(OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED) from None

    @staticmethod
    def _upload_texture(texture_data: PetMeshTextureData) -> QOpenGLTexture:
        image = QImage(
            texture_data.rgba_bytes,
            texture_data.width,
            texture_data.height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        # QOpenGLTexture's QImage upload keeps Qt's top-left image convention.
        texture = QOpenGLTexture(image)
        if not texture.isCreated():
            raise OpenGLMeshError(OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED)
        texture.setMinificationFilter(QOpenGLTexture.Filter.Nearest)
        texture.setMagnificationFilter(QOpenGLTexture.Filter.Nearest)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        return texture

    def _upload_geometry(
        self,
        scene: PetMeshScene,
        vertices: tuple[PetMeshVertex, ...],
        indices: tuple[int, ...],
        program: QOpenGLShaderProgram,
    ) -> _GpuGeometry:
        vertex_bytes = bytearray()
        for vertex in vertices:
            position = vertex.position
            color = vertex.color
            vertex_bytes.extend(
                struct.pack(
                    "8f",
                    position.x / scene.width * 2.0 - 1.0,
                    1.0 - position.y / scene.height * 2.0,
                    vertex.u,
                    vertex.v,
                    color.red / 255.0,
                    color.green / 255.0,
                    color.blue / 255.0,
                    color.alpha / 255.0,
                )
            )
        return self._create_geometry(bytes(vertex_bytes), indices, program)

    def _upload_clip_geometry(
        self,
        scene: PetMeshScene,
        points: tuple[PetMeshPoint, ...],
        program: QOpenGLShaderProgram,
    ) -> _GpuGeometry:
        vertex_bytes = bytearray()
        for point in points:
            vertex_bytes.extend(
                struct.pack(
                    "8f",
                    point.x / scene.width * 2.0 - 1.0,
                    1.0 - point.y / scene.height * 2.0,
                    0.0,
                    0.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                )
            )
        indices = tuple(
            index
            for triangle in ((0, value, value + 1) for value in range(1, len(points) - 1))
            for index in triangle
        )
        return self._create_geometry(bytes(vertex_bytes), indices, program)

    @staticmethod
    def _create_geometry(
        vertex_bytes: bytes,
        indices: tuple[int, ...],
        program: QOpenGLShaderProgram,
    ) -> _GpuGeometry:
        vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        index_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        vertex_array = QOpenGLVertexArrayObject()
        if not vertex_array.create() or not vertex_buffer.create() or not index_buffer.create():
            vertex_array.destroy()
            vertex_buffer.destroy()
            index_buffer.destroy()
            raise OpenGLMeshError(OpenGLMeshSafeCode.SCENE_UPLOAD_FAILED)
        index_bytes = struct.pack(f"{len(indices)}I", *indices)
        vertex_array.bind()
        vertex_buffer.bind()
        vertex_buffer.allocate(vertex_bytes, len(vertex_bytes))
        index_buffer.bind()
        index_buffer.allocate(index_bytes, len(index_bytes))
        program.bind()
        stride = 8 * 4
        for location, offset, count in ((0, 0, 2), (1, 2 * 4, 2), (2, 4 * 4, 4)):
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, 0x1406, offset, count, stride)
        program.release()
        index_buffer.release()
        vertex_buffer.release()
        vertex_array.release()
        return _GpuGeometry(vertex_buffer, index_buffer, vertex_array, len(indices))

    def _create_framebuffer(self, viewport: Size) -> QOpenGLFramebufferObject:
        if self._fault_controller.consume(OpenGLMeshFaultPoint.VIEWPORT_CREATE):
            raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED)
        _validate_viewport(viewport, self._device_pixel_ratio)
        width = round(viewport.width * self._device_pixel_ratio)
        height = round(viewport.height * self._device_pixel_ratio)
        framebuffer_format = QOpenGLFramebufferObjectFormat()
        framebuffer_format.setAttachment(
            QOpenGLFramebufferObject.Attachment.CombinedDepthStencil
        )
        framebuffer = QOpenGLFramebufferObject(width, height, framebuffer_format)
        if not framebuffer.isValid():
            delete(framebuffer)
            raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED)
        return framebuffer

    @staticmethod
    def _render_command(
        gl: QOpenGLFunctions,
        program: QOpenGLShaderProgram,
        scene: _GpuScene,
        command: _GpuDrawCommand,
    ) -> None:
        texture = scene.textures[command.source.texture_id].texture
        program.bind()
        program.setUniformValue(program.uniformLocation(b"sourceTexture"), 0)
        program.setUniformValue(
            program.uniformLocation(b"associateVertexAlpha"),
            int(
                command.source.blend_mode
                is PetMeshBlendMode.NORMAL_PREMULTIPLIED
            ),
        )
        texture.bind(0)
        clip = command.clip_geometry
        if clip is not None:
            gl.glEnable(0x0B90)
            gl.glStencilMask(0xFF)
            gl.glClearStencil(0)
            gl.glClear(0x00000400)
            gl.glColorMask(False, False, False, False)
            gl.glDisable(0x0BE2)
            gl.glStencilFunc(0x0207, 1, 0xFF)
            gl.glStencilOp(0x1E01, 0x1E01, 0x1E01)
            _draw_geometry(gl, clip)
            gl.glColorMask(True, True, True, True)
            gl.glStencilMask(0x00)
            gl.glStencilFunc(0x0202, 1, 0xFF)
            gl.glStencilOp(0x1E00, 0x1E00, 0x1E00)
            gl.glEnable(0x0BE2)
        blend_mode = command.source.blend_mode
        if blend_mode is PetMeshBlendMode.NORMAL_PREMULTIPLIED:
            source_rgb, destination_rgb = 1, 0x0303
        elif blend_mode is PetMeshBlendMode.ADDITIVE:
            source_rgb, destination_rgb = 0x0302, 1
        elif blend_mode is PetMeshBlendMode.MULTIPLY:
            source_rgb, destination_rgb = 0x0306, 0x0303
        elif blend_mode is PetMeshBlendMode.SCREEN:
            source_rgb, destination_rgb = 1, 0x0301
        else:
            source_rgb, destination_rgb = 0x0302, 0x0303
        gl.glBlendFuncSeparate(source_rgb, destination_rgb, 1, 0x0303)
        _draw_geometry(gl, command.geometry)
        if clip is not None:
            gl.glStencilMask(0xFF)
            gl.glDisable(0x0B90)
        texture.release()
        program.release()

    def _replace_framebuffer_for_current_viewport(self) -> None:
        context = self._make_current()
        candidate: QOpenGLFramebufferObject | None = None
        try:
            candidate = self._create_framebuffer(self._viewport)
            previous = self._framebuffer
            self._framebuffer = candidate
            self._framebuffer_replacement_count += 1
            if previous is not None:
                previous.release()
                delete(previous)
        except Exception:
            if candidate is not None:
                delete(candidate)
            raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED) from None
        finally:
            context.doneCurrent()

    def _make_current(self) -> QOpenGLContext:
        if self._fault_controller.consume(OpenGLMeshFaultPoint.CONTEXT_CURRENT):
            raise OpenGLMeshError(OpenGLMeshSafeCode.CONTEXT_LOST)
        context = self._context
        surface = self._surface
        if context is None or surface is None or not context.isValid():
            raise OpenGLMeshError(OpenGLMeshSafeCode.CONTEXT_LOST)
        if not context.makeCurrent(surface):
            raise OpenGLMeshError(OpenGLMeshSafeCode.CONTEXT_LOST)
        return context

    def _require_owner_thread(self) -> None:
        if get_ident() != self._thread_id or QThread.currentThread() is not self._qt_thread:
            raise OpenGLMeshError(OpenGLMeshSafeCode.WRONG_THREAD)

    def _dispose_failed_initialization(
        self,
        context: QOpenGLContext | None,
        surface: QOffscreenSurface | None,
        program: QOpenGLShaderProgram | None,
    ) -> None:
        if context is not None and surface is not None and context.makeCurrent(surface):
            if self._gpu_scene is not None:
                self._gpu_scene.destroy()
            if self._framebuffer is not None:
                delete(self._framebuffer)
            if program is not None:
                delete(program)
            context.doneCurrent()
        if surface is not None:
            surface.destroy()
            delete(surface)
        if context is not None:
            delete(context)
        self._context = None
        self._surface = None
        self._program = None
        self._gpu_scene = None
        self._framebuffer = None


class OpenGLMeshPetRenderer:
    """Explicit PetRenderer adapter; never selected by default configuration."""

    def __init__(
        self,
        scene: PetMeshScene,
        *,
        device_pixel_ratio: float = 1.0,
        backend: PetMeshImageBackend | None = None,
    ) -> None:
        self._backend = backend or OpenGLTexturedMeshBackend(
            scene,
            device_pixel_ratio=device_pixel_ratio,
        )
        self._viewport = Size(scene.width, scene.height)
        self._closed = False
        self._paused = False
        self._state: PetRendererActionRequest | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def backend(self) -> PetMeshImageBackend:
        return self._backend

    def initialize(self, viewport: Size) -> None:
        if not self._closed:
            self._viewport = viewport
            self._backend.initialize(viewport)

    def set_viewport(self, viewport: Size) -> None:
        if not self._closed:
            self._viewport = viewport
            self._backend.set_viewport(viewport)

    def set_scene(self, scene: PetMeshScene) -> None:
        if not self._closed:
            self._backend.set_scene(scene)

    def set_state(self, request: PetRendererActionRequest) -> None:
        if not self._closed:
            self._state = request

    def update(self, delta_seconds: float) -> None:
        if not math.isfinite(delta_seconds) or delta_seconds < 0.0:
            raise OpenGLMeshError(OpenGLMeshSafeCode.RENDER_FAILED)

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del frame
        if self._closed:
            return
        image = self._backend.render_scene()
        painter.drawImage(
            QRectF(0.0, 0.0, self._viewport.width, self._viewport.height),
            image,
        )

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        if not self._closed and not self._paused:
            self._paused = True
            self._backend.pause()

    def resume(self) -> None:
        if not self._closed and self._paused:
            self._paused = False
            self._backend.resume()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._backend.close()


def _draw_geometry(gl: QOpenGLFunctions, geometry: _GpuGeometry) -> None:
    geometry.vertex_array.bind()
    geometry.index_buffer.bind()
    gl.glDrawElements(0x0004, geometry.index_count, 0x1405, VoidPtr(0))  # type: ignore[arg-type]
    geometry.index_buffer.release()
    geometry.vertex_array.release()


def _validate_viewport(viewport: Size, device_pixel_ratio: float) -> None:
    values = (viewport.width, viewport.height, device_pixel_ratio)
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED)
    if viewport.width * device_pixel_ratio > 4096 or viewport.height * device_pixel_ratio > 4096:
        raise OpenGLMeshError(OpenGLMeshSafeCode.VIEWPORT_FAILED)


def _percentile(values: tuple[float, ...], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]
