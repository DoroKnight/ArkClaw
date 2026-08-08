"""Pure Track 0 request arbitration and cancellation vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sjtuclaw.application.pet_action_sequence import (
    InterruptClass,
    PlaybackHealth,
    SequenceName,
)


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
