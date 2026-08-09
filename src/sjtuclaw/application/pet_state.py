"""Framework-independent layered state model for the placeholder pet."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType

from sjtuclaw.application.pet_action_sequence import PetActionName, PlaybackHealth


class PetLifecycleState(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSING = "closing"


class PetMotionState(Enum):
    IDLE = "idle"
    WALKING_LEFT = "walking_left"
    WALKING_RIGHT = "walking_right"
    RUNNING_LEFT = "running_left"
    RUNNING_RIGHT = "running_right"
    DRAGGING = "dragging"
    FALLING = "falling"
    LANDING = "landing"


class PetBehaviorState(Enum):
    BREATHING = "breathing"
    BLINKING = "blinking"
    THINKING = "thinking"
    REMINDING = "reminding"
    DRAG_STRUGGLE = "drag_struggle"


class PetActivityState(Enum):
    """Exclusive semantic Track 0 activity while motion is idle."""

    NONE = "none"
    SITTING = "sitting"
    SLEEPING = "sleeping"
    WAVING = "waving"
    HAPPY = "happy"
    THINKING = "thinking"
    READING = "reading"
    TYPING = "typing"
    REMINDING = "reminding"
    CONFUSED = "confused"
    ANGRY = "angry"


class PetFacing(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class PetLayeredState:
    lifecycle: PetLifecycleState
    motion: PetMotionState
    behaviors: frozenset[PetBehaviorState]
    facing: PetFacing
    activity: PetActivityState = PetActivityState.NONE

    def __post_init__(self) -> None:
        legacy_activity = _activity_from_legacy_behaviors(self.behaviors)
        if self.activity is PetActivityState.NONE and legacy_activity is not None:
            object.__setattr__(self, "activity", legacy_activity)
        elif legacy_activity is not None and legacy_activity is not self.activity:
            raise PetStateTransitionError

        projection = _legacy_behavior_for_activity(self.activity)
        if projection is not None and projection not in self.behaviors:
            object.__setattr__(self, "behaviors", self.behaviors | {projection})
        validate_layered_state(self)


@dataclass(frozen=True, slots=True)
class ProposedStateTransition:
    """Validated semantic transition whose target epoch is state-owned."""

    source_state: PetLayeredState
    target_state: PetLayeredState
    source_epoch: int
    target_epoch: int
    mandatory_for_safety: bool = False


_STATE_PRIORITIES: dict[
    PetLifecycleState | PetMotionState | PetBehaviorState | PetActivityState,
    int,
] = {
    PetLifecycleState.ACTIVE: 0,
    PetLifecycleState.PAUSED: 90,
    PetLifecycleState.CLOSING: 100,
    PetMotionState.IDLE: 10,
    PetMotionState.WALKING_LEFT: 40,
    PetMotionState.WALKING_RIGHT: 40,
    PetMotionState.RUNNING_LEFT: 45,
    PetMotionState.RUNNING_RIGHT: 45,
    PetMotionState.DRAGGING: 80,
    PetMotionState.FALLING: 70,
    PetMotionState.LANDING: 70,
    PetBehaviorState.BREATHING: 10,
    PetBehaviorState.BLINKING: 10,
    PetBehaviorState.THINKING: 20,
    PetBehaviorState.REMINDING: 50,
    PetBehaviorState.DRAG_STRUGGLE: 80,
    PetActivityState.NONE: 0,
    PetActivityState.SITTING: 20,
    PetActivityState.SLEEPING: 20,
    PetActivityState.WAVING: 30,
    PetActivityState.HAPPY: 30,
    PetActivityState.THINKING: 20,
    PetActivityState.READING: 20,
    PetActivityState.TYPING: 20,
    PetActivityState.REMINDING: 50,
    PetActivityState.CONFUSED: 30,
    PetActivityState.ANGRY: 30,
}


class PetStateTransitionError(RuntimeError):
    """Report invalid state without carrying application or model content."""

    def __init__(self) -> None:
        super().__init__("The desktop-pet state combination is not permitted.")


class AnimationCompatibilityError(RuntimeError):
    """Report an invalid semantic state and desired Track 0 action pair."""

    def __init__(self) -> None:
        super().__init__("The Track 0 action is incompatible with semantic state.")


def _activity_from_legacy_behaviors(
    behaviors: frozenset[PetBehaviorState],
) -> PetActivityState | None:
    projected: list[PetActivityState] = []
    if PetBehaviorState.THINKING in behaviors:
        projected.append(PetActivityState.THINKING)
    if PetBehaviorState.REMINDING in behaviors:
        projected.append(PetActivityState.REMINDING)
    if len(projected) > 1:
        raise PetStateTransitionError
    return projected[0] if projected else None


def _legacy_behavior_for_activity(
    activity: PetActivityState,
) -> PetBehaviorState | None:
    if activity is PetActivityState.THINKING:
        return PetBehaviorState.THINKING
    if activity is PetActivityState.REMINDING:
        return PetBehaviorState.REMINDING
    return None


def _behaviors_for_activity(
    activity: PetActivityState,
) -> frozenset[PetBehaviorState]:
    projection = _legacy_behavior_for_activity(activity)
    if projection is not None:
        return frozenset({projection})
    if activity is PetActivityState.NONE:
        return frozenset({PetBehaviorState.BREATHING})
    return frozenset()


def validate_layered_state(state: PetLayeredState) -> None:
    """Reject combinations that violate lifecycle and motion ownership."""

    behaviors = state.behaviors
    if state.lifecycle is not PetLifecycleState.ACTIVE:
        if behaviors or state.activity is not PetActivityState.NONE:
            raise PetStateTransitionError
        return
    if state.motion is not PetMotionState.IDLE and state.activity is not PetActivityState.NONE:
        raise PetStateTransitionError
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
    if state.motion in {
        PetMotionState.WALKING_LEFT,
        PetMotionState.WALKING_RIGHT,
        PetMotionState.RUNNING_LEFT,
        PetMotionState.RUNNING_RIGHT,
    }:
        if behaviors - {PetBehaviorState.BLINKING}:
            raise PetStateTransitionError
        return
    if state.activity is PetActivityState.REMINDING:
        if behaviors != frozenset({PetBehaviorState.REMINDING}):
            raise PetStateTransitionError
        return
    if state.activity is PetActivityState.THINKING:
        if (
            not behaviors.issubset({PetBehaviorState.THINKING, PetBehaviorState.BLINKING})
            or PetBehaviorState.THINKING not in behaviors
        ):
            raise PetStateTransitionError
        return
    if state.activity is not PetActivityState.NONE:
        if behaviors:
            raise PetStateTransitionError
        return
    if behaviors - {PetBehaviorState.BREATHING, PetBehaviorState.BLINKING}:
        raise PetStateTransitionError


def layered_state_priority(state: PetLayeredState) -> int:
    return max(
        _STATE_PRIORITIES[state.lifecycle],
        _STATE_PRIORITIES[state.motion],
        _STATE_PRIORITIES[state.activity],
        *(_STATE_PRIORITIES[behavior] for behavior in state.behaviors),
    )


SemanticTrack0Key = tuple[
    PetLifecycleState,
    PetMotionState,
    PetActivityState,
]


STATE_ACTION_COMPATIBILITY: Mapping[
    SemanticTrack0Key,
    frozenset[PetActionName],
] = MappingProxyType(
    {
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.IDLE,
            PetActivityState.NONE,
        ): frozenset({PetActionName.IDLE, PetActionName.RETURN_IDLE}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.WALKING_LEFT,
            PetActivityState.NONE,
        ): frozenset({PetActionName.WALK_LEFT}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.WALKING_RIGHT,
            PetActivityState.NONE,
        ): frozenset({PetActionName.WALK_RIGHT}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.RUNNING_LEFT,
            PetActivityState.NONE,
        ): frozenset({PetActionName.RUN_LEFT}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.RUNNING_RIGHT,
            PetActivityState.NONE,
        ): frozenset({PetActionName.RUN_RIGHT}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.DRAGGING,
            PetActivityState.NONE,
        ): frozenset({PetActionName.DRAG_START, PetActionName.DRAG_LOOP}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.FALLING,
            PetActivityState.NONE,
        ): frozenset({PetActionName.DRAG_END}),
        (
            PetLifecycleState.ACTIVE,
            PetMotionState.LANDING,
            PetActivityState.NONE,
        ): frozenset({PetActionName.LANDING}),
        **{
            (PetLifecycleState.ACTIVE, PetMotionState.IDLE, activity): actions
            for activity, actions in {
                PetActivityState.SITTING: frozenset(
                    {PetActionName.SIT_DOWN, PetActionName.SIT_IDLE}
                ),
                PetActivityState.SLEEPING: frozenset(
                    {
                        PetActionName.SLEEP_START,
                        PetActionName.SLEEP_LOOP,
                        PetActionName.SLEEP_END,
                    }
                ),
                PetActivityState.WAVING: frozenset({PetActionName.WAVE}),
                PetActivityState.HAPPY: frozenset({PetActionName.HAPPY}),
                PetActivityState.THINKING: frozenset({PetActionName.THINK}),
                PetActivityState.READING: frozenset({PetActionName.READ}),
                PetActivityState.TYPING: frozenset({PetActionName.TYPE}),
                PetActivityState.REMINDING: frozenset({PetActionName.REMIND}),
                PetActivityState.CONFUSED: frozenset({PetActionName.CONFUSED}),
                PetActivityState.ANGRY: frozenset({PetActionName.ANGRY}),
            }.items()
        },
    }
)


def assert_animation_compatible(
    state: PetLayeredState,
    action: PetActionName | None,
    health: PlaybackHealth,
) -> None:
    """Reject a desired Track 0 action not confirmed for semantic state."""

    validate_layered_state(state)
    if health is not PlaybackHealth.HEALTHY:
        if action is None:
            return
        raise AnimationCompatibilityError
    if state.lifecycle is not PetLifecycleState.ACTIVE:
        if action is None:
            return
        raise AnimationCompatibilityError
    allowed = STATE_ACTION_COMPATIBILITY.get(
        (state.lifecycle, state.motion, state.activity),
        frozenset(),
    )
    if action is None or action not in allowed:
        raise AnimationCompatibilityError


class PetLayeredStateMachine:
    """Own lifecycle, exclusive motion, and composable visual behavior."""

    def __init__(self, *, initial_epoch: int = 0) -> None:
        if initial_epoch < 0:
            raise ValueError("initial_epoch must be non-negative")
        self._lifecycle = PetLifecycleState.ACTIVE
        self._motion = PetMotionState.IDLE
        self._behaviors = {PetBehaviorState.BREATHING}
        self._facing = PetFacing.RIGHT
        self._activity = PetActivityState.NONE
        self._epoch = initial_epoch

    @property
    def snapshot(self) -> PetLayeredState:
        return PetLayeredState(
            lifecycle=self._lifecycle,
            motion=self._motion,
            behaviors=frozenset(self._behaviors),
            facing=self._facing,
            activity=self._activity,
        )

    @property
    def epoch(self) -> int:
        return self._epoch

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
    def activity(self) -> PetActivityState:
        return self._activity

    @property
    def facing(self) -> PetFacing:
        return self._facing

    def propose(
        self,
        *,
        lifecycle: PetLifecycleState | None = None,
        motion: PetMotionState | None = None,
        behaviors: frozenset[PetBehaviorState] | None = None,
        facing: PetFacing | None = None,
        activity: PetActivityState | None = None,
        mandatory_for_safety: bool = False,
    ) -> ProposedStateTransition:
        """Validate a possible state change without committing its epoch."""

        source = self.snapshot
        target_lifecycle = lifecycle or source.lifecycle
        target_motion = motion or source.motion
        target_facing = facing or source.facing
        target_activity = activity or source.activity
        target_behaviors = source.behaviors if behaviors is None else behaviors

        if target_lifecycle is not PetLifecycleState.ACTIVE:
            target_activity = PetActivityState.NONE
            target_behaviors = frozenset()
        elif motion is not None and target_motion is not PetMotionState.IDLE:
            target_activity = PetActivityState.NONE
            target_behaviors = (
                frozenset({PetBehaviorState.DRAG_STRUGGLE})
                if target_motion is PetMotionState.DRAGGING
                else frozenset()
            )
        elif activity is not None:
            target_behaviors = _behaviors_for_activity(target_activity)
        elif motion is not None and target_motion is PetMotionState.IDLE:
            target_activity = PetActivityState.NONE
            target_behaviors = frozenset({PetBehaviorState.BREATHING})

        target = replace(
            source,
            lifecycle=target_lifecycle,
            motion=target_motion,
            behaviors=target_behaviors,
            facing=target_facing,
            activity=target_activity,
        )
        return ProposedStateTransition(
            source_state=source,
            target_state=target,
            source_epoch=self._epoch,
            target_epoch=self._epoch + 1,
            mandatory_for_safety=mandatory_for_safety,
        )

    def commit(self, proposal: ProposedStateTransition) -> None:
        """Atomically install a current proposal at its exact target epoch."""

        if (
            proposal.source_epoch != self._epoch
            or proposal.source_state != self.snapshot
            or proposal.target_epoch != proposal.source_epoch + 1
        ):
            raise PetStateTransitionError
        self._install(proposal.target_state)
        self._epoch = proposal.target_epoch

    def pause(self) -> None:
        if self._lifecycle is PetLifecycleState.CLOSING:
            raise PetStateTransitionError
        self._lifecycle = PetLifecycleState.PAUSED
        if self._motion is PetMotionState.DRAGGING:
            self._motion = PetMotionState.IDLE
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        self._bump_epoch()

    def resume(self) -> None:
        if self._lifecycle is not PetLifecycleState.PAUSED:
            raise PetStateTransitionError
        self._lifecycle = PetLifecycleState.ACTIVE
        self._restore_default_behavior()
        self._bump_epoch()

    def begin_closing(self) -> None:
        if self._lifecycle is PetLifecycleState.CLOSING:
            return
        self._lifecycle = PetLifecycleState.CLOSING
        self._motion = PetMotionState.IDLE
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        self._bump_epoch()

    def recover_failed_close(self) -> None:
        if self._lifecycle is not PetLifecycleState.CLOSING:
            raise PetStateTransitionError
        self._lifecycle = PetLifecycleState.PAUSED
        self._motion = PetMotionState.IDLE
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        self._bump_epoch()

    def start_dragging(self) -> None:
        if self._lifecycle is PetLifecycleState.CLOSING:
            raise PetStateTransitionError
        self._motion = PetMotionState.DRAGGING
        self._activity = PetActivityState.NONE
        self._behaviors = (
            {PetBehaviorState.DRAG_STRUGGLE}
            if self._lifecycle is PetLifecycleState.ACTIVE
            else set()
        )
        self._bump_epoch()

    def release_drag(self) -> None:
        if self._lifecycle is PetLifecycleState.PAUSED and self._motion is PetMotionState.DRAGGING:
            self._motion = PetMotionState.IDLE
            self._activity = PetActivityState.NONE
            self._behaviors.clear()
            self._bump_epoch()
            return
        self._require_motion(PetMotionState.DRAGGING)
        self._motion = PetMotionState.FALLING
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        self._bump_epoch()

    def start_falling(self) -> None:
        self._require_active()
        if self._motion is PetMotionState.DRAGGING:
            raise PetStateTransitionError
        self._motion = PetMotionState.FALLING
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        self._bump_epoch()

    def land(self) -> None:
        self._require_motion(PetMotionState.FALLING)
        self._motion = PetMotionState.LANDING
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        self._bump_epoch()

    def finish_landing(self) -> None:
        self._require_motion(PetMotionState.LANDING)
        self._motion = PetMotionState.IDLE
        self._restore_default_behavior()
        self._bump_epoch()

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
        self._activity = PetActivityState.NONE
        self._behaviors.discard(PetBehaviorState.BREATHING)
        self._behaviors.discard(PetBehaviorState.THINKING)
        self._behaviors.discard(PetBehaviorState.REMINDING)
        self._bump_epoch()

    def stop_walking(self) -> None:
        if self._motion not in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            raise PetStateTransitionError
        self._motion = PetMotionState.IDLE
        self._restore_default_behavior()
        self._bump_epoch()

    def start_thinking(self) -> None:
        self._require_active_idle()
        if self._activity is PetActivityState.REMINDING:
            raise PetStateTransitionError
        self._activity = PetActivityState.THINKING
        self._behaviors = {PetBehaviorState.THINKING}
        self._bump_epoch()

    def finish_thinking(self) -> None:
        if self._activity is not PetActivityState.THINKING:
            raise PetStateTransitionError
        self._restore_default_behavior()
        self._bump_epoch()

    def start_reminding(self) -> None:
        self._require_active()
        if self._motion in {
            PetMotionState.DRAGGING,
            PetMotionState.FALLING,
            PetMotionState.LANDING,
        }:
            raise PetStateTransitionError
        self._motion = PetMotionState.IDLE
        self._activity = PetActivityState.REMINDING
        self._behaviors = {PetBehaviorState.REMINDING}
        self._bump_epoch()

    def finish_reminding(self) -> None:
        if self._activity is not PetActivityState.REMINDING:
            raise PetStateTransitionError
        self._restore_default_behavior()
        self._bump_epoch()

    def start_blinking(self) -> None:
        self._require_active()
        if self._motion in {
            PetMotionState.DRAGGING,
            PetMotionState.FALLING,
            PetMotionState.LANDING,
        }:
            return
        if self._activity is PetActivityState.REMINDING:
            return
        if self._activity not in {
            PetActivityState.NONE,
            PetActivityState.THINKING,
        }:
            return
        before = len(self._behaviors)
        self._behaviors.add(PetBehaviorState.BLINKING)
        if len(self._behaviors) != before:
            self._bump_epoch()

    def finish_blinking(self) -> None:
        before = len(self._behaviors)
        self._behaviors.discard(PetBehaviorState.BLINKING)
        if len(self._behaviors) != before:
            self._bump_epoch()

    def _restore_default_behavior(self) -> None:
        self._activity = PetActivityState.NONE
        self._behaviors.clear()
        if self._lifecycle is PetLifecycleState.ACTIVE and self._motion is PetMotionState.IDLE:
            self._behaviors.add(PetBehaviorState.BREATHING)

    def _install(self, state: PetLayeredState) -> None:
        self._lifecycle = state.lifecycle
        self._motion = state.motion
        self._behaviors = set(state.behaviors)
        self._facing = state.facing
        self._activity = state.activity

    def _bump_epoch(self) -> None:
        self._epoch += 1

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
