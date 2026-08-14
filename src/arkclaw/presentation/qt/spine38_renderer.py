"""Opt-in Qt renderer for one verified Spine 3.8 idle animation."""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from typing import Protocol, cast

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from arkclaw.application.pet_animation import PetRenderFrame
from arkclaw.application.pet_geometry import Point, Rect, Size
from arkclaw.application.pet_mesh_model import (
    PetMeshDrawCommand,
    PetMeshPoint,
    PetMeshScene,
    PetMeshTextureData,
    PetMeshTextureFilter,
    PetMeshValidationError,
    PetMeshVertex,
)
from arkclaw.application.pet_render_layout import (
    PetBodyTransform,
    PetRenderLayout,
    PetRenderLayoutFailure,
    PetRenderLayoutQuality,
    PetRenderSurfaceMode,
    RenderContainmentPolicy,
    RolePackRenderProfile,
    plan_pet_render_layout,
    project_action_envelope,
)
from arkclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
)
from arkclaw.application.pet_role_pack import RolePackFraming
from arkclaw.application.pet_state import PetFacing
from arkclaw.application.spine38_runtime import (
    Spine38Bounds,
    Spine38Catalog,
    Spine38FrameError,
    Spine38ViewportTransform,
)
from arkclaw.presentation.qt.pet_mesh_opengl_renderer import (
    OpenGLTexturedMeshBackend,
    PetMeshImageBackend,
)

