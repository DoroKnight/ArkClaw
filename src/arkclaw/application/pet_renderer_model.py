"""Framework-free contracts for replaceable desktop-pet renderers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PureWindowsPath

from arkclaw.application.pet_animation import PetRenderFrame
from arkclaw.application.pet_state import (
    PetActivityState,
    PetBehaviorState,
    PetFacing,
    PetLifecycleState,
    PetMotionState,
)


class PetRendererKind(StrEnum):
    PLACEHOLDER = "placeholder"
    SPINE38 = "spine38"


class PetRendererAction(StrEnum):
    IDLE = "idle"
    WALK_LEFT = "walk_left"
    WALK_RIGHT = "walk_right"
    RUN_LEFT = "run_left"
    RUN_RIGHT = "run_right"
    SITTING = "sitting"
    SLEEP = "sleep"
    SPECIAL = "special"
    INTERACT = "interact"
    WAVE = "wave"
    HAPPY_JUMP = "happy_jump"
    THINKING = "thinking"
    READING = "reading"
    TYPING = "typing"
    REMINDING = "reminding"
    CONFUSED = "confused"
    ANGRY = "angry"
    DRAG_STRUGGLE = "drag_struggle"
    FALLING = "falling"
    LANDING = "landing"
    PAUSED = "paused"
    CLOSING = "closing"


@dataclass(frozen=True, slots=True)
class PetRendererActionRequest:
    action: PetRendererAction
    facing: PetFacing
    loop: bool
    normalized_progress: float


@dataclass(frozen=True, slots=True)
class PetRendererAnimationCapability:
    animation_supported: bool
    loop: bool
    duration_seconds: float | None
    interruptible: bool
    fallback_animation: PetRendererAction


class ExternalAssetConfigStatus(StrEnum):
    VALID = "valid"
    INVALID_ASSET_ID = "invalid_asset_id"
    INVALID_ROOT = "invalid_root"
    INVALID_FILENAME = "invalid_filename"
    INVALID_VERSION = "invalid_version"
    INVALID_HASH = "invalid_hash"
    INVALID_LIMIT = "invalid_limit"
    INVALID_SCALE = "invalid_scale"
    INVALID_GROUND_OFFSET = "invalid_ground_offset"
    RENDERER_UNAVAILABLE = "renderer_unavailable"


@dataclass(frozen=True, slots=True)
class ExternalPetAssetHashes:
    skeleton_sha256: str | None = None
    atlas_sha256: str | None = None
    texture_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalPetAssetLimits:
    atlas_max_bytes: int = 1 * 1024 * 1024
    skeleton_max_bytes: int = 16 * 1024 * 1024
    texture_max_bytes: int = 64 * 1024 * 1024
    bundle_max_bytes: int = 80 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExternalPetAssetDescriptor:
    """Non-persistent descriptor; it never scans or copies asset files."""

    opaque_asset_id: str
    asset_root: str = field(repr=False)
    skeleton_filename: str = field(repr=False)
    atlas_filename: str = field(repr=False)
    texture_filename: str = field(repr=False)
    expected_spine_major: int = 3
    expected_spine_minor: int = 8
    expected_sha256: ExternalPetAssetHashes | None = field(
        default=None,
        repr=False,
    )
    limits: ExternalPetAssetLimits = ExternalPetAssetLimits()


@dataclass(frozen=True, slots=True)
class PetRendererConfig:
    renderer_kind: PetRendererKind = PetRendererKind.PLACEHOLDER
    external_assets: ExternalPetAssetDescriptor | None = field(
        default=None,
        repr=False,
    )
    scale: float = 1.0
    ground_offset: float = 0.0


def validate_external_asset_descriptor(
    descriptor: ExternalPetAssetDescriptor,
) -> ExternalAssetConfigStatus:
    """Validate syntax without touching the filesystem or loading resources."""

    if re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",
        descriptor.opaque_asset_id,
    ) is None:
        return ExternalAssetConfigStatus.INVALID_ASSET_ID
    if not _valid_local_asset_root(descriptor.asset_root):
        return ExternalAssetConfigStatus.INVALID_ROOT
    if not all(
        (
            _valid_filename(descriptor.skeleton_filename, ".skel"),
            _valid_filename(descriptor.atlas_filename, ".atlas"),
            _valid_filename(descriptor.texture_filename, ".png"),
        )
    ):
        return ExternalAssetConfigStatus.INVALID_FILENAME
    if (
        isinstance(descriptor.expected_spine_major, bool)
        or isinstance(descriptor.expected_spine_minor, bool)
        or descriptor.expected_spine_major < 0
        or descriptor.expected_spine_minor < 0
    ):
        return ExternalAssetConfigStatus.INVALID_VERSION
    if descriptor.expected_sha256 is not None and not all(
        _valid_optional_sha256(value)
        for value in (
            descriptor.expected_sha256.skeleton_sha256,
            descriptor.expected_sha256.atlas_sha256,
            descriptor.expected_sha256.texture_sha256,
        )
    ):
        return ExternalAssetConfigStatus.INVALID_HASH
    limits = descriptor.limits
    if any(
        isinstance(value, bool) or value <= 0
        for value in (
            limits.atlas_max_bytes,
            limits.skeleton_max_bytes,
            limits.texture_max_bytes,
            limits.bundle_max_bytes,
        )
    ):
        return ExternalAssetConfigStatus.INVALID_LIMIT
    return ExternalAssetConfigStatus.VALID


def validate_pet_renderer_config(
    config: PetRendererConfig,
) -> ExternalAssetConfigStatus:
    if not math.isfinite(config.scale) or config.scale <= 0:
        return ExternalAssetConfigStatus.INVALID_SCALE
    if not math.isfinite(config.ground_offset):
        return ExternalAssetConfigStatus.INVALID_GROUND_OFFSET
    if config.renderer_kind is PetRendererKind.PLACEHOLDER:
        return (
            ExternalAssetConfigStatus.VALID
            if config.external_assets is None
            else ExternalAssetConfigStatus.INVALID_ROOT
        )
    if config.renderer_kind is not PetRendererKind.SPINE38:
        return ExternalAssetConfigStatus.RENDERER_UNAVAILABLE
    if config.external_assets is None:
        return ExternalAssetConfigStatus.INVALID_ROOT
    return validate_external_asset_descriptor(config.external_assets)


def action_request_for_frame(
    frame: PetRenderFrame,
) -> PetRendererActionRequest:
    """Map layered application state to one renderer-neutral base action."""

    state = frame.state
    if state.lifecycle is PetLifecycleState.CLOSING:
        action = PetRendererAction.CLOSING
    elif state.lifecycle is PetLifecycleState.PAUSED:
        action = PetRendererAction.PAUSED
    elif state.motion is PetMotionState.DRAGGING:
        action = PetRendererAction.DRAG_STRUGGLE
    elif state.motion is PetMotionState.FALLING:
        action = PetRendererAction.FALLING
    elif state.motion is PetMotionState.LANDING:
        action = PetRendererAction.LANDING
    elif state.activity is PetActivityState.SITTING:
        action = PetRendererAction.SITTING
    elif state.activity is PetActivityState.SLEEPING:
        action = PetRendererAction.SLEEP
    elif state.activity is PetActivityState.SPECIAL:
        action = PetRendererAction.SPECIAL
    elif state.activity is PetActivityState.INTERACT:
        action = PetRendererAction.INTERACT
    elif PetBehaviorState.REMINDING in state.behaviors:
        action = PetRendererAction.REMINDING
    elif state.motion is PetMotionState.WALKING_LEFT:
        action = PetRendererAction.WALK_LEFT
    elif state.motion is PetMotionState.WALKING_RIGHT:
        action = PetRendererAction.WALK_RIGHT
    elif PetBehaviorState.THINKING in state.behaviors:
        action = PetRendererAction.THINKING
    else:
        action = PetRendererAction.IDLE
    return PetRendererActionRequest(
        action=action,
        facing=frame.intent.facing,
        loop=frame.intent.loop,
        normalized_progress=min(1.0, max(0.0, frame.intent.progress)),
    )


def placeholder_animation_capability(
    action: PetRendererAction,
) -> PetRendererAnimationCapability:
    supported = {
        PetRendererAction.IDLE,
        PetRendererAction.WALK_LEFT,
        PetRendererAction.WALK_RIGHT,
        PetRendererAction.THINKING,
        PetRendererAction.REMINDING,
        PetRendererAction.DRAG_STRUGGLE,
        PetRendererAction.FALLING,
        PetRendererAction.LANDING,
        PetRendererAction.PAUSED,
        PetRendererAction.CLOSING,
    }
    is_supported = action in supported
    looping = action in {
        PetRendererAction.IDLE,
        PetRendererAction.WALK_LEFT,
        PetRendererAction.WALK_RIGHT,
        PetRendererAction.DRAG_STRUGGLE,
        PetRendererAction.PAUSED,
    }
    return PetRendererAnimationCapability(
        animation_supported=is_supported,
        loop=looping if is_supported else True,
        duration_seconds=None,
        interruptible=action is not PetRendererAction.CLOSING,
        fallback_animation=(
            action if is_supported else PetRendererAction.IDLE
        ),
    )


def _valid_local_asset_root(value: str) -> bool:
    if (
        not value
        or "://" in value
        or any(ord(character) < 32 for character in value)
        or value.startswith(("\\\\", "\\\\?\\", "\\\\.\\"))
    ):
        return False
    path = PureWindowsPath(value)
    if not path.is_absolute() or not path.drive or path.drive.startswith("\\"):
        return False
    return ".." not in path.parts


def _valid_filename(value: str, suffix: str) -> bool:
    if (
        not value
        or ".." in value
        or any(character in value for character in "/\\:\0")
        or any(ord(character) < 32 for character in value)
    ):
        return False
    path = PureWindowsPath(value)
    return (
        path.name == value
        and value not in {".", ".."}
        and path.suffix.lower() == suffix
    )


def _valid_optional_sha256(value: str | None) -> bool:
    return value is None or re.fullmatch(r"[0-9a-f]{64}", value) is not None
