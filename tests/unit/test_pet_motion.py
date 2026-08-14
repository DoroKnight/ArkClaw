from __future__ import annotations

import pytest

from arkclaw.application.pet.pet_geometry import (
    Point,
    Rect,
    Size,
    clamp_window_position,
    physical_to_logical_rect,
    select_workspace,
)
from arkclaw.application.pet.pet_motion import (
    PetMotionConfig,
    PetMotionModel,
)
from arkclaw.application.pet.pet_state import (
    PetActivityState,
    PetBehaviorState,
    PetFacing,
    PetLayeredState,
    PetLayeredStateMachine,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
    layered_state_priority,
)

_WINDOW = Size(100, 120)
_WORKSPACE = Rect(0, 0, 800, 600)


def test_layered_state_starts_active_idle_and_breathing() -> None:
    state = PetLayeredStateMachine().snapshot

    assert state == PetLayeredState(
        lifecycle=PetLifecycleState.ACTIVE,
        motion=PetMotionState.IDLE,
        behaviors=frozenset({PetBehaviorState.BREATHING}),
        facing=PetFacing.RIGHT,
        activity=PetActivityState.NONE,
    )


def test_running_motion_values_are_available_without_changing_walk_api() -> None:
    assert PetMotionState.RUNNING_LEFT.value == "running_left"
    assert PetMotionState.RUNNING_RIGHT.value == "running_right"


def test_thinking_and_reminding_use_activity_with_legacy_behavior_projection() -> None:
    machine = PetLayeredStateMachine()

    machine.start_thinking()
    assert machine.activity is PetActivityState.THINKING
    assert PetBehaviorState.THINKING in machine.behaviors

    reminding_machine = PetLayeredStateMachine()
    reminding_machine.start_reminding()
    assert reminding_machine.activity is PetActivityState.REMINDING
    assert reminding_machine.behaviors == frozenset({PetBehaviorState.REMINDING})


def test_layered_state_priority_places_close_above_drag_and_idle() -> None:
    machine = PetLayeredStateMachine()
    idle_priority = layered_state_priority(machine.snapshot)
    machine.start_dragging()
    dragging_priority = layered_state_priority(machine.snapshot)
    machine.begin_closing()
    closing_priority = layered_state_priority(machine.snapshot)

    assert closing_priority > dragging_priority > idle_priority


def test_state_machine_accepts_the_reviewed_drag_fall_land_path() -> None:
    machine = PetLayeredStateMachine()

    machine.start_dragging()
    machine.release_drag()
    machine.land()
    machine.finish_landing()

    assert machine.motion is PetMotionState.IDLE
    assert machine.behaviors == frozenset({PetBehaviorState.BREATHING})


def test_state_machine_rejects_an_illegal_direct_landing() -> None:
    machine = PetLayeredStateMachine()

    with pytest.raises(PetStateTransitionError):
        machine.land()


def test_dragging_does_not_advance_falling_physics() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_dragging()
    before = model.snapshot

    after = model.update(1.0, (_WORKSPACE,))

    assert after.state.motion is PetMotionState.DRAGGING
    assert after.state.behaviors == frozenset({PetBehaviorState.DRAG_STRUGGLE})
    assert after.position == before.position
    assert after.vertical_velocity == 0


def test_releasing_drag_starts_falling() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_dragging()

    model.release_drag()

    assert model.state.motion is PetMotionState.FALLING
    assert PetBehaviorState.DRAG_STRUGGLE not in model.state.behaviors


@pytest.mark.parametrize(
    ("candidate_x", "expected_x"),
    [(-500.0, -84.0), (1_000.0, 784.0)],
)
def test_drag_retains_a_sixteen_pixel_recoverable_strip(
    candidate_x: float,
    expected_x: float,
) -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_dragging()

    dragged = model.drag_to(Point(candidate_x, 200), (_WORKSPACE,))

    assert dragged.position == Point(expected_x, 200)


def test_drag_below_workspace_floor_release_clamps_then_recovers() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_dragging()
    dragged = model.drag_to(Point(-500, 650), (_WORKSPACE,))

    released = model.release_drag((_WORKSPACE,))

    assert dragged.position == Point(-84, 650)
    assert released.position == Point(0, 480)
    assert released.state.motion is PetMotionState.LANDING
    assert released.vertical_velocity == 0.0
    assert released.horizontal_velocity == 0.0


