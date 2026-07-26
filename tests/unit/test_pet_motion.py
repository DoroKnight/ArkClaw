from __future__ import annotations

import pytest

from sjtuclaw.application.pet_geometry import (
    Point,
    Rect,
    Size,
    clamp_window_position,
    physical_to_logical_rect,
    select_workspace,
)
from sjtuclaw.application.pet_motion import (
    PetMotionConfig,
    PetMotionModel,
)
from sjtuclaw.application.pet_state import (
    PET_STATE_SPECS,
    PetState,
    PetStateMachine,
    PetStateTransitionError,
)

_WINDOW = Size(100, 120)
_WORKSPACE = Rect(0, 0, 800, 600)


def test_every_pet_state_has_an_explicit_lifecycle_contract() -> None:
    assert set(PET_STATE_SPECS) == set(PetState)
    assert PET_STATE_SPECS[PetState.CLOSING].priority == max(
        spec.priority for spec in PET_STATE_SPECS.values()
    )
    assert not PET_STATE_SPECS[PetState.CLOSING].interruptible
    assert all(spec.entry_condition for spec in PET_STATE_SPECS.values())
    assert all(spec.exit_condition for spec in PET_STATE_SPECS.values())


def test_state_machine_accepts_the_reviewed_drag_fall_land_path() -> None:
    machine = PetStateMachine()

    machine.transition(PetState.DRAGGING)
    machine.transition(PetState.FALLING)
    machine.transition(PetState.LANDING)
    machine.transition(PetState.IDLE)

    assert machine.state is PetState.IDLE


def test_state_machine_rejects_an_illegal_direct_landing() -> None:
    machine = PetStateMachine()

    with pytest.raises(PetStateTransitionError):
        machine.transition(PetState.LANDING)


def test_dragging_does_not_advance_falling_physics() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_dragging()
    before = model.snapshot

    after = model.update(1.0, (_WORKSPACE,))

    assert after.state is PetState.DRAGGING
    assert after.position == before.position
    assert after.vertical_velocity == 0


def test_releasing_drag_starts_falling() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_dragging()

    model.release_drag()

    assert model.state is PetState.FALLING


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

    assert landed.state is PetState.LANDING
    assert landed.position == Point(20, 480)
    assert settled.state is PetState.IDLE


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
    assert (
        physical_to_logical_rect(Rect(0, 0, 1920, 1080), scale)
        == expected
    )


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

    assert paused.state is PetState.PAUSED
    assert paused.position == Point(20, 10)
    assert resumed.state is PetState.FALLING
    assert resumed.position.y > 10


def test_idle_pet_is_recovered_when_a_monitor_workspace_disappears() -> None:
    model = PetMotionModel(Point(1_500, 100), _WINDOW)

    recovered = model.update(0.1, (Rect(0, 0, 800, 600),))

    assert recovered.state is PetState.IDLE
    assert recovered.position == Point(700, 100)


def test_closing_rejects_interaction_and_stops_physics() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.start_falling()
    model.begin_closing()

    closed = model.update(10.0, (_WORKSPACE,))

    assert closed.state is PetState.CLOSING
    assert closed.position == Point(20, 10)
    assert not model.accepts_interaction
    with pytest.raises(PetStateTransitionError):
        model.start_dragging()


def test_failed_close_recovery_is_paused_until_user_resumes() -> None:
    model = PetMotionModel(Point(20, 10), _WINDOW)
    model.begin_closing()

    model.recover_failed_close()

    assert model.state is PetState.PAUSED
    assert not model.accepts_interaction
