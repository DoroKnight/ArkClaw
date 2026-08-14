"""Framework-neutral application model for a Spine 3.8 catalog."""

from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arkclaw.application.pet.pet_geometry import Size
from arkclaw.application.pet.pet_mesh_model import (
    PetMeshBlendMode,
    PetMeshColor,
    PetMeshDrawCommand,
    PetMeshPoint,
    PetMeshScene,
    PetMeshTextureData,
    PetMeshVertex,
    validate_pet_mesh_scene,
)
from arkclaw.infrastructure.spine38_native import (
    Spine38BlendMode,
    Spine38CatalogNativePort,
    Spine38DrawCommand,
    Spine38NativeEventType,
    Spine38NativePort,
)


class Spine38CatalogError(RuntimeError):
    """Fixed application error for an absent or ambiguous exact name."""

    def __init__(self) -> None:
        super().__init__("spine38_animation_not_exactly_once")


class Spine38FrameError(RuntimeError):
    """Fixed renderer-neutral transform or draw-conversion failure."""

    def __init__(self) -> None:
        super().__init__("spine38_frame_invalid")


@dataclass(frozen=True, slots=True)
class Spine38AnimationInfo:
    name: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class Spine38Bounds:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Spine38RootTransform:
    """Root-bone translation in Spine skeleton-local coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise Spine38FrameError


class Spine38PlaybackEventType(StrEnum):
    COMPLETE = "complete"
    LOOP_BOUNDARY = "loop_boundary"


@dataclass(frozen=True, slots=True)
class Spine38PlaybackEvent:
    event_type: Spine38PlaybackEventType
    physical_name: str
    loop_ordinal: int


@dataclass(frozen=True, slots=True)
class Spine38ViewportTransform:
    """One fixed y-up Runtime to y-down logical viewport transform."""

    scale: float
    origin_x: float
    origin_y: float
    viewport: Size
    foot_baseline_y: float

    @classmethod
    def fit(
        cls,
        bounds: Spine38Bounds,
        *,
        viewport: Size,
        foot_baseline_y: float,
        margin: float,
    ) -> Spine38ViewportTransform:
        values = (
            bounds.x,
            bounds.y,
            bounds.width,
            bounds.height,
            viewport.width,
            viewport.height,
            foot_baseline_y,
            margin,
        )
        if (
            not all(math.isfinite(value) for value in values)
            or bounds.width <= 0.0
            or bounds.height <= 0.0
            or margin < 0.0
            or foot_baseline_y <= margin
            or foot_baseline_y > viewport.height
            or viewport.width <= 2.0 * margin
        ):
            raise Spine38FrameError
        scale = min(
            (viewport.width - 2.0 * margin) / bounds.width,
            (foot_baseline_y - margin) / bounds.height,
        )
        if not math.isfinite(scale) or scale <= 0.0:
            raise Spine38FrameError
        bounds_center_x = bounds.x + bounds.width / 2.0
        origin_x = viewport.width / 2.0 - bounds_center_x * scale
        origin_y = foot_baseline_y + bounds.y * scale
        return cls(scale, origin_x, origin_y, viewport, foot_baseline_y)

    def point(self, x: float, y: float) -> PetMeshPoint:
        if not math.isfinite(x) or not math.isfinite(y):
            raise Spine38FrameError
        return PetMeshPoint(
            self.origin_x + x * self.scale,
            self.origin_y - y * self.scale,
        )


@dataclass(frozen=True, slots=True)
class Spine38Catalog:
    animations: tuple[Spine38AnimationInfo, ...]

    def require_animation(self, requested_name: str) -> Spine38AnimationInfo:
        """Return one exact, case-sensitive match without aliases or fallback."""

        matches = tuple(
            animation
            for animation in self.animations
            if animation.name == requested_name
        )
        if len(matches) != 1:
            raise Spine38CatalogError
        return matches[0]


class Spine38Runtime:
    """Own a native catalog port and publish immutable application snapshots."""

    def __init__(
        self,
        native_port: Spine38CatalogNativePort,
        *,
        atlas_size: Size | None = None,
    ) -> None:
        self._native_port = native_port
        self._closed = False
        self.atlas_size = atlas_size
        try:
            self.catalog = Spine38Catalog(
                tuple(
                    Spine38AnimationInfo(
                        animation.name,
                        animation.duration_seconds,
                    )
                    for animation in native_port.catalog()
                )
            )
            self.skins = tuple(native_port.skins())
            native_bounds = native_port.setup_bounds()
            self.setup_bounds = Spine38Bounds(
                native_bounds.x,
                native_bounds.y,
                native_bounds.width,
                native_bounds.height,
            )
        except BaseException:
            self._closed = True
            with suppress(Exception):
                native_port.close()
            raise

    @property
    def closed(self) -> bool:
        return self._closed

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        self._playback_port().set_animation(track, name, loop)

    def mix_animation(
        self,
        track: int,
        name: str,
        loop: bool,
        mix_seconds: float,
    ) -> None:
        self._playback_port().mix_animation(
            track,
            name,
            loop,
            mix_seconds,
        )

    def update(self, delta_seconds: float) -> tuple[Spine38PlaybackEvent, ...]:
        port = self._playback_port()
        port.update(delta_seconds)
        type_map = {
            Spine38NativeEventType.COMPLETE: Spine38PlaybackEventType.COMPLETE,
            Spine38NativeEventType.LOOP_BOUNDARY: (
                Spine38PlaybackEventType.LOOP_BOUNDARY
            ),
        }
        return tuple(
            Spine38PlaybackEvent(
                type_map[event.event_type],
                event.physical_name,
                event.loop_ordinal,
            )
            for event in port.playback_events()
        )

    def clear_track(self, track: int) -> None:
        self._playback_port().clear_track(track)

    def draw_commands(self) -> tuple[Spine38DrawCommand, ...]:
        return self._playback_port().draw_commands()

    def root_transform(self) -> Spine38RootTransform:
        native_transform = self._playback_port().root_transform()
        return Spine38RootTransform(native_transform.x, native_transform.y)

    def visible_bounds(self) -> Spine38Bounds:
        visible_vertices = [
            vertex
            for command in self.draw_commands()
            if any(vertex.a > 0 for vertex in command.vertices)
            for vertex in command.vertices
        ]
        if not visible_vertices:
            raise Spine38FrameError

        xs = tuple(vertex.x for vertex in visible_vertices)
        ys = tuple(vertex.y for vertex in visible_vertices)
        if not all(math.isfinite(value) for value in (*xs, *ys)):
            raise Spine38FrameError

        minimum_x = min(xs)
        maximum_x = max(xs)
        minimum_y = min(ys)
        maximum_y = max(ys)
        width = maximum_x - minimum_x
        height = maximum_y - minimum_y
        if (
            not math.isfinite(width)
            or not math.isfinite(height)
            or width <= 0.0
            or height <= 0.0
        ):
            raise Spine38FrameError
        return Spine38Bounds(
            x=minimum_x,
            y=minimum_y,
            width=width,
            height=height,
        )

    def mesh_scene(
        self,
        transform: Spine38ViewportTransform,
        texture: PetMeshTextureData,
    ) -> PetMeshScene:
        """Convert one native frame without changing Runtime draw order."""

        blend_modes = {
            Spine38BlendMode.NORMAL: PetMeshBlendMode.NORMAL_STRAIGHT,
            Spine38BlendMode.ADDITIVE: PetMeshBlendMode.ADDITIVE,
            Spine38BlendMode.MULTIPLY: PetMeshBlendMode.MULTIPLY,
            Spine38BlendMode.SCREEN: PetMeshBlendMode.SCREEN,
        }
        commands: list[PetMeshDrawCommand] = []
        for native_command in self.draw_commands():
            if native_command.texture_page != 0:
                raise Spine38FrameError
            try:
                blend_mode = blend_modes[native_command.blend_mode]
            except KeyError:
                raise Spine38FrameError from None
            commands.append(
                PetMeshDrawCommand(
                    texture_id=texture.texture_id,
                    vertices=tuple(
                        PetMeshVertex(
                            position=transform.point(vertex.x, vertex.y),
                            u=vertex.u,
                            v=vertex.v,
                            color=PetMeshColor(
                                vertex.r,
                                vertex.g,
                                vertex.b,
                                vertex.a,
                            ),
                        )
                        for vertex in native_command.vertices
                    ),
                    triangle_indices=native_command.indices,
                    draw_order=native_command.draw_order,
                    blend_mode=blend_mode,
                )
            )
        width = _logical_dimension(transform.viewport.width)
        height = _logical_dimension(transform.viewport.height)
        scene = PetMeshScene(
            width,
            height,
            transform.foot_baseline_y,
            (texture,),
            tuple(commands),
        )
        validate_pet_mesh_scene(scene)
        return scene

    def close(self) -> None:
        """Release the owned native port once."""

        if self._closed:
            return
        self._closed = True
        self._native_port.close()

    def _playback_port(self) -> Spine38NativePort:
        if self._closed:
            raise Spine38FrameError
        return cast(Spine38NativePort, self._native_port)


def _logical_dimension(value: float) -> int:
    if not math.isfinite(value) or not value.is_integer():
        raise Spine38FrameError
    result = int(value)
    if result <= 0 or result > 4096:
        raise Spine38FrameError
    return result
