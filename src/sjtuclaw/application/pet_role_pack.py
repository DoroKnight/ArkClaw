"""Immutable manifest and logical animation registry for external role packs."""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from sjtuclaw.application.pet_production_actions import ProductionAction

_PACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class RolePackManifestError(ValueError):
    """Report invalid public manifest data without exposing asset content."""


class MoveDirectionPolicy(StrEnum):
    MIRROR_MOVE = "mirror_move"


@dataclass(frozen=True, slots=True)
class RolePackHashes:
    skeleton: str
    atlas: str
    texture: str

    def __post_init__(self) -> None:
        if any(_SHA256.fullmatch(value) is None for value in self):
            raise RolePackManifestError("expected SHA-256 values are invalid")

    def __iter__(self) -> Iterator[str]:
        return iter((self.skeleton, self.atlas, self.texture))


@dataclass(frozen=True, slots=True)
class RoleAnimationNames:
    relax: str
    move: str | None = None
    sit: str | None = None
    sleep: str | None = None
    special: str | None = None
    interact: str | None = None

    def __post_init__(self) -> None:
        if not self.relax:
            raise RolePackManifestError("Relax binding is required")
        if any(value is not None and not value for value in self.values()):
            raise RolePackManifestError("animation bindings must not be empty")

    def values(self) -> tuple[str | None, ...]:
        return (
            self.relax,
            self.move,
            self.sit,
            self.sleep,
            self.special,
            self.interact,
        )


@dataclass(frozen=True, slots=True)
class RolePackFraming:
    scale: float
    x_offset: float
    foot_baseline: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.scale)
            or self.scale <= 0.0
            or not math.isfinite(self.x_offset)
            or not math.isfinite(self.foot_baseline)
        ):
            raise RolePackManifestError("role-pack framing is invalid")


@dataclass(frozen=True, slots=True)
class RolePackManifest:
    schema_version: int
    pack_id: str
    spine_version: str
    manifest_path: Path
    skeleton_path: Path
    atlas_path: Path
    texture_path: Path
    expected_sha256: RolePackHashes
    animations: RoleAnimationNames
    direction_policy: MoveDirectionPolicy
    framing: RolePackFraming
    texture_page_count: int

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RolePackManifestError("unsupported role-pack schema")
        if _PACK_ID.fullmatch(self.pack_id) is None:
            raise RolePackManifestError("role-pack ID is invalid")
        if self.spine_version != "3.8":
            raise RolePackManifestError("role pack must target Spine 3.8")
        paths = (
            self.manifest_path,
            self.skeleton_path,
            self.atlas_path,
            self.texture_path,
        )
        if any(not path.is_absolute() for path in paths):
            raise RolePackManifestError("role-pack paths must be absolute")
        if self.skeleton_path.suffix.lower() != ".skel":
            raise RolePackManifestError("skeleton path must end in .skel")
        if self.atlas_path.suffix.lower() != ".atlas":
            raise RolePackManifestError("atlas path must end in .atlas")
        if self.texture_path.suffix.lower() != ".png":
            raise RolePackManifestError("texture path must end in .png")
        if self.texture_page_count != 1:
            raise RolePackManifestError("schema 1 requires one texture page")


@dataclass(frozen=True, slots=True)
class ValidatedRolePackIdentity:
    schema_version: int
    pack_id: str
    spine_version: str
    expected_sha256: RolePackHashes
    animations: RoleAnimationNames
    direction_policy: MoveDirectionPolicy
    framing: RolePackFraming

    @classmethod
    def from_manifest(cls, manifest: RolePackManifest) -> ValidatedRolePackIdentity:
        return cls(
            schema_version=manifest.schema_version,
            pack_id=manifest.pack_id,
            spine_version=manifest.spine_version,
            expected_sha256=manifest.expected_sha256,
            animations=manifest.animations,
            direction_policy=manifest.direction_policy,
            framing=manifest.framing,
        )


@dataclass(frozen=True, slots=True)
class RoleAnimationBinding:
    action: ProductionAction
    physical_name: str
    mirrored: bool = False


class AnimationRoleRegistry:
    def __init__(self, bindings: Mapping[ProductionAction, RoleAnimationBinding]) -> None:
        copied = dict(bindings)
        if ProductionAction.RELAX not in copied:
            raise RolePackManifestError("Relax binding is required")
        if any(action is not binding.action for action, binding in copied.items()):
            raise RolePackManifestError("registry keys must match bindings")
        self._bindings = MappingProxyType(copied)

    @classmethod
    def from_manifest(cls, manifest: RolePackManifest) -> AnimationRoleRegistry:
        names = manifest.animations
        bindings = {
            ProductionAction.RELAX: RoleAnimationBinding(
                ProductionAction.RELAX,
                names.relax,
            )
        }
        if names.move is not None:
            bindings[ProductionAction.MOVE_LEFT] = RoleAnimationBinding(
                ProductionAction.MOVE_LEFT,
                names.move,
                mirrored=manifest.direction_policy is MoveDirectionPolicy.MIRROR_MOVE,
            )
            bindings[ProductionAction.MOVE_RIGHT] = RoleAnimationBinding(
                ProductionAction.MOVE_RIGHT,
                names.move,
            )
        for action, physical_name in (
            (ProductionAction.SIT, names.sit),
            (ProductionAction.SLEEP, names.sleep),
            (ProductionAction.SPECIAL, names.special),
            (ProductionAction.INTERACT, names.interact),
        ):
            if physical_name is not None:
                bindings[action] = RoleAnimationBinding(action, physical_name)
        return cls(bindings)

    @property
    def capabilities(self) -> frozenset[ProductionAction]:
        return frozenset(self._bindings)

    def supports(self, action: ProductionAction) -> bool:
        return action in self._bindings

    def resolve(self, action: ProductionAction) -> RoleAnimationBinding:
        return self._bindings[action]

    def require_schwarz_production(self) -> None:
        if self.capabilities != frozenset(ProductionAction):
            raise RolePackManifestError("Schwarz production requires all six animations")
