"""Framework-free contracts for replaceable desktop-pet renderers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PureWindowsPath

from sjtuclaw.application.pet_animation import PetRenderFrame
from sjtuclaw.application.pet_state import (
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
    INVALID_ROOT = "invalid_root"
    INVALID_FILENAME = "invalid_filename"
    INVALID_VERSION = "invalid_version"
    INVALID_SCALE = "invalid_scale"
    INVALID_GROUND_OFFSET = "invalid_ground_offset"
    RENDERER_UNAVAILABLE = "renderer_unavailable"


@dataclass(frozen=True, slots=True)
class ExternalPetAssetDescriptor:
    """Non-persistent descriptor; it never scans or copies asset files."""

    renderer_kind: PetRendererKind = PetRendererKind.PLACEHOLDER
    external_asset_root: str | None = field(default=None, repr=False)
    skeleton_filename: str | None = field(default=None, repr=False)
    atlas_filename: str | None = field(default=None, repr=False)
    texture_filename: str | None = field(default=None, repr=False)
    expected_spine_version: str | None = None
    scale: float = 1.0
    ground_offset: float = 0.0


def validate_external_asset_descriptor(
    descriptor: ExternalPetAssetDescriptor,
) -> ExternalAssetConfigStatus:
    """Validate syntax without touching the filesystem or loading resources."""

    if descriptor.renderer_kind is PetRendererKind.PLACEHOLDER:
        return ExternalAssetConfigStatus.VALID
    if descriptor.renderer_kind is not PetRendererKind.SPINE38:
        return ExternalAssetConfigStatus.RENDERER_UNAVAILABLE
    if not _valid_local_asset_root(descriptor.external_asset_root):
        return ExternalAssetConfigStatus.INVALID_ROOT
    if not all(
        (
            _valid_filename(descriptor.skeleton_filename, ".skel"),
            _valid_filename(descriptor.atlas_filename, ".atlas"),
            _valid_filename(descriptor.texture_filename, ".png"),
        )
    ):
        return ExternalAssetConfigStatus.INVALID_FILENAME
    if descriptor.expected_spine_version is None or re.fullmatch(
        r"3\.8(?:\.\d+)?",
        descriptor.expected_spine_version,
    ) is None:
        return ExternalAssetConfigStatus.INVALID_VERSION
    if not math.isfinite(descriptor.scale) or descriptor.scale <= 0:
        return ExternalAssetConfigStatus.INVALID_SCALE
    if not math.isfinite(descriptor.ground_offset):
        return ExternalAssetConfigStatus.INVALID_GROUND_OFFSET
    # No external runtime is present in this phase. A syntactically valid
    # descriptor therefore remains deliberately unavailable and must fall back.
    return ExternalAssetConfigStatus.RENDERER_UNAVAILABLE


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


def _valid_local_asset_root(value: str | None) -> bool:
    if value is None or not value or "://" in value:
        return False
    path = PureWindowsPath(value)
    if not path.is_absolute() or not path.drive or path.drive.startswith("\\"):
        return False
    return ".." not in path.parts


def _valid_filename(value: str | None, suffix: str) -> bool:
    if value is None or not value:
        return False
    path = PureWindowsPath(value)
    return (
        path.name == value
        and value not in {".", ".."}
        and path.suffix.lower() == suffix
    )
