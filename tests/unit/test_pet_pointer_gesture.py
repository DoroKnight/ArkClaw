"""Public-state tests for click/drag disambiguation."""

from __future__ import annotations

import pytest

from arkclaw.application.pet_geometry import Point
from arkclaw.presentation.pet_pointer_gesture import (
    GestureCancelReason,
    GestureDecision,
    PetPointerGesture,
    PointerGestureState,
)


def test_release_below_snapshot_threshold_is_one_click() -> None:
    gesture = PetPointerGesture()

    assert gesture.press(Point(8.0, 9.0), Point(100.0, 100.0), 10.0) is GestureDecision.NONE
    assert gesture.move(Point(104.0, 105.0)) is GestureDecision.NONE
    assert gesture.release(Point(104.0, 105.0)) is GestureDecision.CLICK
    assert gesture.state is PointerGestureState.IDLE


def test_crossing_manhattan_threshold_begins_drag_once() -> None:
    gesture = PetPointerGesture()
    gesture.press(Point(8.0, 9.0), Point(100.0, 100.0), 10.0)

    assert gesture.move(Point(104.0, 105.0)) is GestureDecision.NONE
    assert gesture.move(Point(105.0, 105.0)) is GestureDecision.BEGIN_DRAG
    assert gesture.move(Point(106.0, 105.0)) is GestureDecision.DRAG
    assert gesture.release(Point(106.0, 105.0)) is GestureDecision.RELEASE_ACTIVE_DRAG


def test_threshold_is_snapshotted_by_each_press() -> None:
    gesture = PetPointerGesture()
    gesture.press(Point(0.0, 0.0), Point(0.0, 0.0), 10.0)

    assert gesture.move(Point(6.0, 0.0)) is GestureDecision.NONE
    assert gesture.release(Point(6.0, 0.0)) is GestureDecision.CLICK

    gesture.press(Point(0.0, 0.0), Point(0.0, 0.0), 4.0)
    assert gesture.move(Point(6.0, 0.0)) is GestureDecision.BEGIN_DRAG


@pytest.mark.parametrize("threshold", [0.0, -1.0, float("nan"), float("inf")])
def test_press_rejects_invalid_drag_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="drag threshold"):
        PetPointerGesture().press(
            Point(0.0, 0.0), Point(0.0, 0.0), threshold
        )


def test_pending_and_dragging_cancellation_have_distinct_decisions() -> None:
    pending = PetPointerGesture()
    pending.press(Point(0.0, 0.0), Point(0.0, 0.0), 5.0)
    assert (
        pending.cancel(GestureCancelReason.POINTER_CAPTURE_LOST)
        is GestureDecision.CANCEL_PENDING
    )

    dragging = PetPointerGesture()
    dragging.press(Point(0.0, 0.0), Point(0.0, 0.0), 5.0)
    assert dragging.move(Point(5.0, 0.0)) is GestureDecision.BEGIN_DRAG
    assert (
        dragging.cancel(GestureCancelReason.POINTER_CAPTURE_LOST)
        is GestureDecision.RELEASE_ACTIVE_DRAG
    )

    failed = PetPointerGesture()
    failed.press(Point(0.0, 0.0), Point(0.0, 0.0), 5.0)
    failed.move(Point(5.0, 0.0))
    assert (
        failed.cancel(GestureCancelReason.RENDERER_DEGRADED)
        is GestureDecision.ABORT_ACTIVE_DRAG
    )
