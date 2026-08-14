from __future__ import annotations

import random

import pytest

from arkclaw.application.pet.pet_animation import (
    PetAnimationConfig,
    PetAnimationEngine,
)
from arkclaw.application.pet.pet_geometry import Point, Rect, Size
from arkclaw.application.pet.pet_motion import PetMotionModel
from arkclaw.application.pet.pet_state import (
    PetBehaviorState,
    PetFacing,
    PetLayeredState,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
)

_WORKSPACE = (Rect(0, 0, 800, 600),)
_WINDOW = Size(100, 120)


def _config(
    *,
    blink_min: float = 100.0,
    blink_max: float = 100.0,
    random_min: float = 100.0,
    random_max: float = 100.0,
) -> PetAnimationConfig:
    return PetAnimationConfig(
        maximum_delta_seconds=0.1,
        breathing_cycle_seconds=1.0,
        blinking_duration_seconds=0.1,
        blinking_interval_min_seconds=blink_min,
        blinking_interval_max_seconds=blink_max,
        walking_duration_seconds=0.4,
        thinking_duration_seconds=0.2,
        reminder_duration_seconds=0.2,
        random_action_interval_min_seconds=random_min,
        random_action_interval_max_seconds=random_max,
    )


def _engine(
    *,
    x: float = 100.0,
    seed: int = 7,
    config: PetAnimationConfig | None = None,
) -> PetAnimationEngine:
    return PetAnimationEngine(
        PetMotionModel(Point(x, 480), _WINDOW),
        rng=random.Random(seed),
        config=config or _config(),
    )


@pytest.mark.parametrize(
    ("lifecycle", "motion", "behaviors"),
    [
        (
            PetLifecycleState.CLOSING,
            PetMotionState.IDLE,
            frozenset({PetBehaviorState.BLINKING}),
        ),
        (
            PetLifecycleState.PAUSED,
            PetMotionState.IDLE,
            frozenset({PetBehaviorState.BREATHING}),
        ),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.DRAGGING,
            frozenset({PetBehaviorState.BREATHING}),
        ),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.IDLE,
            frozenset({PetBehaviorState.DRAG_STRUGGLE}),
        ),
    ],
)
def test_illegal_layered_state_combinations_are_rejected(
    lifecycle: PetLifecycleState,
    motion: PetMotionState,
    behaviors: frozenset[PetBehaviorState],
) -> None:
    with pytest.raises(PetStateTransitionError):
        PetLayeredState(
            lifecycle=lifecycle,
            motion=motion,
            behaviors=behaviors,
            facing=PetFacing.RIGHT,
        )


@pytest.mark.parametrize(
    ("motion", "behaviors"),
    [
        (
            PetMotionState.IDLE,
            frozenset(
                {
                    PetBehaviorState.BREATHING,
                    PetBehaviorState.BLINKING,
                }
            ),
        ),
        (
            PetMotionState.WALKING_LEFT,
            frozenset({PetBehaviorState.BLINKING}),
        ),
        (
            PetMotionState.DRAGGING,
            frozenset({PetBehaviorState.DRAG_STRUGGLE}),
        ),
        (
            PetMotionState.IDLE,
            frozenset({PetBehaviorState.REMINDING}),
        ),
    ],
)
def test_reviewed_layered_state_combinations_are_legal(
    motion: PetMotionState,
    behaviors: frozenset[PetBehaviorState],
) -> None:
    state = PetLayeredState(
        lifecycle=PetLifecycleState.ACTIVE,
        motion=motion,
        behaviors=behaviors,
        facing=PetFacing.LEFT,
    )

    assert state.motion is motion
    assert state.behaviors == behaviors


