"""Pure Track 0 request arbitration and cancellation vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sjtuclaw.application.pet_action_sequence import (
    InterruptClass,
    PetActionName,
    PetActionSequence,
    PetActionStep,
    PlaybackHealth,
    SequenceName,
    SequenceTerminal,
)

type PlaybackToken = object


class CancelReason(StrEnum):
    """Why an accepted request must stop or replace current playback."""

    USER_INTERRUPT = "user_interrupt"
    SYSTEM_SHUTDOWN = "system_shutdown"
    MOTION_OVERRIDE = "motion_override"
    PAUSE = "pause"
    RENDERER_FAILURE = "renderer_failure"
    CALLBACK_TIMEOUT = "callback_timeout"


class CancellationMode(StrEnum):
    """How the Track 0 controller should apply a cancellation."""

    GRACEFUL_EXIT = "graceful_exit"
    IMMEDIATE_CLEAR = "immediate_clear"
    REPLACE = "replace"


class ActionOutcome(StrEnum):
    """Stable outcomes shared by arbitration and the future engine boundary."""

    ACCEPTED = "accepted"
    REJECTED_PRIORITY = "rejected_priority"
    REJECTED_DUPLICATE = "rejected_duplicate"
    REJECTED_INCOMPATIBLE_STATE = "rejected_incompatible_state"
    STALE_COMPLETION = "stale_completion"
    INVALID_SEQUENCE = "invalid_sequence"
    REGISTRY_MISMATCH = "registry_mismatch"
    PLAYER_FAILURE = "player_failure"
    CALLBACK_TIMEOUT = "callback_timeout"
    CLEARED = "cleared"
    PLAYBACK_DEGRADED = "playback_degraded"
    RENDERER_STATE_UNKNOWN = "renderer_state_unknown"
    SEQUENCING_DISABLED_CAPABILITY = "sequencing_disabled_capability"
    LEGACY_DIRECT = "legacy_direct"


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """Immutable request passed into the deterministic Track 0 arbiter."""

    sequence_name: SequenceName
    interruption_class: InterruptClass
    protected: bool
    request_token: object
    semantic_epoch: int
    input_session_token: object | None = None

    def __post_init__(self) -> None:
        if self.semantic_epoch < 0:
            raise ValueError("semantic_epoch must be non-negative")
        if self.interruption_class is InterruptClass.STRICT_ACTION and not self.protected:
            raise ValueError("strict requests must be protected")
        if (
            self.interruption_class is InterruptClass.USER_INTERACTION
            and self.input_session_token is None
        ):
            raise ValueError("user interaction requests require an input session")


@dataclass(frozen=True, slots=True)
class ArbitrationContext:
    """State facts supplied by authorities outside the pure arbiter."""

    incoming_mode: CancellationMode = CancellationMode.REPLACE
    runner_authorized_continuation: bool = False
    playback_health: PlaybackHealth = PlaybackHealth.HEALTHY
    confirmed_semantic_epoch: int | None = None
    active_action_compatible: bool = True


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    """An outcome and optional command for replacing active playback."""

    outcome: ActionOutcome
    mode: CancellationMode | None


class PetActionArbiter:
    """Apply the frozen priority and equal-class replacement matrix."""

    def decide(
        self,
        incoming: ActionRequest,
        active: ActionRequest | None,
        context: ArbitrationContext,
    ) -> ArbitrationDecision:
        """Return a deterministic decision without mutating state or playback."""

        if active is None:
            return ArbitrationDecision(ActionOutcome.ACCEPTED, None)

        if incoming.interruption_class is InterruptClass.SYSTEM_SHUTDOWN:
            mode = (
                None
                if active.interruption_class is InterruptClass.SYSTEM_SHUTDOWN
                else CancellationMode.IMMEDIATE_CLEAR
            )
            return ArbitrationDecision(ActionOutcome.ACCEPTED, mode)

        if incoming.interruption_class > active.interruption_class:
            return ArbitrationDecision(ActionOutcome.ACCEPTED, context.incoming_mode)
        if incoming.interruption_class < active.interruption_class:
            return ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)

        if context.runner_authorized_continuation:
            return ArbitrationDecision(ActionOutcome.ACCEPTED, None)

        if (
            incoming.sequence_name is active.sequence_name
            and incoming.request_token is active.request_token
        ):
            return ArbitrationDecision(ActionOutcome.REJECTED_DUPLICATE, None)

        return self._decide_equal_class(incoming, active, context)

    def _decide_equal_class(
        self,
        incoming: ActionRequest,
        active: ActionRequest,
        context: ArbitrationContext,
    ) -> ArbitrationDecision:
        interruption_class = incoming.interruption_class
        if interruption_class is InterruptClass.MOTION_SAFETY:
            return self._decide_motion_safety(incoming, active, context)
        if interruption_class is InterruptClass.USER_INTERACTION:
            return self._decide_user_interaction(incoming, active)
        if interruption_class is InterruptClass.STRICT_ACTION:
            return ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)
        if interruption_class is InterruptClass.NORMAL_ACTION:
            if incoming.sequence_name is not active.sequence_name and not active.protected:
                return ArbitrationDecision(
                    ActionOutcome.ACCEPTED,
                    CancellationMode.REPLACE,
                )
            return ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)
        if interruption_class is InterruptClass.IDLE:
            return ArbitrationDecision(ActionOutcome.REJECTED_DUPLICATE, None)
        if interruption_class is InterruptClass.SYSTEM_SHUTDOWN:
            return ArbitrationDecision(ActionOutcome.ACCEPTED, None)
        raise AssertionError("unhandled interrupt class")

    @staticmethod
    def _decide_motion_safety(
        incoming: ActionRequest,
        active: ActionRequest,
        context: ArbitrationContext,
    ) -> ArbitrationDecision:
        active_is_stale = (
            context.playback_health is not PlaybackHealth.HEALTHY
            or context.confirmed_semantic_epoch != active.semantic_epoch
            or not context.active_action_compatible
        )
        proposed_epoch_is_new = incoming.semantic_epoch != active.semantic_epoch
        if active_is_stale or proposed_epoch_is_new:
            return ArbitrationDecision(
                ActionOutcome.ACCEPTED,
                CancellationMode.REPLACE,
            )
        return ArbitrationDecision(ActionOutcome.REJECTED_DUPLICATE, None)

    @staticmethod
    def _decide_user_interaction(
        incoming: ActionRequest,
        active: ActionRequest,
    ) -> ArbitrationDecision:
        same_session = incoming.input_session_token is active.input_session_token
        if not same_session:
            return ArbitrationDecision(
                ActionOutcome.ACCEPTED,
                CancellationMode.REPLACE,
            )
        if incoming.sequence_name is active.sequence_name:
            return ArbitrationDecision(ActionOutcome.REJECTED_DUPLICATE, None)
        if (
            active.sequence_name is SequenceName.DRAG_HOLD
            and incoming.sequence_name is SequenceName.DRAG_RELEASE
        ):
            return ArbitrationDecision(
                ActionOutcome.ACCEPTED,
                CancellationMode.REPLACE,
            )
        return ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)


@dataclass(frozen=True, slots=True)
class ConfirmedPlaybackEpoch:
    """One player-confirmed physical playback command epoch."""

    generation: int
    logical_action: PetActionName
    physical_name: str
    playback_token: PlaybackToken

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if not self.physical_name:
            raise ValueError("physical_name must not be empty")


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    """Completion or loop-boundary event reported by the player."""

    generation: int
    logical_action: PetActionName
    physical_name: str
    playback_token: PlaybackToken
    loop_boundary: bool = False


@dataclass(frozen=True, slots=True)
class RunnerDirective:
    """Pure runner result for a controller to translate into player commands."""

    outcome: ActionOutcome
    next_index: int | None = None
    step: PetActionStep | None = None
    terminal: SequenceTerminal | None = None


@dataclass(frozen=True, slots=True)
class RunnerSnapshot:
    """Immutable view of runner-local sequencing progress."""

    sequence: PetActionSequence | None
    current_index: int | None
    pending_graceful_exit: bool
    confirmed_epoch: ConfirmedPlaybackEpoch | None


class PetSequenceRunner:
    """Advance one immutable sequence using only matching player callbacks."""

    def __init__(self) -> None:
        self._sequence: PetActionSequence | None = None
        self._current_index: int | None = None
        self._pending_graceful_exit = False
        self._confirmed_epoch: ConfirmedPlaybackEpoch | None = None

    @property
    def snapshot(self) -> RunnerSnapshot:
        return RunnerSnapshot(
            sequence=self._sequence,
            current_index=self._current_index,
            pending_graceful_exit=self._pending_graceful_exit,
            confirmed_epoch=self._confirmed_epoch,
        )

    def start(self, sequence: PetActionSequence) -> RunnerDirective:
        """Replace runner-local progress and select the sequence's first step."""

        self._sequence = sequence
        self._current_index = 0
        self._pending_graceful_exit = False
        self._confirmed_epoch = None
        return self._advance_directive(0)

    def accept_playback(
        self,
        *,
        generation: int,
        logical_action: PetActionName,
        physical_name: str,
        playback_token: PlaybackToken,
    ) -> ConfirmedPlaybackEpoch:
        """Record player confirmation for exactly the selected current step."""

        step = self._current_step()
        if logical_action is not step.action:
            raise ValueError("playback action does not match the current step")
        epoch = ConfirmedPlaybackEpoch(
            generation=generation,
            logical_action=logical_action,
            physical_name=physical_name,
            playback_token=playback_token,
        )
        self._confirmed_epoch = epoch
        return epoch

    def handle_completion(
        self,
        event: PlaybackEvent,
    ) -> RunnerDirective | None:
        """Advance only when every callback identity field matches."""

        if not self._event_matches_current_epoch(event):
            return RunnerDirective(ActionOutcome.STALE_COMPLETION)

        sequence = self._require_sequence()
        current_index = self._require_current_index()
        step = sequence.steps[current_index]

        if step.loop:
            if not event.loop_boundary:
                return RunnerDirective(ActionOutcome.STALE_COMPLETION)
            if not self._pending_graceful_exit:
                return None
            exit_index = sequence.loop_exit_index
            if exit_index is None:
                return RunnerDirective(ActionOutcome.INVALID_SEQUENCE)
            self._current_index = exit_index
            self._pending_graceful_exit = False
            self._confirmed_epoch = None
            return self._advance_directive(exit_index)

        if event.loop_boundary:
            return RunnerDirective(ActionOutcome.STALE_COMPLETION)

        next_index = current_index + 1
        self._confirmed_epoch = None
        if next_index < len(sequence.steps):
            self._current_index = next_index
            return self._advance_directive(next_index)

        terminal = sequence.terminal
        self.reset()
        return RunnerDirective(
            outcome=ActionOutcome.ACCEPTED,
            terminal=terminal,
        )

    def request_graceful_exit(self) -> ActionOutcome:
        """Arm the next matching loop boundary when this sequence has an exit."""

        sequence = self._sequence
        current_index = self._current_index
        if sequence is None or current_index is None:
            return ActionOutcome.INVALID_SEQUENCE
        if sequence.loop_index is None or sequence.loop_exit_index is None:
            return ActionOutcome.INVALID_SEQUENCE
        if current_index > sequence.loop_index:
            return ActionOutcome.INVALID_SEQUENCE
        if self._pending_graceful_exit:
            return ActionOutcome.REJECTED_DUPLICATE
        self._pending_graceful_exit = True
        return ActionOutcome.ACCEPTED

    def reset(self) -> None:
        """Clear only runner-local state; no generation or renderer is touched."""

        self._sequence = None
        self._current_index = None
        self._pending_graceful_exit = False
        self._confirmed_epoch = None

    def _advance_directive(self, index: int) -> RunnerDirective:
        sequence = self._require_sequence()
        return RunnerDirective(
            outcome=ActionOutcome.ACCEPTED,
            next_index=index,
            step=sequence.steps[index],
        )

    def _event_matches_current_epoch(self, event: PlaybackEvent) -> bool:
        epoch = self._confirmed_epoch
        if epoch is None:
            return False
        try:
            step = self._current_step()
        except RuntimeError:
            return False
        return (
            event.generation == epoch.generation
            and event.logical_action is epoch.logical_action
            and event.logical_action is step.action
            and event.physical_name == epoch.physical_name
            and event.playback_token is epoch.playback_token
        )

    def _current_step(self) -> PetActionStep:
        sequence = self._require_sequence()
        return sequence.steps[self._require_current_index()]

    def _require_sequence(self) -> PetActionSequence:
        if self._sequence is None:
            raise RuntimeError("no active sequence")
        return self._sequence

    def _require_current_index(self) -> int:
        if self._current_index is None:
            raise RuntimeError("no active sequence step")
        return self._current_index
