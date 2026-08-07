from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from sjtuclaw.application.pet_action_sequence import (
    SEQUENCE_CATALOG,
    AnimationBinding,
    AnimationRegistry,
    AnimationRegistryError,
    InterruptClass,
    PetActionName,
    PetActionSequence,
    PetActionStep,
    SequenceName,
    default_animation_registry,
)

_EXPECTED_ACTION_NAMES = (
    "idle",
    "breathing",
    "blink",
    "walk_left",
    "walk_right",
    "run_left",
    "run_right",
    "sit_down",
    "sit_idle",
    "sleep_start",
    "sleep_loop",
    "sleep_end",
    "wave",
    "happy",
    "think",
    "read",
    "type",
    "remind",
    "confused",
    "angry",
    "drag_start",
    "drag_loop",
    "drag_end",
    "landing",
    "return_idle",
)


def test_logical_catalog_is_exact_unique_and_case_sensitive() -> None:
    assert tuple(action.value for action in PetActionName) == _EXPECTED_ACTION_NAMES
    assert len(set(PetActionName)) == 25
    with pytest.raises(ValueError):
        PetActionName("Sleep_Loop")


def test_sequence_is_immutable_and_step_has_no_successor_pointer() -> None:
    step = PetActionStep(PetActionName.IDLE, loop=True)
    sequence = PetActionSequence((step,), loop_index=0)

    assert not hasattr(step, "next")
    with pytest.raises(FrozenInstanceError):
        sequence.loop_index = None  # type: ignore[misc]


def test_then_returns_new_ordered_sequence_without_mutating_source() -> None:
    source = PetActionSequence((PetActionStep(PetActionName.WAVE, False),))

    result = source.then(PetActionStep(PetActionName.RETURN_IDLE, False))

    assert tuple(step.action for step in source.steps) == (PetActionName.WAVE,)
    assert tuple(step.action for step in result.steps) == (
        PetActionName.WAVE,
        PetActionName.RETURN_IDLE,
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PetActionSequence(()),
        lambda: PetActionSequence(
            (PetActionStep(PetActionName.IDLE, True),),
            loop_index=1,
        ),
        lambda: PetActionSequence(
            (PetActionStep(PetActionName.WAVE, False),),
            loop_index=0,
        ),
        lambda: PetActionSequence(
            (PetActionStep(PetActionName.WAVE, False),),
            loop_exit_index=0,
        ),
    ],
)
def test_invalid_sequence_shapes_are_rejected(
    factory: Callable[[], PetActionSequence],
) -> None:
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    ("speed", "mix_seconds"),
    [(0.0, None), (-1.0, None), (1.0, -0.01)],
)
def test_invalid_step_timing_is_rejected(
    speed: float,
    mix_seconds: float | None,
) -> None:
    with pytest.raises(ValueError):
        PetActionStep(
            PetActionName.IDLE,
            loop=True,
            speed=speed,
            mix_seconds=mix_seconds,
        )


def test_catalog_union_covers_all_25_names_and_track_ownership() -> None:
    seen = {step.action for entry in SEQUENCE_CATALOG.values() for step in entry.sequence.steps}

    assert seen == set(PetActionName)
    assert SEQUENCE_CATALOG[SequenceName.BREATHING].track == 1
    assert SEQUENCE_CATALOG[SequenceName.BLINK].track == 2
    assert all(
        step.action not in {PetActionName.BREATHING, PetActionName.BLINK}
        for entry in SEQUENCE_CATALOG.values()
        if entry.track == 0
        for step in entry.sequence.steps
    )


def test_drag_release_and_fall_recovery_have_distinct_request_classes() -> None:
    assert (
        SEQUENCE_CATALOG[SequenceName.DRAG_RELEASE].interruption_class
        is InterruptClass.USER_INTERACTION
    )
    assert (
        SEQUENCE_CATALOG[SequenceName.FALL_RECOVERY].interruption_class
        is InterruptClass.MOTION_SAFETY
    )


def test_default_registry_is_an_exact_identity_mapping() -> None:
    registry = default_animation_registry()

    assert set(registry.actions) == set(PetActionName)
    assert all(registry.resolve(action).physical_name == action.value for action in PetActionName)
    assert registry.resolve(PetActionName.BREATHING).track == 1
    assert registry.resolve(PetActionName.BLINK).track == 2
    assert registry.resolve(PetActionName.IDLE).track == 0


def test_registry_rejects_missing_binding() -> None:
    bindings: dict[PetActionName, AnimationBinding] = {
        action: AnimationBinding(action, action.value, 0)
        for action in PetActionName
        if action is not PetActionName.BLINK
    }

    with pytest.raises(AnimationRegistryError):
        AnimationRegistry(bindings)


def test_registry_rejects_duplicate_physical_binding() -> None:
    bindings = {action: AnimationBinding(action, action.value, 0) for action in PetActionName}
    bindings[PetActionName.HAPPY] = AnimationBinding(
        PetActionName.HAPPY,
        PetActionName.WAVE.value,
        0,
    )

    with pytest.raises(AnimationRegistryError):
        AnimationRegistry(bindings)


def test_registry_rejects_case_mismatch_from_loaded_skeleton() -> None:
    registry = default_animation_registry()
    names = {action.value for action in PetActionName} - {"sleep_loop"}
    names.add("Sleep_Loop")

    with pytest.raises(AnimationRegistryError):
        registry.validate_loaded_names(frozenset(names))


def test_registry_requires_duration_only_when_production_requests_it() -> None:
    registry = default_animation_registry()

    with pytest.raises(AnimationRegistryError):
        registry.validate_sequence(
            SEQUENCE_CATALOG[SequenceName.SLEEP],
            require_duration_metadata=True,
        )


def test_registry_rejects_overlay_action_on_track_zero() -> None:
    registry = default_animation_registry()
    invalid = PetActionSequence((PetActionStep(PetActionName.BLINK, False),))

    with pytest.raises(AnimationRegistryError):
        registry.validate_track_sequence(0, invalid)