def test_blink_schedule_is_reproducible_for_a_fixed_seed() -> None:
    config = _config(blink_min=0.2, blink_max=0.5)
    first = _engine(seed=123, config=config)
    second = _engine(seed=123, config=config)

    first_frames = []
    second_frames = []
    for _ in range(12):
        first_frames.append(first.advance(0.05, _WORKSPACE).frame)
        second_frames.append(second.advance(0.05, _WORKSPACE).frame)

    assert [
        PetBehaviorState.BLINKING in frame.state.behaviors
        for frame in first_frames
    ] == [
        PetBehaviorState.BLINKING in frame.state.behaviors
        for frame in second_frames
    ]
    assert [
        frame.visual.eye_openness for frame in first_frames
    ] == [
        frame.visual.eye_openness for frame in second_frames
    ]


def test_breathing_cycle_is_seamless() -> None:
    engine = _engine()
    start = engine.frame.visual.breathing_amount

    frames = [engine.advance(0.1, _WORKSPACE).frame for _ in range(10)]

    assert max(frame.visual.breathing_amount for frame in frames) > 0.9
    assert frames[-1].visual.breathing_amount == pytest.approx(
        start,
        abs=1e-12,
    )


def test_random_idle_action_is_reproducible_for_a_fixed_seed() -> None:
    config = _config(random_min=0.1, random_max=0.1)
    first = _engine(seed=99, config=config)
    second = _engine(seed=99, config=config)

    first_state = first.advance(0.1, _WORKSPACE).frame.state
    second_state = second.advance(0.1, _WORKSPACE).frame.state

    assert first_state == second_state
    assert (
        first_state.motion
        in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }
        or PetBehaviorState.THINKING in first_state.behaviors
    )


def test_blink_can_overlay_idle_breathing() -> None:
    engine = _engine(config=_config(blink_min=0.1, blink_max=0.1))

    frame = engine.advance(0.1, _WORKSPACE).frame

    assert frame.state.motion is PetMotionState.IDLE
    assert frame.state.behaviors == frozenset(
        {PetBehaviorState.BREATHING, PetBehaviorState.BLINKING}
    )


def test_blink_can_overlay_walking() -> None:
    engine = _engine(config=_config(blink_min=0.1, blink_max=0.1))
    engine.request_walk(PetFacing.LEFT)

    frame = engine.advance(0.1, _WORKSPACE).frame

    assert frame.state.motion is PetMotionState.WALKING_LEFT
    assert frame.state.behaviors == frozenset(
        {PetBehaviorState.BLINKING}
    )


def test_blink_can_overlay_thinking() -> None:
    engine = _engine(config=_config(blink_min=0.1, blink_max=0.1))
    engine.request_thinking_animation()

    frame = engine.advance(0.1, _WORKSPACE).frame

    assert frame.state.motion is PetMotionState.IDLE
    assert frame.state.behaviors == frozenset(
        {PetBehaviorState.THINKING, PetBehaviorState.BLINKING}
    )


def test_walking_speed_is_derived_from_stride_and_cycle() -> None:
    engine = _engine(x=100)
    engine.request_walk(PetFacing.RIGHT)

    snapshot = engine.advance(0.1, _WORKSPACE)

    assert snapshot.motion.position.x == pytest.approx(103.0)
    assert snapshot.frame.intent.progress == pytest.approx(0.125)


def test_walking_reverses_at_workspace_edge() -> None:
    engine = _engine(x=0)
    engine.request_walk(PetFacing.LEFT)

    snapshot = engine.advance(0.1, _WORKSPACE)

    assert snapshot.motion.position.x == 0
    assert snapshot.motion.state.motion is PetMotionState.WALKING_RIGHT
    assert snapshot.motion.state.facing is PetFacing.RIGHT


def test_dragging_immediately_interrupts_walk_and_enables_struggle() -> None:
    engine = _engine(x=100)
    engine.request_walk(PetFacing.RIGHT)

    engine.start_dragging()
    before = engine.motion.position
    snapshot = engine.advance(0.03, _WORKSPACE)

    assert snapshot.motion.state.motion is PetMotionState.DRAGGING
    assert snapshot.motion.state.behaviors == frozenset(
        {PetBehaviorState.DRAG_STRUGGLE}
    )
    assert snapshot.motion.position == before
    assert snapshot.frame.visual.body_wiggle != 0


