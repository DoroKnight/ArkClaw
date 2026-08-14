"""Fail-closed composition of one external Spine 3.8 production role pack."""

from __future__ import annotations

import json
import math
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from arkclaw.application.pet.pet_autonomous_scheduler import AutonomousActionScheduler
from arkclaw.application.pet.pet_external_assets import ExternalPetAssetLoader
from arkclaw.application.pet.pet_geometry import Rect, Size
from arkclaw.application.pet.pet_mesh_model import PetMeshTextureFilter
from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_render_layout import (
    PetBodyTransform,
    PetRenderLayoutFailure,
    PetRenderLayoutFailureReason,
    RenderContainmentPolicy,
    RolePackRenderProfile,
    plan_pet_render_layout,
    project_action_envelope,
)
from arkclaw.application.pet.pet_renderer_model import (
    ExternalPetAssetDescriptor,
    ExternalPetAssetHashes,
    PetRendererAction,
)
from arkclaw.application.pet.pet_role_calibration import (
    RootMotionClassification,
    classify_root_motion_samples,
)
from arkclaw.application.pet.pet_role_pack import (
    AnimationRoleRegistry,
    MoveDirectionPolicy,
    RoleAnimationNames,
    RolePackFraming,
    RolePackHashes,
    RolePackManifest,
    build_track0_animation_registry,
)
from arkclaw.application.pet.pet_state import PetFacing
from arkclaw.application.pet.pet_track0 import PetTrack0Controller
from arkclaw.application.pet.spine38_runtime import (
    Spine38Bounds,
    Spine38RootTransform,
    Spine38Runtime,
)
from arkclaw.infrastructure.pet_external_asset_filesystem import (
    WindowsExternalPetAssetFilesystem,
)
from arkclaw.infrastructure.spine38_native import (
    Spine38NativeLibrary,
    Spine38TextureFilter,
)
from arkclaw.presentation.qt.pet.spine38_player import Spine38AnimationPlayer
from arkclaw.presentation.qt.pet.spine38_renderer import Spine38PetRenderer

