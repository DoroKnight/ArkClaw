"""Deterministic tests for the framework-free renderer contract."""

from __future__ import annotations

from arkclaw.application.pet.pet_animation import (
    PetAnimationConfig,
    PetAnimationEngine,
)
from arkclaw.application.pet.pet_geometry import Point, Rect, Size
from arkclaw.application.pet.pet_motion import PetMotionModel
from arkclaw.application.pet.pet_renderer_model import (
    ExternalAssetConfigStatus,
    ExternalPetAssetDescriptor,
    PetRendererAction,
    PetRendererConfig,
    PetRendererKind,
    action_request_for_frame,
    placeholder_animation_capability,
    validate_external_asset_descriptor,
    validate_pet_renderer_config,
)
from arkclaw.application.pet.pet_state import PetFacing


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


def test_default_renderer_config_selects_placeholder_without_assets() -> None:
    config = PetRendererConfig()

    assert config.renderer_kind is PetRendererKind.PLACEHOLDER
    assert config.external_assets is None
    assert validate_pet_renderer_config(config) is (
        ExternalAssetConfigStatus.VALID
    )


def test_external_descriptor_is_memory_only_and_runtime_unavailable() -> None:
    fictional_root = "X:\\fictional-pet-assets"
    descriptor = ExternalPetAssetDescriptor(
        opaque_asset_id="fictional-bundle",
        asset_root=fictional_root,
        skeleton_filename="fictional.skel",
        atlas_filename="fictional.atlas",
        texture_filename="fictional.png",
        expected_spine_major=3,
        expected_spine_minor=8,
    )

    assert validate_external_asset_descriptor(descriptor) is (
        ExternalAssetConfigStatus.VALID
    )
    assert validate_pet_renderer_config(
        PetRendererConfig(
            renderer_kind=PetRendererKind.SPINE38,
            external_assets=descriptor,
        )
    ) is (
        ExternalAssetConfigStatus.VALID
    )
    assert fictional_root not in repr(descriptor)


def test_external_descriptor_rejects_unsafe_or_invalid_values() -> None:
    base = {
        "opaque_asset_id": "fictional-bundle",
        "skeleton_filename": "fictional.skel",
        "atlas_filename": "fictional.atlas",
        "texture_filename": "fictional.png",
        "expected_spine_major": 3,
        "expected_spine_minor": 8,
    }

    def descriptor(**changes: object) -> ExternalPetAssetDescriptor:
        return ExternalPetAssetDescriptor(**(base | changes))  # type: ignore[arg-type]

    assert validate_external_asset_descriptor(
        descriptor(
            asset_root="\\\\host\\share\\assets",
        )
    ) is ExternalAssetConfigStatus.INVALID_ROOT
    assert validate_external_asset_descriptor(
        descriptor(
            asset_root="https://invalid.example/assets",
        )
    ) is ExternalAssetConfigStatus.INVALID_ROOT
    assert validate_external_asset_descriptor(
        descriptor(
            asset_root="X:\\fictional\\..\\escape",
        )
    ) is ExternalAssetConfigStatus.INVALID_ROOT
    assert validate_external_asset_descriptor(
        descriptor(
            asset_root="X:\\fictional",
            skeleton_filename="nested\\fictional.skel",
        )
    ) is ExternalAssetConfigStatus.INVALID_FILENAME
    assert validate_external_asset_descriptor(
        descriptor(
            asset_root="X:\\fictional",
            expected_spine_major=-1,
        )
    ) is ExternalAssetConfigStatus.INVALID_VERSION
    assert validate_pet_renderer_config(
        PetRendererConfig(scale=0.0)
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
        "special",
        "interact",
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
