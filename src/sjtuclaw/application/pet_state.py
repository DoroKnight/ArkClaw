"""Framework-independent layered state model for the placeholder pet."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PetLifecycleState(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSING = "closing"


class PetMotionState(Enum):
    IDLE = "idle"
    WALKING_LEFT = "walking_left"
    WALKING_RIGHT = "walking_right"
    DRAGGING = "dragging"
    FALLING = "falling"
    LANDING = "landing"


class PetBehaviorState(Enum):
    BREATHING = "breathing"
    BLINKING = "blinking"
    THINKING = "thinking"
    REMINDING = "reminding"
    DRAG_STRUGGLE = "drag_struggle"


class PetFacing(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class PetLayeredState:
    lifecycle: PetLifecycleState
    motion: PetMotionState
    behaviors: frozenset[PetBehaviorState]
    facing: PetFacing

    def __post_init__(self) -> None:
        validate_layered_state(self)


_STATE_PRIORITIES: dict[
    PetLifecycleState | PetMotionState | PetBehaviorState,
    int,
] = {
    PetLifecycleState.ACTIVE: 0,
    PetLifecycleState.PAUSED: 90,
    PetLifecycleState.CLOSING: 100,
    PetMotionState.IDLE: 10,
    PetMotionState.WALKING_LEFT: 40,
    PetMotionState.WALKING_RIGHT: 40,
    PetMotionState.DRAGGING: 80,
    PetMotionState.FALLING: 70,
    PetMotionState.LANDING: 70,
    PetBehaviorState.BREATHING: 10,
    PetBehaviorState.BLINKING: 10,
    PetBehaviorState.THINKING: 20,
    PetBehaviorState.REMINDING: 50,
    PetBehaviorState.DRAG_STRUGGLE: 80,
}


class PetStateTransitionError(RuntimeError):
    """Report invalid state without carrying application or model content."""

    def __init__(self) -> None:
        super().__init__("The desktop-pet state combination is not permitted.")


def validate_layered_state(state: PetLayeredState) -> None:
    """Reject combinations that violate lifecycle and motion ownership."""

    behaviors = state.behaviors
    if state.lifecycle is not PetLifecycleState.ACTIVE and behaviors:
        raise PetStateTransitionError
    if state.lifecycle is PetLifecycleState.CLOSING:
        if state.motion is not PetMotionState.IDLE:
            raise PetStateTransitionError
        return
    if state.lifecycle is PetLifecycleState.PAUSED:
        return
    if state.motion is PetMotionState.DRAGGING:
        if behaviors != frozenset({PetBehaviorState.DRAG_STRUGGLE}):
            raise PetStateTransitionError
        return
    if PetBehaviorState.DRAG_STRUGGLE in behaviors:
        raise PetStateTransitionError
    if state.motion in {PetMotionState.FALLING, PetMotionState.LANDING}:
        if behaviors:
            raise PetStateTransitionError
        return
    if (
        PetBehaviorState.REMINDING in behaviors
        and (
            state.motion is not PetMotionState.IDLE
            or behaviors != frozenset({PetBehaviorState.REMINDING})
        )
    ):
        raise PetStateTransitionError
    if PetBehaviorState.THINKING in behaviors:
        if state.motion is not PetMotionState.IDLE:
            raise PetStateTransitionError
        if PetBehaviorState.REMINDING in behaviors:
            raise PetStateTransitionError
    if (
        PetBehaviorState.BREATHING in behaviors
        and state.motion is not PetMotionState.IDLE
    ):
        raise PetStateTransitionError


def layered_state_priority(state: PetLayeredState) -> int:
    return max(
        _STATE_PRIORITIES[state.lifecycle],
        _STATE_PRIORITIES[state.motion],
        *(_STATE_PRIORITIES[behavior] for behavior in state.behaviors),
    )


class PetLayeredStateMachine:
    """Own lifecycle, exclusive motion, and composable visual behavior."""

    def __init__(self) -> None:
        self._lifecycle = PetLifecycleState.ACTIVE
        self._motion = PetMotionState.IDLE
        self._behaviors = {PetBehaviorState.BREATHING}
        self._facing = PetFacing.RIGHT

    @property
    def snapshot(self) -> PetLayeredState:
        return PetLayeredState(
            lifecycle=self._lifecycle,
            motion=self._motion,
            behaviors=frozenset(self._behaviors),
            facing=self._facing,
        )

    @property
    def lifecycle(self) -> PetLifecycleState:
        return self._lifecycle

    @property
    def motion(self) -> PetMotionState:
        return self._motion

    @property
    def behaviors(self) -> frozenset[PetBehaviorState]:
        return frozenset(self._behaviors)

    @property
    def facing(self) -> PetFacing:
        return self._facing

    def pause(self) -> None:
        if self._lifecycle is PetLifecycleState.CLOSING:
            raise PetStateTransitionError
        self._lifecycle = PetLifecycleState.PAUSED
        if self._motion is PetMotionState.DRAGGING:
            self._motion = PetMotionState.IDLE
        self._behaviors.clear()

    def resume(self) -> None:
        if self._lifecycle is not PetLifecycleState.PAUSED:
            raise PetStateTransitionError
        self._lifecycle = PetLifecycleState.ACTIVE
        self._restore_default_behavior()

    def begin_closing(self) -> None:
        if self._lifecycle is PetLifecycleState.CLOSING:
            return
        self._lifecycle = PetLifecycleState.CLOSING
        self._motion = PetMotionState.IDLE
        self._behaviors.clear()

    def recover_failed_close(self) -> None:
        if self._lifecycle is not PetLifecycleState.CLOSING:
            raise PetStateTransitionError
        self._lifecycle = PetLifecycleState.PAUSED
        self._motion = PetMotionState.IDLE
        self._behaviors.clear()

    def start_dragging(self) -> None:
        if self._lifecycle is PetLifecycleState.CLOSING:
            raise PetStateTransitionError
        self._motion = PetMotionState.DRAGGING
        self._behaviors = (
            {PetBehaviorState.DRAG_STRUGGLE}
            if self._lifecycle is PetLifecycleState.ACTIVE
            else set()
        )

    def release_drag(self) -> None:
        if (
            self._lifecycle is PetLifecycleState.PAUSED
            and self._motion is PetMotionState.DRAGGING
        ):
            self._motion = PetMotionState.IDLE
            self._behaviors.clear()
            return
        self._require_motion(PetMotionState.DRAGGING)
        self._motion = PetMotionState.FALLING
        self._behaviors.clear()

    def start_falling(self) -> None:
        self._require_active()
        if self._motion is PetMotionState.DRAGGING:
            raise PetStateTransitionError
        self._motion = PetMotionState.FALLING
        self._behaviors.clear()

    def land(self) -> None:
        self._require_motion(PetMotionState.FALLING)
        self._motion = PetMotionState.LANDING
        self._behaviors.clear()

    def finish_landing(self) -> None:
        self._require_motion(PetMotionState.LANDING)
        self._motion = PetMotionState.IDLE
        self._restore_default_behavior()

    def start_walking(self, direction: PetFacing) -> None:
        self._require_active()
        if PetBehaviorState.REMINDING in self._behaviors:
            raise PetStateTransitionError
        if self._motion not in {
            PetMotionState.IDLE,
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            raise PetStateTransitionError
        self._facing = direction
        self._motion = (
            PetMotionState.WALKING_LEFT
            if direction is PetFacing.LEFT
            else PetMotionState.WALKING_RIGHT
        )
        self._behaviors.discard(PetBehaviorState.BREATHING)
        self._behaviors.discard(PetBehaviorState.THINKING)
        self._behaviors.discard(PetBehaviorState.REMINDING)

    def stop_walking(self) -> None:
        if self._motion not in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            raise PetStateTransitionError
        self._motion = PetMotionState.IDLE
        self._restore_default_behavior()

    def start_thinking(self) -> None:
        self._require_active_idle()
        if PetBehaviorState.REMINDING in self._behaviors:
            raise PetStateTransitionError
        self._behaviors = {PetBehaviorState.THINKING}

    def finish_thinking(self) -> None:
        if PetBehaviorState.THINKING not in self._behaviors:
            raise PetStateTransitionError
        self._restore_default_behavior()

    def start_reminding(self) -> None:
        self._require_active()
        if self._motion in {
            PetMotionState.DRAGGING,
            PetMotionState.FALLING,
            PetMotionState.LANDING,
        }:
            raise PetStateTransitionError
        self._motion = PetMotionState.IDLE
        self._behaviors = {PetBehaviorState.REMINDING}

    def finish_reminding(self) -> None:
        if PetBehaviorState.REMINDING not in self._behaviors:
            raise PetStateTransitionError
        self._restore_default_behavior()

    def start_blinking(self) -> None:
        self._require_active()
        if self._motion in {
            PetMotionState.DRAGGING,
            PetMotionState.FALLING,
            PetMotionState.LANDING,
        }:
            return
        if PetBehaviorState.REMINDING in self._behaviors:
            return
        self._behaviors.add(PetBehaviorState.BLINKING)

    def finish_blinking(self) -> None:
        self._behaviors.discard(PetBehaviorState.BLINKING)

    def _restore_default_behavior(self) -> None:
        self._behaviors.clear()
        if (
            self._lifecycle is PetLifecycleState.ACTIVE
            and self._motion is PetMotionState.IDLE
        ):
            self._behaviors.add(PetBehaviorState.BREATHING)

    def _require_active(self) -> None:
        if self._lifecycle is not PetLifecycleState.ACTIVE:
            raise PetStateTransitionError

    def _require_active_idle(self) -> None:
        self._require_active()
        if self._motion is not PetMotionState.IDLE:
            raise PetStateTransitionError

    def _require_motion(self, expected: PetMotionState) -> None:
        self._require_active()
        if self._motion is not expected:
            raise PetStateTransitionError
