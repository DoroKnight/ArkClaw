"""Deterministic animation intent and scheduling for the placeholder pet."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from sjtuclaw.application.pet_action_sequence import (
    SEQUENCE_CATALOG,
    PetActionName,
    SequenceName,
    SequenceTerminal,
)
from sjtuclaw.application.pet_autonomous_scheduler import (
    AutonomousActionScheduler,
    AutonomousSchedulerState,
    autonomous_state_for_action,
)
from sjtuclaw.application.pet_geometry import Rect, Size
from sjtuclaw.application.pet_motion import PetMotionModel, PetMotionSnapshot
from sjtuclaw.application.pet_production_actions import (
    ActionIntent,
    ActionOrigin,
    ActionSource,
    AutonomousExecutionMode,
    PendingExplicitIntent,
    ProductionAction,
    semantic_target,
)
from sjtuclaw.application.pet_role_pack import production_track0_action
from sjtuclaw.application.pet_state import (
    AnimationCompatibilityError,
    PetActivityState,
    PetBehaviorState,
    PetFacing,
    PetLayeredState,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
    ProposedStateTransition,
    assert_animation_compatible,
)
from sjtuclaw.application.pet_track0 import (
    ActionOutcome,
    ActionRequest,
    ArbitrationContext,
    CancellationMode,
    CancelReason,
    PetTrack0Controller,
    PlaybackEvent,
)

_PRODUCTION_SEQUENCE_BY_ACTION = {
    ProductionAction.RELAX: SequenceName.PRODUCTION_RELAX,
    ProductionAction.MOVE_LEFT: SequenceName.PRODUCTION_MOVE_LEFT,
    ProductionAction.MOVE_RIGHT: SequenceName.PRODUCTION_MOVE_RIGHT,
    ProductionAction.SIT: SequenceName.PRODUCTION_SIT,
    ProductionAction.SLEEP: SequenceName.PRODUCTION_SLEEP,
    ProductionAction.SPECIAL: SequenceName.PRODUCTION_SPECIAL,
    ProductionAction.INTERACT: SequenceName.PRODUCTION_INTERACT,
}
_PRODUCTION_LOOP_ACTIONS = frozenset(
    {
        ProductionAction.RELAX,
        ProductionAction.MOVE_LEFT,
        ProductionAction.MOVE_RIGHT,
        ProductionAction.SIT,
        ProductionAction.SLEEP,
    }
)
_PRODUCTION_PROTECTED_ACTIONS = frozenset(
    {ProductionAction.SPECIAL, ProductionAction.INTERACT}
)


class MonotonicClock(Protocol):
    def now(self) -> float:
        """Return monotonically increasing seconds."""


class SystemMonotonicClock:
    def now(self) -> float:
        return time.monotonic()


class PetAnimationEventType(StrEnum):
    """Semantic events that may also replace Track 0 playback."""

    START_READING = "start_reading"
    START_FALLING = "start_falling"
    START_WALKING = "start_walking"
    START_THINKING = "start_thinking"
    START_REMINDING = "start_reminding"
    START_DRAGGING = "start_dragging"
    RELEASE_DRAG = "release_drag"
    PAUSE = "pause"
    RESUME = "resume"
    BEGIN_CLOSING = "begin_closing"


_MANDATORY_INTERRUPTION_EVENTS = frozenset(
    {
        PetAnimationEventType.START_FALLING,
        PetAnimationEventType.START_DRAGGING,
        PetAnimationEventType.PAUSE,
        PetAnimationEventType.BEGIN_CLOSING,
    }
)


@dataclass(frozen=True, slots=True)
class PetAnimationEvent:
    """Content-free transaction input owned by the application layer."""

    event_type: PetAnimationEventType
    request_token: object
    facing: PetFacing | None = None
    input_session_token: object | None = None

    @classmethod
    def start_reading(cls, *, token: object) -> PetAnimationEvent:
        return cls(PetAnimationEventType.START_READING, token)

    @classmethod
    def start_falling(cls, *, token: object | None = None) -> PetAnimationEvent:
        return cls(
            PetAnimationEventType.START_FALLING,
            object() if token is None else token,
        )

    @classmethod
    def start_walking(
        cls,
        direction: PetFacing,
        *,
        token: object,
    ) -> PetAnimationEvent:
        return cls(PetAnimationEventType.START_WALKING, token, facing=direction)

    @classmethod
    def start_thinking(cls, *, token: object) -> PetAnimationEvent:
        return cls(PetAnimationEventType.START_THINKING, token)

    @classmethod
    def start_reminding(cls, *, token: object) -> PetAnimationEvent:
        return cls(PetAnimationEventType.START_REMINDING, token)

    @classmethod
    def start_dragging(
        cls,
        *,
        token: object,
        input_session_token: object,
    ) -> PetAnimationEvent:
        return cls(
            PetAnimationEventType.START_DRAGGING,
            token,
            input_session_token=input_session_token,
        )

    @classmethod
    def release_drag(
        cls,
        *,
        token: object,
        input_session_token: object,
    ) -> PetAnimationEvent:
        return cls(
            PetAnimationEventType.RELEASE_DRAG,
            token,
            input_session_token=input_session_token,
        )

    @classmethod
    def pause(cls, *, token: object) -> PetAnimationEvent:
        return cls(PetAnimationEventType.PAUSE, token)

    @classmethod
    def resume(cls, *, token: object) -> PetAnimationEvent:
        return cls(PetAnimationEventType.RESUME, token)

    @classmethod
    def begin_closing(cls, *, token: object) -> PetAnimationEvent:
        return cls(PetAnimationEventType.BEGIN_CLOSING, token)


@dataclass(frozen=True, slots=True)
class PetAnimationConfig:
    maximum_delta_seconds: float = 0.1
    breathing_cycle_seconds: float = 2.4
    blinking_duration_seconds: float = 0.14
    blinking_interval_min_seconds: float = 2.0
    blinking_interval_max_seconds: float = 5.0
    walking_duration_seconds: float = 2.4
    thinking_duration_seconds: float = 1.2
    reminder_duration_seconds: float = 0.9
    random_action_interval_min_seconds: float = 4.0
    random_action_interval_max_seconds: float = 8.0

    def __post_init__(self) -> None:
        positive = (
            self.maximum_delta_seconds,
            self.breathing_cycle_seconds,
            self.blinking_duration_seconds,
            self.blinking_interval_min_seconds,
            self.blinking_interval_max_seconds,
            self.walking_duration_seconds,
            self.thinking_duration_seconds,
            self.reminder_duration_seconds,
            self.random_action_interval_min_seconds,
            self.random_action_interval_max_seconds,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("Pet animation timing must be positive.")
        if (
            self.blinking_interval_min_seconds
            > self.blinking_interval_max_seconds
            or self.random_action_interval_min_seconds
            > self.random_action_interval_max_seconds
        ):
            raise ValueError("Pet animation interval bounds are invalid.")


@dataclass(frozen=True, slots=True)
class PetAnimationIntent:
    base_action: PetMotionState
    facing: PetFacing
    loop: bool
    progress: float
    overlays: frozenset[PetBehaviorState]

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("Animation progress must be normalized.")


@dataclass(frozen=True, slots=True)
class PetVisualParameters:
    breathing_amount: float
    eye_openness: float
    body_wiggle: float
    thinking_tilt: float
    reminder_pulse: float


@dataclass(frozen=True, slots=True)
class PetRenderFrame:
    state: PetLayeredState
    animation_time: float
    window_size: Size
    intent: PetAnimationIntent
    visual: PetVisualParameters


@dataclass(frozen=True, slots=True)
class PetAnimationSnapshot:
    motion: PetMotionSnapshot
    frame: PetRenderFrame
    applied_delta_seconds: float


class PetAnimationEngine:
    """Advance movement and visual scheduling using explicit delta time."""

    def __init__(
        self,
        motion: PetMotionModel,
        *,
        rng: random.Random | None = None,
        config: PetAnimationConfig | None = None,
        track0: PetTrack0Controller | None = None,
        autonomous_scheduler: AutonomousActionScheduler | None = None,
        clock: MonotonicClock | None = None,
    ) -> None:
        self._motion = motion
        self._rng = rng or random.Random()
        self._config = config or PetAnimationConfig()
        self._track0 = track0
        self._autonomous_scheduler = autonomous_scheduler
        self._clock = clock or SystemMonotonicClock()
        self._autonomous_scheduler_state: AutonomousSchedulerState | None = None
        self._execution_mode = AutonomousExecutionMode.AUTONOMOUS
        self._pending_explicit_action: PendingExplicitIntent | None = None
        self._resume_after_protected = False
        self._active_production_action: ProductionAction | None = None
        self._animation_time = 0.0
        self._blink_elapsed = 0.0
        self._action_remaining = 0.0
        self._next_blink = self._new_blink_interval()
        self._next_random_action = self._new_random_action_interval()
        self._last_applied_delta = 0.0
        self._drag_session_token: object | None = None

    @property
    def motion(self) -> PetMotionModel:
        return self._motion

    @property
    def track0(self) -> PetTrack0Controller | None:
        return self._track0

    @property
    def execution_mode(self) -> AutonomousExecutionMode:
        return self._execution_mode

    @property
    def pending_explicit_action(self) -> PendingExplicitIntent | None:
        return self._pending_explicit_action

    @property
    def resume_after_protected(self) -> bool:
        return self._resume_after_protected

    @property
    def autonomous_scheduler_state(self) -> AutonomousSchedulerState | None:
        return self._autonomous_scheduler_state

    @property
    def _production_sequencing_enabled(self) -> bool:
        return self._track0 is not None and self._track0.sequencing_enabled

    @property
    def frame(self) -> PetRenderFrame:
        state = self._motion.state
        progress = self._base_progress(state.motion)
        intent = PetAnimationIntent(
            base_action=state.motion,
            facing=state.facing,
            loop=state.motion
            in {
                PetMotionState.IDLE,
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            },
            progress=progress,
            overlays=state.behaviors,
        )
        return PetRenderFrame(
            state=state,
            animation_time=self._animation_time,
            window_size=self._motion.window_size,
            intent=intent,
            visual=self._visual_parameters(state, progress),
        )

    @property
    def last_applied_delta_seconds(self) -> float:
        return self._last_applied_delta

    def request_action(
        self,
        action: ProductionAction,
        source: ActionSource,
    ) -> ActionOutcome:
        """Submit one typed explicit production action through Track 0."""

        intent = ActionIntent(action, ActionOrigin.EXPLICIT, source, object())
        return self._submit_production_intent(intent)

    def resume_autonomous(self, source: ActionSource) -> ActionOutcome:
        """Leave explicit hold, or defer autonomous Relax until one-shot end."""

        command = ActionIntent(
            ProductionAction.RELAX,
            ActionOrigin.EXPLICIT,
            source,
            object(),
        )
        if self._active_request_is_protected():
            self._pending_explicit_action = None
            self._resume_after_protected = True
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
            return ActionOutcome.ACCEPTED

        outcome = self._submit_production_intent(command)
        if outcome is ActionOutcome.ACCEPTED:
            self._activate_autonomous(ProductionAction.RELAX)
        return outcome

    def start_autonomous(self) -> ActionOutcome:
        """Establish the initial autonomous Relax transaction at production startup."""

        if self._track0 is None:
            return ActionOutcome.LEGACY_DIRECT
        if self._track0.active_request is not None:
            return ActionOutcome.REJECTED_DUPLICATE
        outcome = self._recover_autonomous_relax()
        return outcome

    def contain_renderer_failure(self) -> ActionOutcome:
        """Stop motion and autonomy after the playback event boundary fails."""

        self._clear_protected_continuation()
        self._execution_mode = AutonomousExecutionMode.SUSPENDED
        self._active_production_action = None
        relax = semantic_target(ProductionAction.RELAX)
        self._motion.commit_state_transition(
            self._motion.states.propose(
                motion=relax.motion,
                activity=relax.activity,
                facing=relax.facing,
            )
        )
        if self._track0 is None:
            return ActionOutcome.LEGACY_DIRECT
        return self._track0.clear(CancelReason.RENDERER_FAILURE)

    def _submit_production_intent(self, intent: ActionIntent) -> ActionOutcome:
        track0 = self._track0
        if track0 is None:
            return ActionOutcome.LEGACY_DIRECT

        if self._active_request_is_protected():
            if intent.origin is not ActionOrigin.EXPLICIT:
                return ActionOutcome.REJECTED_PRIORITY
            self._pending_explicit_action = PendingExplicitIntent(
                intent.action,
                intent.source,
                intent.request_token,
            )
            self._resume_after_protected = False
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
            return ActionOutcome.ACCEPTED

        if (
            intent.origin is ActionOrigin.EXPLICIT
            and intent.action in _PRODUCTION_LOOP_ACTIONS
            and self._execution_mode is AutonomousExecutionMode.EXPLICIT_HOLD
            and self._active_production_action is intent.action
            and track0.state.confirmed_epoch is not None
        ):
            self._resume_after_protected = False
            return ActionOutcome.ACCEPTED

        target = semantic_target(intent.action)
        proposal = self._motion.states.propose(
            motion=target.motion,
            activity=target.activity,
            facing=target.facing,
        )
        sequence_name = _PRODUCTION_SEQUENCE_BY_ACTION[intent.action]
        entry = SEQUENCE_CATALOG[sequence_name]
        request = ActionRequest(
            sequence_name=sequence_name,
            interruption_class=entry.interruption_class,
            protected=entry.protected,
            request_token=intent.request_token,
            semantic_epoch=proposal.target_epoch,
            origin=intent.origin,
            source=intent.source,
        )
        try:
            assert_animation_compatible(
                proposal.target_state,
                production_track0_action(intent.action),
                track0.state.health,
            )
        except AnimationCompatibilityError:
            return ActionOutcome.REJECTED_INCOMPATIBLE_STATE

        preflight = track0.preflight(request)
        if preflight.outcome is not ActionOutcome.ACCEPTED:
            return preflight.outcome
        active = track0.active_request
        decision = track0.arbitrate(
            request,
            ArbitrationContext(
                incoming_mode=CancellationMode.REPLACE,
                playback_health=track0.state.health,
                confirmed_semantic_epoch=(
                    active.semantic_epoch
                    if active is not None and track0.state.confirmed_epoch is not None
                    else None
                ),
                active_action_compatible=self._active_playback_is_compatible(),
            ),
        )
        if decision.outcome is not ActionOutcome.ACCEPTED:
            return decision.outcome

        if intent.origin is ActionOrigin.EXPLICIT:
            self._clear_protected_continuation()
        self._motion.commit_state_transition(proposal)
        if active is None:
            outcome = track0.play(request)
        elif decision.mode is None:
            outcome = ActionOutcome.ACCEPTED
        else:
            outcome = track0.cancel(
                CancelReason.USER_INTERRUPT,
                decision.mode,
                replacement=request,
            )
        if outcome is not ActionOutcome.ACCEPTED:
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
            self._active_production_action = None
            if intent.action in {
                ProductionAction.MOVE_LEFT,
                ProductionAction.MOVE_RIGHT,
            }:
                relax = semantic_target(ProductionAction.RELAX)
                self._motion.commit_state_transition(
                    self._motion.states.propose(
                        motion=relax.motion,
                        activity=relax.activity,
                        facing=relax.facing,
                    )
                )
            self._assert_transaction_compatible()
            return outcome

        self._active_production_action = intent.action
        if intent.action in _PRODUCTION_PROTECTED_ACTIONS:
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
        elif intent.origin is ActionOrigin.EXPLICIT:
            self._execution_mode = AutonomousExecutionMode.EXPLICIT_HOLD
        else:
            self._execution_mode = AutonomousExecutionMode.AUTONOMOUS
        self._assert_transaction_compatible()
        return outcome

    def _active_request_is_protected(self) -> bool:
        track0 = self._track0
        active = None if track0 is None else track0.active_request
        return active is not None and active.protected

    def _clear_protected_continuation(self) -> None:
        self._pending_explicit_action = None
        self._resume_after_protected = False

    def _activate_autonomous(self, action: ProductionAction) -> None:
        track0 = self._track0
        confirmed = None if track0 is None else track0.state.confirmed_epoch
        if confirmed is None:
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
            self._autonomous_scheduler_state = None
            return
        scheduler = self._autonomous_scheduler
        self._execution_mode = AutonomousExecutionMode.AUTONOMOUS
        if scheduler is None:
            self._autonomous_scheduler_state = None
            return
        self._autonomous_scheduler_state = scheduler.enter(
            autonomous_state_for_action(action),
            entered_at=self._clock.now(),
            playback_generation=confirmed.generation,
            playback_token=confirmed.playback_token,
            rng=self._rng,
        )

    def handle_event(self, event: PetAnimationEvent) -> ActionOutcome:
        """Atomically coordinate one semantic proposal and Track 0 request."""

        if event.event_type in _MANDATORY_INTERRUPTION_EVENTS:
            self._clear_protected_continuation()
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
            self._active_production_action = None

        track0 = self._track0
        if track0 is None:
            return ActionOutcome.LEGACY_DIRECT

        proposal, sequence_name, cancel_reason = self._propose_event(event)
        if sequence_name is None:
            self._motion.commit_state_transition(proposal)
            outcome = track0.clear(cancel_reason)
            self._assert_transaction_compatible()
            return outcome
        entry = SEQUENCE_CATALOG[sequence_name]
        request = ActionRequest(
            sequence_name=sequence_name,
            interruption_class=entry.interruption_class,
            protected=entry.protected,
            request_token=event.request_token,
            semantic_epoch=proposal.target_epoch,
            input_session_token=event.input_session_token,
            origin=self._event_origin(event),
            source=self._event_source(event),
        )
        target_action = entry.sequence.steps[0].action
        try:
            assert_animation_compatible(
                proposal.target_state,
                target_action,
                track0.state.health,
            )
        except AnimationCompatibilityError:
            if proposal.mandatory_for_safety:
                return self._contain_mandatory_proposal(
                    proposal,
                    cancel_reason,
                )
            return ActionOutcome.REJECTED_INCOMPATIBLE_STATE

        preflight = track0.preflight(request)
        if preflight.outcome is not ActionOutcome.ACCEPTED:
            if not proposal.mandatory_for_safety:
                return preflight.outcome
            return self._contain_mandatory_proposal(proposal, cancel_reason)

        active = track0.active_request
        active_compatible = self._active_playback_is_compatible()
        confirmed_epoch = (
            active.semantic_epoch
            if active is not None and track0.state.confirmed_epoch is not None
            else None
        )
        decision = track0.arbitrate(
            request,
            ArbitrationContext(
                incoming_mode=CancellationMode.REPLACE,
                playback_health=track0.state.health,
                confirmed_semantic_epoch=confirmed_epoch,
                active_action_compatible=active_compatible,
            ),
        )
        if decision.outcome is not ActionOutcome.ACCEPTED:
            return decision.outcome

        self._motion.commit_state_transition(proposal)
        if active is None:
            outcome = track0.play(request)
        elif decision.mode is None:
            outcome = ActionOutcome.ACCEPTED
        else:
            outcome = track0.cancel(
                cancel_reason,
                decision.mode,
                replacement=request,
            )
        if event.event_type is PetAnimationEventType.RESUME:
            if outcome is ActionOutcome.ACCEPTED:
                self._active_production_action = ProductionAction.RELAX
                self._activate_autonomous(ProductionAction.RELAX)
            else:
                self._execution_mode = AutonomousExecutionMode.SUSPENDED
        self._assert_transaction_compatible()
        return outcome

    def _contain_mandatory_proposal(
        self,
        proposal: ProposedStateTransition,
        reason: CancelReason,
    ) -> ActionOutcome:
        track0 = self._track0
        if track0 is None:
            return ActionOutcome.LEGACY_DIRECT
        self._motion.commit_state_transition(proposal)
        outcome = track0.contain_preflight_failure(reason)
        self._assert_transaction_compatible()
        return outcome

    def handle_playback_event(self, event: PlaybackEvent) -> ActionOutcome:
        """Apply one renderer callback on the same serialized engine boundary."""

        track0 = self._track0
        if track0 is None:
            return ActionOutcome.LEGACY_DIRECT
        if not self._callback_matches_snapshot(event):
            outcome = track0.handle_completion(event)
            self._assert_transaction_compatible()
            return outcome

        completes_production_protected = (
            not event.loop_boundary
            and self._active_production_action in _PRODUCTION_PROTECTED_ACTIONS
            and self._active_request_is_protected()
        )
        active_request = track0.active_request
        completes_mandatory_recovery = (
            not event.loop_boundary
            and active_request is not None
            and active_request.sequence_name
            in {SequenceName.DRAG_RELEASE, SequenceName.FALL_RECOVERY, SequenceName.LANDING}
        )

        next_action = self._next_action_for_callback(event)
        continuation_request: ActionRequest | None = None
        if next_action is PetActionName.RETURN_IDLE:
            proposal = self._motion.states.propose(
                motion=PetMotionState.IDLE,
                activity=PetActivityState.NONE,
            )
            assert_animation_compatible(
                proposal.target_state,
                next_action,
                track0.state.health,
            )
            active = track0.active_request
            if active is None:
                return ActionOutcome.INVALID_SEQUENCE
            continuation_request = replace(
                active,
                semantic_epoch=proposal.target_epoch,
            )
            self._motion.commit_state_transition(proposal)

        reaches_idle_terminal = self._callback_reaches_idle_terminal(event)
        outcome = track0.handle_completion(
            event,
            continuation_request=continuation_request,
        )
        if outcome is ActionOutcome.ACCEPTED and completes_production_protected:
            pending = self._pending_explicit_action
            self._clear_protected_continuation()
            self._active_production_action = None
            if pending is not None:
                outcome = self._submit_production_intent(pending.intent)
            else:
                outcome = self._recover_autonomous_relax()
        elif outcome is ActionOutcome.ACCEPTED and completes_mandatory_recovery:
            clear_outcome = track0.clear(CancelReason.MOTION_OVERRIDE)
            if clear_outcome is ActionOutcome.CLEARED:
                outcome = self._recover_autonomous_relax()
            else:
                self._execution_mode = AutonomousExecutionMode.SUSPENDED
                outcome = clear_outcome
        if outcome is ActionOutcome.ACCEPTED and reaches_idle_terminal:
            outcome = self._start_idle_after_terminal()
        self._assert_transaction_compatible()
        return outcome

    def _recover_autonomous_relax(self) -> ActionOutcome:
        intent = ActionIntent(
            ProductionAction.RELAX,
            ActionOrigin.AUTONOMOUS,
            ActionSource.SCHEDULER,
            object(),
        )
        outcome = self._submit_production_intent(intent)
        if outcome is ActionOutcome.ACCEPTED:
            self._activate_autonomous(ProductionAction.RELAX)
        else:
            self._execution_mode = AutonomousExecutionMode.SUSPENDED
        return outcome

    def request_graceful_exit(self) -> ActionOutcome:
        """Arm a catalog-declared loop exit without guessing a duration."""

        track0 = self._track0
        if track0 is None or not track0.sequencing_enabled:
            return ActionOutcome.LEGACY_DIRECT
        return track0.cancel(
            CancelReason.USER_INTERRUPT,
            CancellationMode.GRACEFUL_EXIT,
        )

    def _callback_matches_snapshot(self, event: PlaybackEvent) -> bool:
        track0 = self._track0
        if track0 is None:
            return False
        snapshot = track0.runner.snapshot
        confirmed = snapshot.confirmed_epoch
        sequence = snapshot.sequence
        current_index = snapshot.current_index
        if confirmed is None or sequence is None or current_index is None:
            return False
        step = sequence.steps[current_index]
        return (
            event.generation == confirmed.generation
            and event.logical_action is confirmed.logical_action
            and event.logical_action is step.action
            and event.physical_name == confirmed.physical_name
            and event.playback_token is confirmed.playback_token
        )

    def _next_action_for_callback(
        self,
        event: PlaybackEvent,
    ) -> PetActionName | None:
        track0 = self._track0
        if track0 is None:
            return None
        snapshot = track0.runner.snapshot
        sequence = snapshot.sequence
        current_index = snapshot.current_index
        if sequence is None or current_index is None:
            return None
        step = sequence.steps[current_index]
        if step.loop:
            if not event.loop_boundary or not snapshot.pending_graceful_exit:
                return None
            exit_index = sequence.loop_exit_index
            return None if exit_index is None else sequence.steps[exit_index].action
        if event.loop_boundary:
            return None
        next_index = current_index + 1
        if next_index >= len(sequence.steps):
            return None
        return sequence.steps[next_index].action

    def _callback_reaches_idle_terminal(self, event: PlaybackEvent) -> bool:
        track0 = self._track0
        if track0 is None:
            return False
        snapshot = track0.runner.snapshot
        sequence = snapshot.sequence
        current_index = snapshot.current_index
        if sequence is None or current_index is None:
            return False
        step = sequence.steps[current_index]
        return (
            not step.loop
            and not event.loop_boundary
            and current_index + 1 == len(sequence.steps)
            and sequence.terminal is SequenceTerminal.IDLE
        )

    def _start_idle_after_terminal(self) -> ActionOutcome:
        track0 = self._track0
        if track0 is None:
            return ActionOutcome.LEGACY_DIRECT
        entry = SEQUENCE_CATALOG[SequenceName.IDLE]
        request = ActionRequest(
            sequence_name=SequenceName.IDLE,
            interruption_class=entry.interruption_class,
            protected=entry.protected,
            request_token=object(),
            semantic_epoch=self._motion.states.epoch,
        )
        preflight = track0.preflight(request)
        if preflight.outcome is not ActionOutcome.ACCEPTED:
            return track0.contain_preflight_failure(CancelReason.RENDERER_FAILURE)
        return track0.play(request)

    def _propose_event(
        self,
        event: PetAnimationEvent,
    ) -> tuple[ProposedStateTransition, SequenceName | None, CancelReason]:
        machine = self._motion.states
        if event.event_type is PetAnimationEventType.START_READING:
            return (
                machine.propose(activity=PetActivityState.READING),
                SequenceName.READ,
                CancelReason.USER_INTERRUPT,
            )
        if event.event_type is PetAnimationEventType.START_FALLING:
            return (
                machine.propose(
                    motion=PetMotionState.FALLING,
                    mandatory_for_safety=True,
                ),
                SequenceName.FALL_RECOVERY,
                CancelReason.MOTION_OVERRIDE,
            )
        if event.event_type is PetAnimationEventType.START_WALKING:
            direction = event.facing
            if direction is None:
                raise ValueError("walking event requires a facing direction")
            motion = (
                PetMotionState.WALKING_LEFT
                if direction is PetFacing.LEFT
                else PetMotionState.WALKING_RIGHT
            )
            sequence = (
                SequenceName.WALK_LEFT
                if direction is PetFacing.LEFT
                else SequenceName.WALK_RIGHT
            )
            return (
                machine.propose(motion=motion, facing=direction),
                sequence,
                CancelReason.USER_INTERRUPT,
            )
        if event.event_type is PetAnimationEventType.START_THINKING:
            return (
                machine.propose(
                    motion=PetMotionState.IDLE,
                    activity=PetActivityState.THINKING,
                ),
                SequenceName.THINK,
                CancelReason.USER_INTERRUPT,
            )
        if event.event_type is PetAnimationEventType.START_REMINDING:
            return (
                machine.propose(
                    motion=PetMotionState.IDLE,
                    activity=PetActivityState.REMINDING,
                ),
                SequenceName.REMIND,
                CancelReason.USER_INTERRUPT,
            )
        if event.event_type is PetAnimationEventType.START_DRAGGING:
            return (
                machine.propose(motion=PetMotionState.DRAGGING),
                SequenceName.DRAG_HOLD,
                CancelReason.USER_INTERRUPT,
            )
        if event.event_type is PetAnimationEventType.RELEASE_DRAG:
            return (
                machine.propose(motion=PetMotionState.FALLING),
                SequenceName.DRAG_RELEASE,
                CancelReason.MOTION_OVERRIDE,
            )
        if event.event_type is PetAnimationEventType.PAUSE:
            return (
                machine.propose(
                    lifecycle=PetLifecycleState.PAUSED,
                    mandatory_for_safety=True,
                ),
                None,
                CancelReason.PAUSE,
            )
        if event.event_type is PetAnimationEventType.RESUME:
            return (
                machine.propose(
                    lifecycle=PetLifecycleState.ACTIVE,
                    motion=PetMotionState.IDLE,
                    activity=PetActivityState.NONE,
                ),
                SequenceName.PRODUCTION_RELAX,
                CancelReason.USER_INTERRUPT,
            )
        if event.event_type is PetAnimationEventType.BEGIN_CLOSING:
            return (
                machine.propose(
                    lifecycle=PetLifecycleState.CLOSING,
                    mandatory_for_safety=True,
                ),
                None,
                CancelReason.SYSTEM_SHUTDOWN,
            )
        raise AssertionError("unhandled animation event")

    @staticmethod
    def _event_origin(event: PetAnimationEvent) -> ActionOrigin:
        if event.event_type in {
            PetAnimationEventType.START_FALLING,
            PetAnimationEventType.PAUSE,
            PetAnimationEventType.RESUME,
            PetAnimationEventType.BEGIN_CLOSING,
        }:
            return ActionOrigin.SYSTEM
        return ActionOrigin.EXPLICIT

    @staticmethod
    def _event_source(event: PetAnimationEvent) -> ActionSource:
        if event.event_type is PetAnimationEventType.START_FALLING:
            return ActionSource.MOTION
        if event.event_type in {
            PetAnimationEventType.PAUSE,
            PetAnimationEventType.RESUME,
            PetAnimationEventType.BEGIN_CLOSING,
        }:
            return ActionSource.LIFECYCLE
        return ActionSource.USER

    def _active_playback_is_compatible(self) -> bool:
        track0 = self._track0
        if track0 is None:
            return True
        try:
            assert_animation_compatible(
                self._motion.state,
                track0.state.desired_action,
                track0.state.health,
            )
        except AnimationCompatibilityError:
            return False
        return True

    def _assert_transaction_compatible(self) -> None:
        track0 = self._track0
        if track0 is None:
            return
        assert_animation_compatible(
            self._motion.state,
            track0.state.desired_action,
            track0.state.health,
        )

    def advance(
        self,
        elapsed_seconds: float,
        workspaces: tuple[Rect, ...],
    ) -> PetAnimationSnapshot:
        if elapsed_seconds < 0:
            raise ValueError("Elapsed animation time must not be negative.")
        if self._motion.state.lifecycle is not PetLifecycleState.ACTIVE:
            self._last_applied_delta = 0.0
            motion = self._motion.update(0.0, workspaces)
            return self._snapshot(motion)

        applied = min(
            elapsed_seconds,
            self._config.maximum_delta_seconds,
        )
        self._last_applied_delta = applied
        self._animation_time += applied
        self._advance_action(applied)
        self._advance_blink(applied)
        self._advance_random_action(applied)
        motion = self._motion.update(applied, workspaces)
        direction_turn = self._motion.take_pending_direction_turn()
        if direction_turn is not None:
            if self._active_production_action in {
                ProductionAction.MOVE_LEFT,
                ProductionAction.MOVE_RIGHT,
            }:
                self._commit_workspace_boundary_turn(direction_turn)
            else:
                self._motion.start_walking(direction_turn)
            motion = self._motion.snapshot
        return self._snapshot(motion)

    def _commit_workspace_boundary_turn(self, direction: PetFacing) -> None:
        self._clear_protected_continuation()
        self._execution_mode = AutonomousExecutionMode.SUSPENDED
        action = (
            ProductionAction.MOVE_LEFT
            if direction is PetFacing.LEFT
            else ProductionAction.MOVE_RIGHT
        )
        outcome = self._submit_production_intent(
            ActionIntent(
                action,
                ActionOrigin.SYSTEM,
                ActionSource.MOTION,
                object(),
            )
        )
        if outcome is ActionOutcome.ACCEPTED:
            self._activate_autonomous(action)

    def request_walk(self, direction: PetFacing) -> ActionOutcome:
        if self._production_sequencing_enabled:
            return self.handle_event(
                PetAnimationEvent.start_walking(direction, token=object())
            )
        self._motion.start_walking(direction)
        self._action_remaining = self._config.walking_duration_seconds
        return ActionOutcome.LEGACY_DIRECT

    def request_thinking_animation(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            return self.handle_event(
                PetAnimationEvent.start_thinking(token=object())
            )
        state = self._motion.state
        if state.motion in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            self._motion.stop_walking()
        self._motion.states.start_thinking()
        self._action_remaining = self._config.thinking_duration_seconds
        return ActionOutcome.LEGACY_DIRECT

    def request_reminder_animation(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            return self.handle_event(
                PetAnimationEvent.start_reminding(token=object())
            )
        self._motion.states.start_reminding()
        self._action_remaining = self._config.reminder_duration_seconds
        return ActionOutcome.LEGACY_DIRECT

    def start_dragging(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            session_token = object()
            outcome = self.handle_event(
                PetAnimationEvent.start_dragging(
                    token=object(),
                    input_session_token=session_token,
                )
            )
            if outcome is ActionOutcome.ACCEPTED:
                self._drag_session_token = session_token
                self._action_remaining = 0.0
            return outcome
        self._action_remaining = 0.0
        self._motion.start_dragging()
        return ActionOutcome.LEGACY_DIRECT

    def release_drag(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            session_token = self._drag_session_token
            if session_token is None:
                raise PetStateTransitionError
            outcome = self.handle_event(
                PetAnimationEvent.release_drag(
                    token=object(),
                    input_session_token=session_token,
                )
            )
            if outcome is ActionOutcome.ACCEPTED:
                self._drag_session_token = None
            return outcome
        self._motion.release_drag()
        return ActionOutcome.LEGACY_DIRECT

    def pause(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            return self.handle_event(PetAnimationEvent.pause(token=object()))
        self._motion.pause()
        return ActionOutcome.LEGACY_DIRECT

    def resume(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            return self.handle_event(PetAnimationEvent.resume(token=object()))
        self._motion.resume()
        return ActionOutcome.LEGACY_DIRECT

    def begin_closing(self) -> ActionOutcome:
        if self._production_sequencing_enabled:
            self._action_remaining = 0.0
            return self.handle_event(
                PetAnimationEvent.begin_closing(token=object())
            )
        self._action_remaining = 0.0
        self._motion.begin_closing()
        return ActionOutcome.LEGACY_DIRECT

    def recover_failed_close(self) -> None:
        self._motion.recover_failed_close()

    def _advance_action(self, elapsed_seconds: float) -> None:
        if self._action_remaining <= 0:
            return
        self._action_remaining = max(
            0.0,
            self._action_remaining - elapsed_seconds,
        )
        if self._action_remaining > 0:
            return
        state = self._motion.state
        try:
            if state.motion in {
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            }:
                self._motion.stop_walking()
            elif PetBehaviorState.THINKING in state.behaviors:
                self._motion.states.finish_thinking()
            elif PetBehaviorState.REMINDING in state.behaviors:
                self._motion.states.finish_reminding()
        except PetStateTransitionError:
            return
        self._next_random_action = self._new_random_action_interval()

    def _advance_blink(self, elapsed_seconds: float) -> None:
        state = self._motion.state
        if PetBehaviorState.BLINKING in state.behaviors:
            self._blink_elapsed += elapsed_seconds
            if (
                self._blink_elapsed
                >= self._config.blinking_duration_seconds
            ):
                self._motion.states.finish_blinking()
                self._blink_elapsed = 0.0
                self._next_blink = self._new_blink_interval()
            return
        self._next_blink -= elapsed_seconds
        if self._next_blink <= 0:
            self._motion.states.start_blinking()
            if PetBehaviorState.BLINKING in self._motion.state.behaviors:
                self._blink_elapsed = 0.0
            else:
                self._next_blink = self._new_blink_interval()

    def _advance_random_action(self, elapsed_seconds: float) -> None:
        state = self._motion.state
        if (
            self._action_remaining > 0
            or state.motion is not PetMotionState.IDLE
            or state.behaviors
            != frozenset({PetBehaviorState.BREATHING})
        ):
            return
        self._next_random_action -= elapsed_seconds
        if self._next_random_action > 0:
            return
        selection = self._rng.randrange(3)
        if selection == 0:
            self.request_walk(PetFacing.LEFT)
        elif selection == 1:
            self.request_walk(PetFacing.RIGHT)
        else:
            self.request_thinking_animation()

    def _base_progress(self, motion: PetMotionState) -> float:
        period = (
            self._motion.config.walking_cycle_seconds
            if motion
            in {
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            }
            else self._config.breathing_cycle_seconds
        )
        return (self._animation_time % period) / period

    def _visual_parameters(
        self,
        state: PetLayeredState,
        base_progress: float,
    ) -> PetVisualParameters:
        breathing = (
            (1.0 - math.cos(base_progress * math.tau)) / 2.0
            if PetBehaviorState.BREATHING in state.behaviors
            else 0.0
        )
        if PetBehaviorState.BLINKING in state.behaviors:
            blink_progress = min(
                1.0,
                self._blink_elapsed
                / self._config.blinking_duration_seconds,
            )
            eye_openness = abs(2.0 * blink_progress - 1.0)
        else:
            eye_openness = 1.0
        body_wiggle = (
            math.sin(self._animation_time * math.tau * 5.0)
            if PetBehaviorState.DRAG_STRUGGLE in state.behaviors
            else 0.0
        )
        thinking_tilt = (
            math.sin(self._animation_time * math.tau * 0.8)
            if PetBehaviorState.THINKING in state.behaviors
            else 0.0
        )
        reminder_pulse = (
            (1.0 - math.cos(self._animation_time * math.tau * 3.0))
            / 2.0
            if PetBehaviorState.REMINDING in state.behaviors
            else 0.0
        )
        return PetVisualParameters(
            breathing_amount=breathing,
            eye_openness=eye_openness,
            body_wiggle=body_wiggle,
            thinking_tilt=thinking_tilt,
            reminder_pulse=reminder_pulse,
        )

    def _new_blink_interval(self) -> float:
        return self._rng.uniform(
            self._config.blinking_interval_min_seconds,
            self._config.blinking_interval_max_seconds,
        )

    def _new_random_action_interval(self) -> float:
        return self._rng.uniform(
            self._config.random_action_interval_min_seconds,
            self._config.random_action_interval_max_seconds,
        )

    def _snapshot(
        self,
        motion: PetMotionSnapshot,
    ) -> PetAnimationSnapshot:
        return PetAnimationSnapshot(
            motion=motion,
            frame=self.frame,
            applied_delta_seconds=self._last_applied_delta,
        )