def test_fall_reaches_landing_then_returns_to_idle() -> None:
    model = PetMotionModel(
        Point(20, 470),
        _WINDOW,
        PetMotionConfig(
            gravity=1_000,
            landing_duration_seconds=0.2,
        ),
    )
    model.start_falling()

    landed = model.update(0.2, (_WORKSPACE,))
    settled = model.update(0.2, (_WORKSPACE,))

    assert landed.state.motion is PetMotionState.LANDING
    assert landed.position == Point(20, 480)
    assert settled.state.motion is PetMotionState.IDLE


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (Point(-50, 20), Point(0, 20)),
        (Point(760, 20), Point(700, 20)),
        (Point(20, -80), Point(20, 0)),
        (Point(20, 570), Point(20, 480)),
    ],
)
def test_workspace_clamps_every_screen_edge(
    candidate: Point,
    expected: Point,
) -> None:
    assert clamp_window_position(candidate, _WINDOW, _WORKSPACE) == expected


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (1.0, Rect(0, 0, 1920, 1080)),
        (1.25, Rect(0, 0, 1536, 864)),
        (1.5, Rect(0, 0, 1280, 720)),
        (2.0, Rect(0, 0, 960, 540)),
    ],
)
def test_physical_workspace_conversion_respects_display_scale(
    scale: float,
    expected: Rect,
) -> None:
    assert physical_to_logical_rect(Rect(0, 0, 1920, 1080), scale) == expected


def test_workspace_selection_prefers_greatest_overlap() -> None:
    left = Rect(-1920, 0, 1920, 1080)
    right = Rect(0, 0, 2560, 1440)

    selected = select_workspace(
        Point(-40, 100),
        Size(200, 200),
        (left, right),
    )

    assert selected is right


def test_workspace_selection_uses_nearest_display_when_offscreen() -> None:
    left = Rect(0, 0, 800, 600)
    right = Rect(1200, 0, 800, 600)

    selected = select_workspace(
        Point(980, 200),
        Size(100, 100),
        (left, right),
    )

    assert selected is right


def test_paused_motion_does_not_update_until_resumed() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_falling()
    model.pause()

    paused = model.update(10.0, (_WORKSPACE,))
    model.resume()
    resumed = model.update(0.1, (_WORKSPACE,))

    assert paused.state.lifecycle is PetLifecycleState.PAUSED
    assert paused.position == Point(20, 10)
    assert resumed.state.motion is PetMotionState.FALLING
    assert resumed.position.y > 10


def test_paused_pet_can_be_dragged_without_resuming_physics() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.pause()

    model.start_dragging()
    dragged = model.drag_to(Point(250, 180), (_WORKSPACE,))
    model.release_drag()
    after_release = model.update(10.0, (_WORKSPACE,))

    assert dragged.state.lifecycle is PetLifecycleState.PAUSED
    assert dragged.state.motion is PetMotionState.DRAGGING
    assert not dragged.state.behaviors
    assert after_release.state.lifecycle is PetLifecycleState.PAUSED
    assert after_release.state.motion is PetMotionState.IDLE
    assert after_release.position == Point(250, 180)


def test_idle_pet_is_recovered_when_a_monitor_workspace_disappears() -> None:
    model = PetMotionModel(Point(1_500, 100), _WINDOW)

    recovered = model.update(0.1, (Rect(0, 0, 800, 600),))

    assert recovered.state.motion is PetMotionState.IDLE
    assert recovered.position == Point(700, 480)
    assert recovered.position.y + _WINDOW.height == _WORKSPACE.bottom


def test_restored_settled_window_bottom_equals_workspace_bottom() -> None:
    model = PetMotionModel(Point(20, 480), _WINDOW)

    restored = model.restore_position(Point(300, 100), (_WORKSPACE,))

    assert restored.position == Point(300, 480)
    assert restored.position.y + _WINDOW.height == _WORKSPACE.bottom


def test_closing_rejects_interaction_and_stops_physics() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_falling()
    model.begin_closing()

    closed = model.update(10.0, (_WORKSPACE,))

    assert closed.state.lifecycle is PetLifecycleState.CLOSING
    assert closed.position == Point(20, 10)
    assert not model.accepts_interaction
    with pytest.raises(PetStateTransitionError):
        model.start_dragging()


def test_failed_close_recovery_is_paused_until_user_resumes() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.begin_closing()

    model.recover_failed_close()

    assert model.state.lifecycle is PetLifecycleState.PAUSED
    assert model.accepts_interaction
    assert model.update(10.0, (_WORKSPACE,)).position == Point(20, 10)
