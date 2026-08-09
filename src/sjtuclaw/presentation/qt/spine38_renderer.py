"""Opt-in Qt renderer for one verified Spine 3.8 idle animation."""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from typing import Protocol, cast

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from sjtuclaw.application.pet_animation import PetRenderFrame
from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_mesh_model import (
    PetMeshScene,
    PetMeshTextureData,
    PetMeshTextureFilter,
    PetMeshValidationError,
)
from sjtuclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
)
from sjtuclaw.application.pet_role_pack import RolePackFraming
from sjtuclaw.application.spine38_runtime import (
    Spine38Bounds,
    Spine38Catalog,
    Spine38FrameError,
    Spine38ViewportTransform,
)
from sjtuclaw.presentation.qt.pet_mesh_opengl_renderer import (
    OpenGLTexturedMeshBackend,
    PetMeshImageBackend,
)

_VIEWPORT = Size(160, 180)
_FOOT_BASELINE_Y = 176.0
_MARGIN = 4.0
_TEXTURE_ID = "spine38-page-0"


class Spine38RendererCode(StrEnum):
    CATALOG_INVALID = "spine38_renderer_catalog_invalid"
    TEXTURE_INVALID = "spine38_renderer_texture_invalid"
    VIEWPORT_INVALID = "spine38_renderer_viewport_invalid"
    RUNTIME_FAILED = "spine38_renderer_runtime_failed"
    MESH_INVALID = "spine38_renderer_mesh_invalid"
    OPENGL_FAILED = "spine38_renderer_opengl_failed"
    CLOSE_FAILED = "spine38_renderer_close_failed"
    CLOSED = "spine38_renderer_closed"


class Spine38RendererError(RuntimeError):
    """Fixed, content-free failure contained by ``SafePetRenderer``."""

    _PUBLIC_MESSAGE = "The Spine pet renderer failed safely."

    def __init__(self, code: Spine38RendererCode) -> None:
        self.code = code
        super().__init__(self._PUBLIC_MESSAGE)


class _Spine38RenderRuntime(Protocol):
    catalog: Spine38Catalog
    setup_bounds: Spine38Bounds
    atlas_size: Size | None

    def set_animation(self, track: int, name: str, loop: bool) -> None: ...

    def update(self, delta_seconds: float) -> object: ...

    def visible_bounds(self) -> Spine38Bounds: ...

    def mesh_scene(
        self,
        transform: Spine38ViewportTransform,
        texture: PetMeshTextureData,
    ) -> PetMeshScene: ...

    def close(self) -> None: ...


class _Closeable(Protocol):
    def close(self) -> None: ...


BackendFactory = Callable[[PetMeshScene], PetMeshImageBackend]