def test_drag_struggle_never_changes_mouse_follow_position() -> None:
    engine = _engine(x=100)
    engine.start_dragging()

    dragged = engine.motion.drag_to(Point(250, 200), _WORKSPACE)
    animated = engine.advance(0.1, _WORKSPACE)

    assert dragged.position == Point(250, 200)
    assert animated.motion.position == dragged.position


def test_releasing_drag_removes_struggle_and_enters_falling() -> None:
    engine = _engine()
    engine.start_dragging()

    engine.release_drag()

    assert engine.motion.state.motion is PetMotionState.FALLING
    assert PetBehaviorState.DRAG_STRUGGLE not in (
        engine.motion.state.behaviors
    )


def test_reminder_interrupts_walk_and_returns_to_idle() -> None:
    engine = _engine()
    engine.request_walk(PetFacing.LEFT)

    engine.request_reminder_animation()
    reminding = engine.frame
    engine.advance(0.1, _WORKSPACE)
    finished = engine.advance(0.1, _WORKSPACE).frame

    assert reminding.state.motion is PetMotionState.IDLE
    assert reminding.state.behaviors == frozenset(
        {PetBehaviorState.REMINDING}
    )
    assert finished.state.motion is PetMotionState.IDLE
    assert finished.state.behaviors == frozenset(
        {PetBehaviorState.BREATHING}
    )


def test_reminder_blocks_lower_priority_walk_and_thinking_requests() -> None:
    engine = _engine()
    engine.request_reminder_animation()

    with pytest.raises(PetStateTransitionError):
        engine.request_walk(PetFacing.LEFT)
    with pytest.raises(PetStateTransitionError):
        engine.request_thinking_animation()

    assert engine.frame.state.behaviors == frozenset(
        {PetBehaviorState.REMINDING}
    )


def test_reminder_interrupts_a_seeded_random_idle_action() -> None:
    engine = _engine(config=_config(random_min=0.1, random_max=0.1))
    random_state = engine.advance(0.1, _WORKSPACE).frame.state
    assert (
        random_state.motion
        in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }
        or PetBehaviorState.THINKING in random_state.behaviors
    )

    engine.request_reminder_animation()

    assert engine.frame.state.motion is PetMotionState.IDLE
    assert engine.frame.state.behaviors == frozenset(
        {PetBehaviorState.REMINDING}
    )


def test_paused_state_freezes_animation_and_random_schedule() -> None:
    engine = _engine(
        config=_config(
            blink_min=0.1,
            blink_max=0.1,
            random_min=0.1,
            random_max=0.1,
        )
    )
    before = engine.frame
    engine.pause()

    paused = engine.advance(100.0, _WORKSPACE)

    assert paused.applied_delta_seconds == 0
    assert paused.frame.animation_time == before.animation_time
    assert paused.frame.state.lifecycle is PetLifecycleState.PAUSED
    assert not paused.frame.state.behaviors
    engine.resume()
    resumed = engine.advance(0.05, _WORKSPACE)
    assert resumed.frame.state.motion is PetMotionState.IDLE
    assert resumed.frame.state.behaviors == frozenset(
        {PetBehaviorState.BREATHING}
    )


def test_closing_freezes_all_animation_layers() -> None:
    engine = _engine()

    engine.begin_closing()
    snapshot = engine.advance(1.0, _WORKSPACE)

    assert snapshot.applied_delta_seconds == 0
    assert snapshot.frame.state.lifecycle is PetLifecycleState.CLOSING
    assert snapshot.frame.state.motion is PetMotionState.IDLE
    assert not snapshot.frame.state.behaviors


def test_large_delta_is_clamped_before_motion_and_animation() -> None:
    engine = _engine(x=100)
    engine.request_walk(PetFacing.RIGHT)

    snapshot = engine.advance(60.0, _WORKSPACE)

    assert snapshot.applied_delta_seconds == 0.1
    assert snapshot.motion.position.x == pytest.approx(103.0)
