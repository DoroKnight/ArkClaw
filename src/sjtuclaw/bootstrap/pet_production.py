"""Fail-closed composition of one external Spine 3.8 production role pack."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sjtuclaw.application.pet_autonomous_scheduler import AutonomousActionScheduler
from sjtuclaw.application.pet_external_assets import ExternalPetAssetLoader
from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_production_actions import ProductionAction
from sjtuclaw.application.pet_renderer_model import (
    ExternalPetAssetDescriptor,
    ExternalPetAssetHashes,
)
from sjtuclaw.application.pet_role_pack import (
    AnimationRoleRegistry,
    MoveDirectionPolicy,
    RoleAnimationNames,
    RolePackFraming,
    RolePackHashes,
    RolePackManifest,
    build_track0_animation_registry,
)
from sjtuclaw.application.pet_track0 import PetTrack0Controller
from sjtuclaw.application.spine38_runtime import Spine38Runtime
from sjtuclaw.infrastructure.pet_external_asset_filesystem import (
    WindowsExternalPetAssetFilesystem,
)
from sjtuclaw.infrastructure.spine38_native import Spine38NativeLibrary
from sjtuclaw.presentation.qt.spine38_player import Spine38AnimationPlayer
from sjtuclaw.presentation.qt.spine38_renderer import Spine38PetRenderer

_MANIFEST_ENV = "SJTUCLAW_PET_ROLE_MANIFEST"
_BRIDGE_ENV = "SJTUCLAW_SPINE38_BRIDGE_DLL"
_MAX_MANIFEST_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ProductionPetComposition:
    renderer: Spine38PetRenderer
    track0: PetTrack0Controller
    playback_event_source: Spine38AnimationPlayer
    autonomous_scheduler: AutonomousActionScheduler
    role_pack_id: str
    available_actions: frozenset[ProductionAction]


def create_optional_production_pet_composition() -> ProductionPetComposition | None:
    """Return a complete pack or ``None`` without weakening placeholder startup."""

    manifest_value = os.environ.get(_MANIFEST_ENV)
    bridge_value = os.environ.get(_BRIDGE_ENV)
    if manifest_value is None or bridge_value is None:
        return None
    bundle = None
    native = None
    runtime = None
    renderer = None
    try:
        manifest = load_role_pack_manifest(Path(manifest_value))
        roles = AnimationRoleRegistry.from_manifest(manifest)
        roles.require_schwarz_production()
        descriptor = _asset_descriptor(manifest)
        loaded = ExternalPetAssetLoader(
            WindowsExternalPetAssetFilesystem()
        ).load(descriptor)
        if not loaded.succeeded or loaded.bundle is None:
            return None
        bundle = loaded.bundle
        native = Spine38NativeLibrary.from_dll_path(bridge_value).create(
            bundle.snapshot
        )
        runtime = Spine38Runtime(
            native,
            atlas_size=Size(
                bundle.metadata.atlas.page_width,
                bundle.metadata.atlas.page_height,
            ),
        )
        native = None
        durations = {
            action: runtime.catalog.require_animation(
                roles.resolve(action).physical_name
            ).duration_seconds
            for action in roles.capabilities
        }
        registry = build_track0_animation_registry(
            roles,
            source_durations=durations,
        )
        player = Spine38AnimationPlayer(runtime)
        track0 = PetTrack0Controller(player=player, registry=registry)
        renderer = Spine38PetRenderer(
            runtime,
            bundle.snapshot.texture_bytes,
            asset_owner=bundle,
            advance_runtime=False,
        )
        runtime = None
        bundle = None
        return ProductionPetComposition(
            renderer,
            track0,
            player,
            AutonomousActionScheduler(),
            manifest.pack_id,
            roles.capabilities,
        )
    except Exception:
        if renderer is not None:
            with suppress(Exception):
                renderer.close()
        if runtime is not None:
            with suppress(Exception):
                runtime.close()
        if native is not None:
            with suppress(Exception):
                native.close()
        if bundle is not None:
            with suppress(Exception):
                bundle.close()
        return None


def load_role_pack_manifest(path: Path) -> RolePackManifest:
    """Parse the frozen schema-1 JSON form without scanning for assets."""

    if not path.is_absolute() or not path.is_file():
        raise ValueError("role_pack_manifest_invalid")
    encoded = path.read_bytes()
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise ValueError("role_pack_manifest_invalid")
    try:
        value = cast(dict[str, Any], json.loads(encoded.decode("utf-8")))
        assets = cast(dict[str, str], value["assets"])
        hashes = cast(dict[str, str], value["expected_sha256"])
        animations = cast(dict[str, str | None], value["animations"])
        framing = cast(dict[str, float], value["framing"])
        relax = animations["relax"]
        if not isinstance(relax, str):
            raise ValueError
        return RolePackManifest(
            schema_version=int(value["schema_version"]),
            pack_id=str(value["pack_id"]),
            spine_version=str(value["spine_version"]),
            manifest_path=path,
            skeleton_path=Path(assets["skeleton"]),
            atlas_path=Path(assets["atlas"]),
            texture_path=Path(assets["texture"]),
            expected_sha256=RolePackHashes(
                hashes["skeleton"],
                hashes["atlas"],
                hashes["texture"],
            ),
            animations=RoleAnimationNames(
                relax,
                animations.get("move"),
                animations.get("sit"),
                animations.get("sleep"),
                animations.get("special"),
                animations.get("interact"),
            ),
            direction_policy=MoveDirectionPolicy(str(value["direction_policy"])),
            framing=RolePackFraming(
                float(framing["scale"]),
                float(framing["x_offset"]),
                float(framing["foot_baseline"]),
            ),
            texture_page_count=int(value["texture_page_count"]),
        )
    except Exception:
        raise ValueError("role_pack_manifest_invalid") from None


def _asset_descriptor(manifest: RolePackManifest) -> ExternalPetAssetDescriptor:
    parents = {
        path.parent
        for path in (
            manifest.skeleton_path,
            manifest.atlas_path,
            manifest.texture_path,
        )
    }
    if len(parents) != 1:
        raise ValueError("role_pack_assets_must_share_one_root")
    root = parents.pop()
    return ExternalPetAssetDescriptor(
        opaque_asset_id=manifest.pack_id,
        asset_root=str(root),
        skeleton_filename=manifest.skeleton_path.name,
        atlas_filename=manifest.atlas_path.name,
        texture_filename=manifest.texture_path.name,
        expected_sha256=ExternalPetAssetHashes(
            manifest.expected_sha256.skeleton,
            manifest.expected_sha256.atlas,
            manifest.expected_sha256.texture,
        ),
    )
