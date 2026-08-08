"""Minimal renderer-neutral textured-mesh contracts for local experiments."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class PetMeshBlendMode(StrEnum):
    """Alpha convention used by a single draw command."""

    STRAIGHT_ALPHA = "straight_alpha"
    PREMULTIPLIED_ALPHA = "premultiplied_alpha"


class PetMeshValidationCode(StrEnum):
    INVALID_VIEWPORT = "pet_mesh_invalid_viewport"
    INVALID_BASELINE = "pet_mesh_invalid_baseline"
    INVALID_TEXTURE_ID = "pet_mesh_invalid_texture_id"
    INVALID_VERTEX = "pet_mesh_invalid_vertex"
    INVALID_INDEX = "pet_mesh_invalid_index"
    INVALID_CLIP = "pet_mesh_invalid_clip"
    DUPLICATE_TEXTURE = "pet_mesh_duplicate_texture"
    MISSING_TEXTURE = "pet_mesh_missing_texture"


class PetMeshValidationError(ValueError):
    """Fixed, content-free validation failure."""

    _PUBLIC_MESSAGE = "The pet mesh is invalid."

    def __init__(self, code: PetMeshValidationCode) -> None:
        self.code = code
        super().__init__(self._PUBLIC_MESSAGE)


@dataclass(frozen=True, slots=True)
class PetMeshPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PetMeshColor:
    red: int = 255
    green: int = 255
    blue: int = 255
    alpha: int = 255


@dataclass(frozen=True, slots=True)
class PetMeshVertex:
    position: PetMeshPoint
    u: float
    v: float
    color: PetMeshColor = PetMeshColor()


@dataclass(frozen=True, slots=True)
class PetMeshDrawCommand:
    texture_id: str
    vertices: tuple[PetMeshVertex, ...]
    triangle_indices: tuple[int, ...]
    draw_order: int
    blend_mode: PetMeshBlendMode = PetMeshBlendMode.STRAIGHT_ALPHA
    clip_polygon: tuple[PetMeshPoint, ...] | None = None


@dataclass(frozen=True, slots=True)
class PetMeshTextureData:
    """Small in-memory RGBA texture used by the renderer spike."""

    texture_id: str
    width: int
    height: int
    rgba_bytes: bytes
    premultiplied: bool = False


@dataclass(frozen=True, slots=True)
class PetMeshScene:
    width: int
    height: int
    foot_baseline_y: float
    textures: tuple[PetMeshTextureData, ...]
    draw_commands: tuple[PetMeshDrawCommand, ...]


def validate_pet_mesh_scene(scene: PetMeshScene) -> None:
    """Validate only generic mesh invariants, never Spine-specific details."""

    if (
        isinstance(scene.width, bool)
        or isinstance(scene.height, bool)
        or scene.width <= 0
        or scene.height <= 0
        or scene.width > 4096
        or scene.height > 4096
    ):
        raise PetMeshValidationError(PetMeshValidationCode.INVALID_VIEWPORT)
    if not math.isfinite(scene.foot_baseline_y):
        raise PetMeshValidationError(PetMeshValidationCode.INVALID_BASELINE)
    if not 0.0 <= scene.foot_baseline_y <= scene.height:
        raise PetMeshValidationError(PetMeshValidationCode.INVALID_BASELINE)

    texture_ids: set[str] = set()
    for texture in scene.textures:
        if not _valid_texture_id(texture.texture_id):
            raise PetMeshValidationError(PetMeshValidationCode.INVALID_TEXTURE_ID)
        if texture.texture_id in texture_ids:
            raise PetMeshValidationError(PetMeshValidationCode.DUPLICATE_TEXTURE)
        texture_ids.add(texture.texture_id)
        if (
            isinstance(texture.width, bool)
            or isinstance(texture.height, bool)
            or texture.width <= 0
            or texture.height <= 0
            or texture.width > 4096
            or texture.height > 4096
            or len(texture.rgba_bytes) != texture.width * texture.height * 4
        ):
            raise PetMeshValidationError(PetMeshValidationCode.INVALID_VIEWPORT)

    for command in scene.draw_commands:
        if command.texture_id not in texture_ids:
            raise PetMeshValidationError(PetMeshValidationCode.MISSING_TEXTURE)
        if len(command.vertices) < 3:
            raise PetMeshValidationError(PetMeshValidationCode.INVALID_VERTEX)
        for vertex in command.vertices:
            if not all(
                math.isfinite(value)
                for value in (
                    vertex.position.x,
                    vertex.position.y,
                    vertex.u,
                    vertex.v,
                )
            ) or not _valid_color(vertex.color):
                raise PetMeshValidationError(PetMeshValidationCode.INVALID_VERTEX)
        if (
            len(command.triangle_indices) == 0
            or len(command.triangle_indices) % 3 != 0
            or any(
                isinstance(index, bool) or index < 0 or index >= len(command.vertices)
                for index in command.triangle_indices
            )
        ):
            raise PetMeshValidationError(PetMeshValidationCode.INVALID_INDEX)
        if command.clip_polygon is not None:
            _validate_convex_clip_polygon(scene, command.clip_polygon)


def sorted_draw_commands(
    scene: PetMeshScene,
) -> tuple[PetMeshDrawCommand, ...]:
    """Return a stable slot-like draw order without mutating the scene."""

    return tuple(
        command
        for _, command in sorted(
            enumerate(scene.draw_commands),
            key=lambda item: (item[1].draw_order, item[0]),
        )
    )


def _valid_texture_id(value: str) -> bool:
    return (
        0 < len(value) <= 64
        and value[0].isalnum()
        and all(character.isalnum() or character in "._-" for character in value)
    )


def _valid_color(color: PetMeshColor) -> bool:
    return all(
        not isinstance(channel, bool) and 0 <= channel <= 255
        for channel in (color.red, color.green, color.blue, color.alpha)
    )


def _validate_convex_clip_polygon(
    scene: PetMeshScene,
    points: tuple[PetMeshPoint, ...],
) -> None:
    """Accept bounded convex clips; the OpenGL backend uses a triangle fan."""

    if len(points) < 3:
        raise PetMeshValidationError(PetMeshValidationCode.INVALID_CLIP)
    if any(
        not math.isfinite(point.x)
        or not math.isfinite(point.y)
        or point.x < 0.0
        or point.y < 0.0
        or point.x > scene.width
        or point.y > scene.height
        for point in points
    ):
        raise PetMeshValidationError(PetMeshValidationCode.INVALID_CLIP)

    winding = 0
    count = len(points)
    for index in range(count):
        first = points[index]
        second = points[(index + 1) % count]
        third = points[(index + 2) % count]
        cross = (second.x - first.x) * (third.y - second.y) - (
            second.y - first.y
        ) * (third.x - second.x)
        if math.isclose(cross, 0.0, abs_tol=1e-9):
            raise PetMeshValidationError(PetMeshValidationCode.INVALID_CLIP)
        direction = 1 if cross > 0.0 else -1
        if winding == 0:
            winding = direction
        elif winding != direction:
            raise PetMeshValidationError(PetMeshValidationCode.INVALID_CLIP)