_MANIFEST_ENV = "ARKCLAW_PET_ROLE_MANIFEST"
_BRIDGE_ENV = "ARKCLAW_SPINE38_BRIDGE_DLL"
_MAX_MANIFEST_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ProductionPetComposition:
    renderer: Spine38PetRenderer
    track0: PetTrack0Controller
    playback_event_source: Spine38AnimationPlayer
    autonomous_scheduler: AutonomousActionScheduler
    role_pack_id: str
    available_actions: frozenset[ProductionAction]
    root_motion: RootMotionClassification


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
        native_filters = native.texture_page_info()
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
        root_motion = _classify_root_motion(
            runtime,
            roles,
            durations,
        )
        session_bounds = _sample_session_bounds(
            runtime,
            roles,
            durations,
            manifest.framing,
        )
        render_profile = _sample_action_profile(
            runtime,
            roles,
            durations,
            session_bounds,
        )
        _preflight_render_profile(render_profile, manifest.framing)
        player = Spine38AnimationPlayer(runtime)
        track0 = PetTrack0Controller(player=player, registry=registry)
        renderer = Spine38PetRenderer(
            runtime,
            bundle.snapshot.texture_bytes,
            asset_owner=bundle,
            advance_runtime=False,
            min_filter=_texture_filter(native_filters.min_filter),
            mag_filter=_texture_filter(native_filters.mag_filter),
            framing=manifest.framing,
            session_bounds=session_bounds,
            render_profile=render_profile,
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
            root_motion,
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


def _texture_filter(value: Spine38TextureFilter) -> PetMeshTextureFilter:
    if value is Spine38TextureFilter.NEAREST:
        return PetMeshTextureFilter.NEAREST
    return PetMeshTextureFilter.LINEAR


def _sample_session_bounds(
    runtime: Spine38Runtime,
    roles: AnimationRoleRegistry,
    durations: dict[ProductionAction, float],
    framing: RolePackFraming | None = None,
) -> Spine38Bounds:
    """Sample every role uniformly and return the Relax body calibration envelope."""

    samples_by_name: dict[str, list[Spine38Bounds]] = {}
    sampled_names: set[str] = set()
    for action in ProductionAction:
        binding = roles.resolve(action)
        if binding.physical_name in sampled_names:
            continue
        sampled_names.add(binding.physical_name)
        samples: list[Spine38Bounds] = []
        samples_by_name[binding.physical_name] = samples
        runtime.set_animation(0, binding.physical_name, True)
        runtime.update(0.0)
        samples.append(runtime.visible_bounds())
        step = durations[action] / 12.0
        for _ in range(11):
            runtime.update(step)
            samples.append(runtime.visible_bounds())
    relax_name = roles.resolve(ProductionAction.RELAX).physical_name
    relax_samples = samples_by_name.get(relax_name)
    if not relax_samples:
        raise ValueError("role_pack_visible_bounds_unavailable")
    relax_bounds = _union_bounds(relax_samples)
    selected_framing = framing or RolePackFraming(1.0, 0.0, 180.0)
    target_height = 162.0 * selected_framing.scale
    if (
        not 153.0 <= target_height <= 171.0
        or not 178.0 <= selected_framing.foot_baseline <= 180.0
    ):
        raise ValueError("role_pack_body_priority_invalid")
    scale = target_height / relax_bounds.height
    center_x = relax_bounds.x + relax_bounds.width / 2.0
    origin_x = 80.0 - center_x * scale + selected_framing.x_offset
    origin_y = selected_framing.foot_baseline + relax_bounds.y * scale
    relax_edges = (
        origin_x + relax_bounds.x * scale,
        origin_x + (relax_bounds.x + relax_bounds.width) * scale,
        origin_y - (relax_bounds.y + relax_bounds.height) * scale,
        origin_y - relax_bounds.y * scale,
    )
    if (
        relax_edges[0] < 0.0
        or relax_edges[1] > 160.0
        or relax_edges[2] < 0.0
        or relax_edges[3] > 180.0
    ):
        raise ValueError("role_pack_body_priority_invalid")
    core_names = {
        roles.resolve(action).physical_name
        for action in (
            ProductionAction.RELAX,
            ProductionAction.MOVE_LEFT,
            ProductionAction.SIT,
            ProductionAction.SLEEP,
        )
    }
    for name in core_names:
        for bounds in samples_by_name[name]:
            values = (bounds.x, bounds.y, bounds.width, bounds.height)
            overlap_width = min(
                bounds.x + bounds.width,
                relax_bounds.x + relax_bounds.width,
            ) - max(bounds.x, relax_bounds.x)
            overlap_height = min(
                bounds.y + bounds.height,
                relax_bounds.y + relax_bounds.height,
            ) - max(bounds.y, relax_bounds.y)
            if (
                not all(math.isfinite(value) for value in values)
                or bounds.width <= 0.0
                or bounds.height <= 0.0
                or overlap_width <= 0.0
                or overlap_height <= 0.0
            ):
                raise ValueError("role_pack_body_priority_invalid")
    return relax_bounds


def _classify_root_motion(
    runtime: Spine38Runtime,
    roles: AnimationRoleRegistry,
    durations: dict[ProductionAction, float],
) -> RootMotionClassification:
    """Observe root translation at 60 Hz before any grounding policy is built."""

    samples_by_action: dict[ProductionAction, tuple[Spine38RootTransform, ...]] = {}
    for action in (
        ProductionAction.RELAX,
        ProductionAction.MOVE_LEFT,
        ProductionAction.SIT,
    ):
        duration = durations[action]
        if not math.isfinite(duration) or duration <= 0.0 or duration > 60.0:
            raise ValueError("role_pack_animation_duration_invalid")
        interval_count = max(1, math.ceil(60.0 * duration))
        if interval_count > 3600:
            raise ValueError("role_pack_sample_allocation_invalid")
        runtime.clear_track(0)
        runtime.set_animation(0, roles.resolve(action).physical_name, False)
        step = duration / interval_count
        samples: list[Spine38RootTransform] = []
        runtime.update(0.0)
        samples.append(runtime.root_transform())
        for _ in range(interval_count):
            runtime.update(step)
            samples.append(runtime.root_transform())
        samples_by_action[action] = tuple(samples)
    return classify_root_motion_samples(samples_by_action)


_RENDERER_ACTIONS_BY_PRODUCTION = {
    ProductionAction.RELAX: (PetRendererAction.IDLE,),
    ProductionAction.MOVE_LEFT: (
        PetRendererAction.WALK_LEFT,
        PetRendererAction.WALK_RIGHT,
    ),
    ProductionAction.MOVE_RIGHT: (
        PetRendererAction.WALK_LEFT,
        PetRendererAction.WALK_RIGHT,
    ),
    ProductionAction.SIT: (PetRendererAction.SITTING,),
    ProductionAction.SLEEP: (PetRendererAction.SLEEP,),
    ProductionAction.SPECIAL: (PetRendererAction.SPECIAL,),
    ProductionAction.INTERACT: (PetRendererAction.INTERACT,),
}


def _sample_action_profile(
    runtime: Spine38Runtime,
    roles: AnimationRoleRegistry,
    durations: dict[ProductionAction, float],
    body_bounds: Spine38Bounds,
) -> RolePackRenderProfile:
    """Build endpoint-inclusive isolated sampled bounds for layout decisions."""

    sampled_by_name: dict[str, Spine38Bounds] = {}
    action_for_name: dict[str, ProductionAction] = {}
    for action in ProductionAction:
        binding = roles.resolve(action)
        action_for_name.setdefault(binding.physical_name, action)
    for physical_name, action in action_for_name.items():
        duration = durations[action]
        if not math.isfinite(duration) or duration <= 0.0 or duration > 60.0:
            raise ValueError("role_pack_animation_duration_invalid")
        interval_count = max(12, math.ceil(60.0 * duration))
        if interval_count > 3600 or interval_count + 1 > 3601:
            raise ValueError("role_pack_sample_allocation_invalid")
        runtime.clear_track(0)
        runtime.set_animation(0, physical_name, False)
        step = duration / interval_count
        samples: list[Spine38Bounds] = []
        runtime.update(0.0)
        samples.append(runtime.visible_bounds())
        for _ in range(interval_count):
            runtime.update(step)
            samples.append(runtime.visible_bounds())
        sampled_by_name[physical_name] = _union_bounds(samples)

    renderer_bounds: dict[PetRendererAction, Spine38Bounds] = {}
    for action in ProductionAction:
        sampled = sampled_by_name[roles.resolve(action).physical_name]
        for renderer_action in _RENDERER_ACTIONS_BY_PRODUCTION[action]:
            renderer_bounds[renderer_action] = sampled
    return RolePackRenderProfile(body_bounds, renderer_bounds)


def _preflight_render_profile(
    profile: RolePackRenderProfile,
    framing: RolePackFraming,
) -> None:
    """Reject only candidate-static layout failures before publication."""

    target_height = 162.0 * framing.scale
    scale = target_height / profile.body_bounds.height
    center_x = profile.body_bounds.x + profile.body_bounds.width / 2.0
    transform = PetBodyTransform(
        scale,
        80.0 - center_x * scale + framing.x_offset,
        framing.foot_baseline + profile.body_bounds.y * scale,
        80.0,
    )
    static_failures = {
        PetRenderLayoutFailureReason.BODY_VERTICAL_INFEASIBLE,
        PetRenderLayoutFailureReason.SPECIAL_EFFECT_FLOOR_INFEASIBLE,
        PetRenderLayoutFailureReason.LOGICAL_RESOURCE_LIMIT_EXCEEDED,
    }
    body_rect = Rect(0.0, 0.0, 160.0, 180.0)
    workspace = Rect(-2048.0, -2048.0, 4096.0, 4096.0)
    for action, sampled in profile.sampled_action_bounds.items():
        result = plan_pet_render_layout(
            body_rect=body_rect,
            workspace=workspace,
            envelope=project_action_envelope(
                sampled_bounds=sampled,
                body_transform=transform,
            ),
            preferred_facing=PetFacing.RIGHT,
            policy=(
                RenderContainmentPolicy.FULL_SAMPLED_BOUNDS
                if action is PetRendererAction.SPECIAL
                else RenderContainmentPolicy.BODY_PRIORITY
            ),
            device_pixel_ratio=1.0,
        )
        if isinstance(result, PetRenderLayoutFailure) and result.reason in static_failures:
            raise ValueError(result.reason.value)


def _union_bounds(samples: list[Spine38Bounds]) -> Spine38Bounds:
    left = min(item.x for item in samples)
    bottom = min(item.y for item in samples)
    right = max(item.x + item.width for item in samples)
    top = max(item.y + item.height for item in samples)
    bounds = Spine38Bounds(left, bottom, right - left, top - bottom)
    if (
        not all(
            math.isfinite(value)
            for value in (bounds.x, bounds.y, bounds.width, bounds.height)
        )
        or bounds.width <= 0.0
        or bounds.height <= 0.0
    ):
        raise ValueError("role_pack_body_priority_invalid")
    return bounds
