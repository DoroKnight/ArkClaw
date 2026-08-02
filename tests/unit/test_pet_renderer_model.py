"""Deterministic tests for the framework-free renderer contract."""

from __future__ import annotations

from sjtuclaw.application.pet_animation import (
    PetAnimationConfig,
    PetAnimationEngine,
)
from sjtuclaw.application.pet_geometry import Point, Rect, Size
from sjtuclaw.application.pet_motion import PetMotionModel
from sjtuclaw.application.pet_renderer_model import (
    ExternalAssetConfigStatus,
    ExternalPetAssetDescriptor,
    PetRendererAction,
    PetRendererKind,
    action_request_for_frame,
    placeholder_animation_capability,
    validate_external_asset_descriptor,
)
from sjtuclaw.application.pet_state import PetFacing


def _engine() -> PetAnimationEngine:
    return PetAnimationEngine(
        PetMotionModel(Point(20, 20), Size(160, 180)),
        config=PetAnimationConfig(
            blinking_interval_min_seconds=100,
            blinking_interval_max_seconds=100,
            random_action_interval_min_seconds=100,
            random_action_interval_max_seconds=100,
        ),
    )


def test_default_descriptor_selects_placeholder_without_assets() -> None:
    descriptor = ExternalPetAssetDescriptor()

    assert descriptor.renderer_kind is PetRendererKind.PLACEHOLDER
    assert validate_external_asset_descriptor(descriptor) is (
        ExternalAssetConfigStatus.VALID
    )


def test_external_descriptor_is_memory_only_and_runtime_unavailable() -> None:
    fictional_root = "X:\\fictional-pet-assets"
    descriptor = ExternalPetAssetDescriptor(
        renderer_kind=PetRendererKind.SPINE38,
        external_asset_root=fictional_root,
        skeleton_filename="fictional.skel",
        atlas_filename="fictional.atlas",
        texture_filename="fictional.png",
        expected_spine_version="3.8.99",
        scale=0.75,
        ground_offset=4.0,
    )

    assert validate_external_asset_descriptor(descriptor) is (
        ExternalAssetConfigStatus.RENDERER_UNAVAILABLE
    )
    assert fictional_root not in repr(descriptor)


def test_external_descriptor_rejects_unsafe_or_invalid_values() -> None:
    base = {
        "renderer_kind": PetRendererKind.SPINE38,
        "skeleton_filename": "fictional.skel",
        "atlas_filename": "fictional.atlas",
        "texture_filename": "fictional.png",
        "expected_spine_version": "3.8",
    }

    def descriptor(**changes: object) -> ExternalPetAssetDescriptor:
        return ExternalPetAssetDescriptor(**(base | changes))  # type: ignore[arg-type]

    assert validate_external_asset_descriptor(
        descriptor(
            external_asset_root="\\\\host\\share\\assets",
        )
    ) is ExternalAssetConfigStatus.INVALID_ROOT
    assert validate_external_asset_descriptor(
        descriptor(
            external_asset_root="https://invalid.example/assets",
        )
    ) is ExternalAssetConfigStatus.INVALID_ROOT
    assert validate_external_asset_descriptor(
        descriptor(
            external_asset_root="X:\\fictional\\..\\escape",
        )
    ) is ExternalAssetConfigStatus.INVALID_ROOT
    assert validate_external_asset_descriptor(
        descriptor(
            external_asset_root="X:\\fictional",
            skeleton_filename="nested\\fictional.skel",
        )
    ) is ExternalAssetConfigStatus.INVALID_FILENAME
    assert validate_external_asset_descriptor(
        descriptor(
            external_asset_root="X:\\fictional",
            expected_spine_version="4.2",
        )
    ) is ExternalAssetConfigStatus.INVALID_VERSION
    assert validate_external_asset_descriptor(
        descriptor(
            external_asset_root="X:\\fictional",
            scale=0.0,
        )
    ) is ExternalAssetConfigStatus.INVALID_SCALE


def test_layered_state_maps_to_renderer_actions_by_priority() -> None:
    engine = _engine()
    workspaces = (Rect(0, 0, 1920, 1080),)

    assert action_request_for_frame(engine.frame).action is PetRendererAction.IDLE
    engine.request_walk(PetFacing.LEFT)
    assert action_request_for_frame(engine.frame).action is (
        PetRendererAction.WALK_LEFT
    )
    engine.start_dragging()
    assert action_request_for_frame(engine.frame).action is (
        PetRendererAction.DRAG_STRUGGLE
    )
    engine.release_drag()
    assert action_request_for_frame(engine.frame).action is (
        PetRendererAction.FALLING
    )
    for _ in range(20):
        snapshot = engine.advance(0.1, workspaces)
        if snapshot.frame.state.motion.value == "landing":
            break
    assert action_request_for_frame(engine.frame).action is (
        PetRendererAction.LANDING
    )
    engine.pause()
    assert action_request_for_frame(engine.frame).action is (
        PetRendererAction.PAUSED
    )
    engine.begin_closing()
    assert action_request_for_frame(engine.frame).action is (
        PetRendererAction.CLOSING
    )


def test_placeholder_reports_unsupported_actions_with_idle_fallback() -> None:
    unsupported = {
        PetRendererAction.RUN_LEFT,
        PetRendererAction.RUN_RIGHT,
        PetRendererAction.SITTING,
        PetRendererAction.SLEEP,
        PetRendererAction.WAVE,
        PetRendererAction.HAPPY_JUMP,
        PetRendererAction.READING,
        PetRendererAction.TYPING,
        PetRendererAction.CONFUSED,
        PetRendererAction.ANGRY,
    }

    for action in unsupported:
        capability = placeholder_animation_capability(action)
        assert not capability.animation_supported
        assert capability.fallback_animation is PetRendererAction.IDLE

    idle = placeholder_animation_capability(PetRendererAction.IDLE)
    assert idle.animation_supported
    assert idle.loop
    assert idle.fallback_animation is PetRendererAction.IDLE


def test_renderer_action_vocabulary_is_stable_and_complete() -> None:
    assert {action.value for action in PetRendererAction} == {
        "idle",
        "walk_left",
        "walk_right",
        "run_left",
        "run_right",
        "sitting",
        "sleep",
        "wave",
        "happy_jump",
        "thinking",
        "reading",
        "typing",
        "reminding",
        "confused",
        "angry",
        "drag_struggle",
        "falling",
        "landing",
        "paused",
        "closing",
    }