class Spine38PetRenderer:
    """Render the exact looping ``Relax`` animation in one existing window."""

    foot_baseline_y = _FOOT_BASELINE_Y

    def __init__(
        self,
        runtime: _Spine38RenderRuntime,
        verified_texture_bytes: bytes,
        *,
        asset_owner: _Closeable | None = None,
        backend_factory: BackendFactory = OpenGLTexturedMeshBackend,
        advance_runtime: bool = True,
        min_filter: PetMeshTextureFilter = PetMeshTextureFilter.LINEAR,
        mag_filter: PetMeshTextureFilter = PetMeshTextureFilter.LINEAR,
        framing: RolePackFraming | None = None,
        session_bounds: Spine38Bounds | None = None,
    ) -> None:
        self._runtime = runtime
        self._texture_bytes = bytes(verified_texture_bytes)
        self._asset_owner = asset_owner
        self._backend_factory = backend_factory
        self._advance_runtime = advance_runtime
        self._min_filter = min_filter
        self._mag_filter = mag_filter
        self._framing = framing or RolePackFraming(1.0, 0.0, _FOOT_BASELINE_Y)
        self.foot_baseline_y = self._framing.foot_baseline
        self._session_bounds = session_bounds
        self._backend: PetMeshImageBackend | None = None
        self._transform: Spine38ViewportTransform | None = None
        self._texture: PetMeshTextureData | None = None
        self._initialized = False
        self._paused = False
        self._closed = False
        self._device_pixel_ratio = 1.0

    @property
    def closed(self) -> bool:
        return self._closed

    def initialize(self, viewport: Size) -> None:
        self._require_open()
        self._require_fixed_viewport(viewport)
        if self._initialized:
            return
        try:
            self._runtime.catalog.require_animation("Relax")
        except Exception:
            raise Spine38RendererError(
                Spine38RendererCode.CATALOG_INVALID
            ) from None
        texture = self._decode_texture()
        try:
            self._runtime.set_animation(0, "Relax", True)
            self._runtime.update(0.0)
            transform = self._fixed_transform(
                self._session_bounds or self._runtime.visible_bounds(),
                viewport,
            )
            scene = self._runtime.mesh_scene(transform, texture)
        except (PetMeshValidationError, Spine38FrameError):
            raise Spine38RendererError(Spine38RendererCode.MESH_INVALID) from None
        except Exception:
            raise Spine38RendererError(
                Spine38RendererCode.RUNTIME_FAILED
            ) from None
        backend: PetMeshImageBackend | None = None
        try:
            backend = self._backend_factory(scene)
            set_ratio = getattr(backend, "set_device_pixel_ratio", None)
            if set_ratio is not None:
                set_ratio(self._device_pixel_ratio)
            backend.initialize(viewport)
        except Exception:
            if backend is not None:
                with suppress(Exception):
                    backend.close()
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED) from None
        self._transform = transform
        self._texture = texture
        self._backend = backend
        self._initialized = True

    def set_viewport(self, viewport: Size) -> None:
        self._require_open()
        self._require_fixed_viewport(viewport)
        if self._backend is None:
            return
        try:
            self._backend.set_viewport(viewport)
        except Exception:
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED) from None

    def set_device_pixel_ratio(self, value: float) -> None:
        self._require_open()
        if not math.isfinite(value) or value <= 0.0:
            raise Spine38RendererError(Spine38RendererCode.VIEWPORT_INVALID)
        if math.isclose(value, self._device_pixel_ratio):
            return
        backend = self._backend
        if backend is not None:
            set_ratio = getattr(backend, "set_device_pixel_ratio", None)
            if set_ratio is None:
                raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED)
            try:
                set_ratio(value)
            except Exception:
                raise Spine38RendererError(
                    Spine38RendererCode.OPENGL_FAILED
                ) from None
        self._device_pixel_ratio = value

    def set_state(self, request: PetRendererActionRequest) -> None:
        del request
        self._require_open()

    def update(self, delta_seconds: float) -> None:
        self._require_open()
        if self._paused:
            return
        if (
            not self._initialized
            or self._backend is None
            or self._transform is None
            or self._texture is None
            or not math.isfinite(delta_seconds)
            or delta_seconds < 0.0
        ):
            raise Spine38RendererError(Spine38RendererCode.RUNTIME_FAILED)
        try:
            if self._advance_runtime:
                self._runtime.update(delta_seconds)
            scene = self._runtime.mesh_scene(self._transform, self._texture)
        except (PetMeshValidationError, Spine38FrameError):
            raise Spine38RendererError(Spine38RendererCode.MESH_INVALID) from None
        except Exception:
            raise Spine38RendererError(
                Spine38RendererCode.RUNTIME_FAILED
            ) from None
        try:
            self._backend.set_scene(scene)
        except Exception:
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED) from None

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del frame
        self._require_open()
        if not self._initialized or self._backend is None:
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED)
        try:
            image = self._backend.render_scene()
            painter.drawImage(
                QRectF(0.0, 0.0, _VIEWPORT.width, _VIEWPORT.height),
                image,
            )
        except Exception:
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED) from None

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        idle = action is PetRendererAction.IDLE
        return PetRendererAnimationCapability(
            animation_supported=idle,
            loop=True,
            duration_seconds=None,
            interruptible=True,
            fallback_animation=PetRendererAction.IDLE,
        )

    def pause(self) -> None:
        self._require_open()
        if self._paused:
            return
        self._paused = True
        if self._backend is not None:
            try:
                self._backend.pause()
            except Exception:
                raise Spine38RendererError(
                    Spine38RendererCode.OPENGL_FAILED
                ) from None

    def resume(self) -> None:
        self._require_open()
        if not self._paused:
            return
        self._paused = False
        if self._backend is not None:
            try:
                self._backend.resume()
            except Exception:
                raise Spine38RendererError(
                    Spine38RendererCode.OPENGL_FAILED
                ) from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failed = False
        resources: tuple[_Closeable | None, ...] = (
            self._backend,
            self._runtime,
            self._asset_owner,
        )
        self._backend = None
        self._asset_owner = None
        for resource in resources:
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                failed = True
        if failed:
            raise Spine38RendererError(Spine38RendererCode.CLOSE_FAILED)

    def _decode_texture(self) -> PetMeshTextureData:
        expected = self._runtime.atlas_size
        try:
            image = QImage.fromData(
                self._texture_bytes,
                cast(bytes, "PNG"),
            )
            if image.isNull() or expected is None:
                raise ValueError
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            if (
                image.isNull()
                or image.width() != expected.width
                or image.height() != expected.height
                or image.bytesPerLine() != image.width() * 4
            ):
                raise ValueError
            rgba_bytes = bytes(image.constBits()[: image.sizeInBytes()])
            if len(rgba_bytes) != image.width() * image.height() * 4:
                raise ValueError
            return PetMeshTextureData(
                _TEXTURE_ID,
                image.width(),
                image.height(),
                rgba_bytes,
                premultiplied=False,
                min_filter=self._min_filter,
                mag_filter=self._mag_filter,
            )
        except Exception:
            raise Spine38RendererError(
                Spine38RendererCode.TEXTURE_INVALID
            ) from None

    def _require_open(self) -> None:
        if self._closed:
            raise Spine38RendererError(Spine38RendererCode.CLOSED)

    @staticmethod
    def _require_fixed_viewport(viewport: Size) -> None:
        if viewport != _VIEWPORT:
            raise Spine38RendererError(Spine38RendererCode.VIEWPORT_INVALID)

    def _fixed_transform(
        self,
        bounds: Spine38Bounds,
        viewport: Size,
    ) -> Spine38ViewportTransform:
        base = Spine38ViewportTransform.fit(
            bounds,
            viewport=viewport,
            foot_baseline_y=self._framing.foot_baseline,
            margin=_MARGIN,
        )
        scale = base.scale * self._framing.scale
        center_x = bounds.x + bounds.width / 2.0
        return Spine38ViewportTransform(
            scale,
            viewport.width / 2.0
            - center_x * scale
            + self._framing.x_offset,
            self._framing.foot_baseline + bounds.y * scale,
            viewport,
            self._framing.foot_baseline,
        )
