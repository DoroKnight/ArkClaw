from __future__ import annotations

from contextlib import suppress
from dataclasses import FrozenInstanceError
from itertools import combinations

import pytest

from arkclaw.application.pet.pet_action_sequence import PetActionName, PlaybackHealth
from arkclaw.application.pet.pet_state import (
    STATE_ACTION_COMPATIBILITY,
    AnimationCompatibilityError,
    PetActivityState,
    PetBehaviorState,
    PetFacing,
    PetLayeredState,
    PetLayeredStateMachine,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
    assert_animation_compatible,
)


def _behavior_sets() -> tuple[frozenset[PetBehaviorState], ...]:
    values = tuple(PetBehaviorState)
    return tuple(
        frozenset(group) for size in range(len(values) + 1) for group in combinations(values, size)
    )


def _all_valid_layered_states() -> tuple[PetLayeredState, ...]:
    states: list[PetLayeredState] = []
    for lifecycle in PetLifecycleState:
        for motion in PetMotionState:
            for activity in PetActivityState:
                for behaviors in _behavior_sets():
                    with suppress(PetStateTransitionError):
                        states.append(
                            PetLayeredState(
                                lifecycle=lifecycle,
                                motion=motion,
                                behaviors=behaviors,
                                facing=PetFacing.RIGHT,
                                activity=activity,
                            )
                        )
    return tuple(dict.fromkeys(states))


def test_state_machine_owns_target_epoch_and_rejected_proposal_does_not_commit() -> None:
    machine = PetLayeredStateMachine(initial_epoch=17)

    proposal = machine.propose(activity=PetActivityState.READING)

    assert proposal.source_epoch == 17
    assert proposal.target_epoch == 18
    assert machine.epoch == 17
    machine.commit(proposal)
    assert machine.epoch == 18
    assert machine.snapshot.activity is PetActivityState.READING


def test_commit_rejects_stale_source_epoch() -> None:
    machine = PetLayeredStateMachine(initial_epoch=17)
    stale = machine.propose(activity=PetActivityState.READING)
    machine.commit(machine.propose(activity=PetActivityState.THINKING))

    with pytest.raises(PetStateTransitionError):
        machine.commit(stale)


def test_rejected_proposal_never_reserves_an_epoch() -> None:
    machine = PetLayeredStateMachine(initial_epoch=4)

    first = machine.propose(activity=PetActivityState.READING)
    second = machine.propose(activity=PetActivityState.THINKING)

    assert first.target_epoch == second.target_epoch == 5
    assert machine.epoch == 4


def test_mandatory_safety_flag_is_part_of_the_immutable_proposal() -> None:
    machine = PetLayeredStateMachine()

    proposal = machine.propose(
        motion=PetMotionState.FALLING,
        mandatory_for_safety=True,
    )

    assert proposal.mandatory_for_safety
    with pytest.raises(FrozenInstanceError):
        proposal.target_epoch = 99  # type: ignore[misc]


@pytest.mark.parametrize("state", _all_valid_layered_states())
@pytest.mark.parametrize("action", (*PetActionName, None))
def test_track0_compatibility_is_exhaustive(
    state: PetLayeredState,
    action: PetActionName | None,
) -> None:
    key = (state.lifecycle, state.motion, state.activity)
    expected = (
        action is None
        if state.lifecycle is not PetLifecycleState.ACTIVE
        else action in STATE_ACTION_COMPATIBILITY.get(key, frozenset())
    )
    if expected:
        assert_animation_compatible(state, action, PlaybackHealth.HEALTHY)
    else:
        with pytest.raises(AnimationCompatibilityError):
            assert_animation_compatible(state, action, PlaybackHealth.HEALTHY)


@pytest.mark.parametrize(
    "health",
    [PlaybackHealth.DEGRADED, PlaybackHealth.UNKNOWN],
)
def test_unconfirmed_health_permits_only_no_desired_action(
    health: PlaybackHealth,
) -> None:
    state = PetLayeredStateMachine().snapshot

    assert_animation_compatible(state, None, health)
    with pytest.raises(AnimationCompatibilityError):
        assert_animation_compatible(state, PetActionName.IDLE, health)


@pytest.mark.parametrize(
    ("state", "action"),
    [
        (
            PetLayeredState(
                PetLifecycleState.ACTIVE,
                PetMotionState.DRAGGING,
                frozenset({PetBehaviorState.DRAG_STRUGGLE}),
                PetFacing.RIGHT,
            ),
            PetActionName.SLEEP_LOOP,
        ),
        (
            PetLayeredState(
                PetLifecycleState.ACTIVE,
                PetMotionState.IDLE,
                frozenset(),
                PetFacing.RIGHT,
                PetActivityState.SLEEPING,
            ),
            PetActionName.DRAG_LOOP,
        ),
        (
            PetLayeredState(
                PetLifecycleState.PAUSED,
                PetMotionState.IDLE,
                frozenset(),
                PetFacing.RIGHT,
            ),
            PetActionName.IDLE,
        ),
    ],
)
def test_named_incompatible_state_action_pairs_are_rejected(
    state: PetLayeredState,
    action: PetActionName,
) -> None:
    with pytest.raises(AnimationCompatibilityError):
        assert_animation_compatible(state, action, PlaybackHealth.HEALTHY)


def test_compatibility_mapping_contains_only_active_semantic_rows() -> None:
    assert len(STATE_ACTION_COMPATIBILITY) == 20
    assert STATE_ACTION_COMPATIBILITY[
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.IDLE,
            PetActivityState.SPECIAL,
        )
    ] == frozenset({PetActionName.WAVE})
    assert STATE_ACTION_COMPATIBILITY[
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.IDLE,
            PetActivityState.INTERACT,
        )
    ] == frozenset({PetActionName.HAPPY})
    assert all(
        lifecycle is PetLifecycleState.ACTIVE
        for lifecycle, _motion, _activity in STATE_ACTION_COMPATIBILITY
    )