_VIEWPORT = Size(160, 180)
_FOOT_BASELINE_Y = 180.0
_BODY_TARGET_HEIGHT = 162.0
_BODY_MIN_HEIGHT = 153.0
_BODY_MAX_HEIGHT = 171.0
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
        render_profile: RolePackRenderProfile | None = None,
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
        self._render_profile = render_profile
        self._backend: PetMeshImageBackend | None = None
        self._transform: Spine38ViewportTransform | None = None
        self._texture: PetMeshTextureData | None = None
        self._initialized = False
        self._paused = False
        self._closed = False
        self._device_pixel_ratio = 1.0
        self._facing = PetFacing.RIGHT
        self._request = PetRendererActionRequest(
            PetRendererAction.IDLE,
            PetFacing.RIGHT,
            True,
            0.0,
        )
        self._body_transform: Spine38ViewportTransform | None = None
        self._render_layout: PetRenderLayout | None = None
        self._layout_explicit = False
        self._surface_size = _VIEWPORT
        self._render_generation = 0

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def render_generation(self) -> int:
        return self._render_generation

    @property
    def device_pixel_ratio(self) -> float:
        return self._device_pixel_ratio

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
            self._body_transform = transform
            self._render_layout = PetRenderLayout(
                PetRenderSurfaceMode.BODY,
                Rect(0.0, 0.0, _VIEWPORT.width, _VIEWPORT.height),
                Point(0.0, 0.0),
                Point(0.0, 0.0),
                0.0,
                self._facing,
                1.0,
                PetRenderLayoutQuality.FULL_SCALE,
            )
            scene = self._runtime.mesh_scene(transform, texture)
            if self._facing is PetFacing.LEFT:
                scene = _mirror_scene(scene, mirror_axis_x=_VIEWPORT.width / 2.0)
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
        self._require_open()
        if (
            request.action,
            request.facing,
            request.loop,
        ) != (
            self._request.action,
            self._request.facing,
            self._request.loop,
        ):
            self._render_generation += 1
        self._request = request
        self._facing = request.facing

    def plan_layout(
        self,
        body_rect: Rect,
        workspace: Rect,
        device_pixel_ratio: float,
        *,
        display: Rect | None = None,
    ) -> PetRenderLayout | PetRenderLayoutFailure:
        """Plan the current renderer-neutral action for one active workspace."""

        self._require_open()
        profile = self._render_profile
        transform = self._body_transform
        if profile is None or transform is None:
            raise Spine38RendererError(Spine38RendererCode.RUNTIME_FAILED)
        sampled = profile.sampled_action_bounds.get(self._request.action)
        if sampled is None:
            sampled = profile.sampled_action_bounds.get(PetRendererAction.IDLE)
        if sampled is None:
            raise Spine38RendererError(Spine38RendererCode.RUNTIME_FAILED)
        envelope = project_action_envelope(
            sampled_bounds=sampled,
            body_transform=PetBodyTransform(
                transform.scale,
                transform.origin_x,
                transform.origin_y,
                _VIEWPORT.width / 2.0,
            ),
        )
        return plan_pet_render_layout(
            body_rect=body_rect,
            workspace=workspace,
            display=display,
            envelope=envelope,
            preferred_facing=self._request.facing,
            policy=(
                RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS
                if self._request.action is PetRendererAction.SITTING
                else (
                    RenderContainmentPolicy.FULL_SAMPLED_BOUNDS
                    if self._request.action is PetRendererAction.SPECIAL
                    else RenderContainmentPolicy.BODY_PRIORITY
                )
            ),
            device_pixel_ratio=device_pixel_ratio,
        )

    def set_render_layout(self, layout: PetRenderLayout) -> None:
        """Install one already-planned immutable composition."""

        self._require_open()
        if not self._initialized or self._backend is None:
            raise Spine38RendererError(Spine38RendererCode.RUNTIME_FAILED)
        surface_size = Size(
            layout.surface_rect.width,
            layout.surface_rect.height,
        )
        if surface_size != self._surface_size:
            try:
                self._backend.set_viewport(surface_size)
            except Exception:
                raise Spine38RendererError(
                    Spine38RendererCode.OPENGL_FAILED
                ) from None
        self._surface_size = surface_size
        self._render_layout = layout
        self._layout_explicit = True
        self._transform = self._transform_for_layout(layout)

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
            layout = self._render_layout
            facing = (
                self._facing
                if layout is None or not self._layout_explicit
                else layout.effective_facing
            )
            if facing is PetFacing.LEFT:
                mirror_axis = (
                    _VIEWPORT.width / 2.0
                    if layout is None
                    else layout.body_window_offset.x + _VIEWPORT.width / 2.0
                )
                scene = _mirror_scene(scene, mirror_axis_x=mirror_axis)
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
        layout = self._render_layout
        if layout is not None and layout.mode is PetRenderSurfaceMode.OVERFLOW:
            return
        self.render_surface(painter)

    def render_surface(self, painter: QPainter) -> QImage:
        """Draw the prepared scene into its owning BODY or OVERFLOW surface."""

        self._require_open()
        if not self._initialized or self._backend is None:
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED)
        try:
            image = self._backend.render_scene()
            painter.drawImage(
                QRectF(0.0, 0.0, self._surface_size.width, self._surface_size.height),
                image,
            )
            return image
        except Exception:
            raise Spine38RendererError(Spine38RendererCode.OPENGL_FAILED) from None

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        idle = action is PetRendererAction.IDLE
        supported = (
            idle
            if self._render_profile is None
            else action in self._render_profile.sampled_action_bounds
        )
        return PetRendererAnimationCapability(
            animation_supported=supported,
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
        values = (bounds.x, bounds.y, bounds.width, bounds.height)
        if (
            not all(math.isfinite(value) for value in values)
            or bounds.width <= 0.0
            or bounds.height <= 0.0
            or not 178.0 <= self._framing.foot_baseline <= viewport.height
        ):
            raise Spine38FrameError
        target_height = _BODY_TARGET_HEIGHT * self._framing.scale
        if not _BODY_MIN_HEIGHT <= target_height <= _BODY_MAX_HEIGHT:
            raise Spine38FrameError
        scale = target_height / bounds.height
        center_x = bounds.x + bounds.width / 2.0
        origin_x = (
            viewport.width / 2.0
            - center_x * scale
            + self._framing.x_offset
        )
        left = origin_x + bounds.x * scale
        right = left + bounds.width * scale
        top = self._framing.foot_baseline - target_height
        if left < 0.0 or right > viewport.width or top < 0.0:
            raise Spine38FrameError
        return Spine38ViewportTransform(
            scale,
            origin_x,
            self._framing.foot_baseline + bounds.y * scale,
            viewport,
            self._framing.foot_baseline,
        )

    def _transform_for_layout(
        self,
        layout: PetRenderLayout,
    ) -> Spine38ViewportTransform:
        base = self._body_transform
        if base is None:
            raise Spine38RendererError(Spine38RendererCode.RUNTIME_FAILED)
        scale_multiplier = layout.scale_multiplier
        offset = layout.body_window_offset
        origin_y = (
            offset.y
            + _FOOT_BASELINE_Y
            + scale_multiplier
            * (
                base.origin_y
                - layout.ground_correction
                - _FOOT_BASELINE_Y
            )
        )
        return Spine38ViewportTransform(
            base.scale * scale_multiplier,
            offset.x + base.origin_x,
            origin_y,
            self._surface_size,
            offset.y + _FOOT_BASELINE_Y,
        )


def _mirror_scene(
    scene: PetMeshScene,
    *,
    mirror_axis_x: float | None = None,
) -> PetMeshScene:
    """Reflect logical positions while retaining UVs and draw semantics."""

    def mirror_point(point: PetMeshPoint) -> PetMeshPoint:
        axis = scene.width / 2.0 if mirror_axis_x is None else mirror_axis_x
        return PetMeshPoint(2.0 * axis - point.x, point.y)

    return PetMeshScene(
        width=scene.width,
        height=scene.height,
        foot_baseline_y=scene.foot_baseline_y,
        textures=scene.textures,
        draw_commands=tuple(
            PetMeshDrawCommand(
                texture_id=command.texture_id,
                vertices=tuple(
                    PetMeshVertex(
                        position=mirror_point(vertex.position),
                        u=vertex.u,
                        v=vertex.v,
                        color=vertex.color,
                    )
                    for vertex in command.vertices
                ),
                triangle_indices=command.triangle_indices,
                draw_order=command.draw_order,
                blend_mode=command.blend_mode,
                clip_polygon=(
                    tuple(mirror_point(point) for point in command.clip_polygon)
                    if command.clip_polygon is not None
                    else None
                ),
            )
            for command in scene.draw_commands
        ),
    )
