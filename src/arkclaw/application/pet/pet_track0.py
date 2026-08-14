"""Pure Track 0 request arbitration and cancellation vocabulary.

Provenance: this is an independent Python rewrite informed by the ArkPets
project by Harry Huang (GPL-3.0), specifically ``AnimData.java``,
``AnimComposer.java``, ``AnimClipGroup.java``, and ``AnimClip.java`` under
``core/src/cn/harryh/arkpets/animations``. No ArkPets Java source or comments,
character assets, mobility logic, root-motion ownership, or stochastic
behavior matrix are vendored or reproduced here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from arkclaw.application.pet.pet_action_sequence import (
    SEQUENCE_CATALOG,
    AnimationRegistry,
    AnimationRegistryError,
    InterruptClass,
    PetActionName,
    PetActionSequence,
    PetActionStep,
    PlaybackHealth,
    SequenceCatalogEntry,
    SequenceName,
    SequenceTerminal,
)
from arkclaw.application.pet.pet_production_actions import (
    ActionOrigin,
    ActionSource,
    validate_action_authority,
)

if TYPE_CHECKING:
    from arkclaw.application.pet.pet_animation import MonotonicClock

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
    origin: ActionOrigin = ActionOrigin.SYSTEM
    source: ActionSource = ActionSource.LIFECYCLE

    def __post_init__(self) -> None:
        validate_action_authority(self.origin, self.source)
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
            if (
                incoming.origin is ActionOrigin.EXPLICIT
                and active.origin is ActionOrigin.AUTONOMOUS
            ):
                return ArbitrationDecision(
                    ActionOutcome.ACCEPTED,
                    CancellationMode.REPLACE,
                )
            if (
                incoming.origin is ActionOrigin.AUTONOMOUS
                and active.origin is ActionOrigin.EXPLICIT
            ):
                return ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)
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
    boundary_index: int | None = None


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


@dataclass(frozen=True, slots=True)
class AnimationPlayerCapabilities:
    """Capabilities required before completion-driven sequencing is enabled."""

    completion_callbacks: bool
    loop_boundary_callbacks: bool
    duration_metadata: bool
    liveness_reporting: bool


def sequencing_enabled(capabilities: AnimationPlayerCapabilities) -> bool:
    """Require the complete callback, duration, and liveness contract."""

    return all(
        (
            capabilities.completion_callbacks,
            capabilities.loop_boundary_callbacks,
            capabilities.duration_metadata,
            capabilities.liveness_reporting,
        )
    )


@dataclass(frozen=True, slots=True)
class WatchdogPolicy:
    """Bounded completion/boundary timeout tolerance."""

    tolerance_ratio: float = 0.25
    minimum_tolerance_seconds: float = 0.25
    maximum_tolerance_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.tolerance_ratio < 0:
            raise ValueError("tolerance_ratio must be non-negative")
        if self.minimum_tolerance_seconds < 0:
            raise ValueError("minimum tolerance must be non-negative")
        if self.maximum_tolerance_seconds < self.minimum_tolerance_seconds:
            raise ValueError("watchdog tolerance bounds are invalid")

    def deadline(
        self,
        start: float,
        source_duration: float,
        speed: float,
    ) -> float:
        if source_duration <= 0:
            raise ValueError("source_duration must be positive")
        if speed <= 0:
            raise ValueError("speed must be positive")
        effective_duration = source_duration / speed
        tolerance = min(
            self.maximum_tolerance_seconds,
            max(
                self.minimum_tolerance_seconds,
                self.tolerance_ratio * effective_duration,
            ),
        )
        return start + effective_duration + tolerance


class _SystemMonotonicClock:
    def now(self) -> float:
        return time.monotonic()


@dataclass(frozen=True, slots=True)
class PlaybackRequest:
    """One concrete logical-to-physical player command."""

    generation: int
    track: int
    logical_action: PetActionName
    physical_name: str
    loop: bool
    speed: float
    mix_seconds: float

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if self.track not in {0, 1, 2}:
            raise ValueError("track must be 0, 1, or 2")
        if not self.physical_name:
            raise ValueError("physical_name must not be empty")
        if self.speed <= 0:
            raise ValueError("speed must be positive")
        if self.mix_seconds < 0:
            raise ValueError("mix_seconds must be non-negative")


class AnimationPlayer(Protocol):
    """Renderer-neutral player boundary used by the Track 0 controller."""

    @property
    def capabilities(self) -> AnimationPlayerCapabilities: ...

    def play(self, request: PlaybackRequest) -> PlaybackToken: ...

    def clear(self, track: int, mix_seconds: float) -> None: ...


@dataclass(frozen=True, slots=True)
class Track0PlaybackState:
    """Separate desired intent, confirmed player epoch, and renderer health."""

    desired_action: PetActionName | None
    confirmed_epoch: ConfirmedPlaybackEpoch | None
    health: PlaybackHealth


@dataclass(frozen=True, slots=True)
class ControllerPreflight:
    """Read-only validation result produced before any runner/player mutation."""

    outcome: ActionOutcome
    entry: SequenceCatalogEntry | None = None


class PetTrack0Controller:
    """Thin transaction coordinator for Track 0 sequencing and player state."""

    def __init__(
        self,
        *,
        player: AnimationPlayer,
        registry: AnimationRegistry,
        arbiter: PetActionArbiter | None = None,
        runner: PetSequenceRunner | None = None,
        clock: MonotonicClock | None = None,
        watchdog_policy: WatchdogPolicy | None = None,
    ) -> None:
        self._player = player
        self._registry = registry
        self._arbiter = arbiter or PetActionArbiter()
        self._runner = runner or PetSequenceRunner()
        self._clock = clock or _SystemMonotonicClock()
        self._watchdog_policy = watchdog_policy or WatchdogPolicy()
        self._watchdog_deadline: float | None = None
        self._generation = 0
        self._active_request: ActionRequest | None = None
        self._state = Track0PlaybackState(None, None, PlaybackHealth.HEALTHY)

    @property
    def state(self) -> Track0PlaybackState:
        return self._state

    @property
    def runner(self) -> PetSequenceRunner:
        return self._runner

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def active_request(self) -> ActionRequest | None:
        return self._active_request

    @property
    def watchdog_deadline(self) -> float | None:
        return self._watchdog_deadline

    @property
    def sequencing_enabled(self) -> bool:
        return sequencing_enabled(self._player.capabilities)

    def preflight(self, request: ActionRequest) -> ControllerPreflight:
        """Validate catalog and registry facts without changing any state."""

        entry = SEQUENCE_CATALOG.get(request.sequence_name)
        if entry is None or entry.track != 0:
            return ControllerPreflight(ActionOutcome.INVALID_SEQUENCE)
        if (
            request.interruption_class is not entry.interruption_class
            or request.protected is not entry.protected
        ):
            return ControllerPreflight(ActionOutcome.INVALID_SEQUENCE)
        if not sequencing_enabled(self._player.capabilities):
            return ControllerPreflight(ActionOutcome.SEQUENCING_DISABLED_CAPABILITY)
        try:
            self._registry.validate_sequence(
                entry,
                require_duration_metadata=True,
            )
        except AnimationRegistryError:
            return ControllerPreflight(ActionOutcome.REGISTRY_MISMATCH)
        return ControllerPreflight(ActionOutcome.ACCEPTED, entry)

    def arbitrate(
        self,
        request: ActionRequest,
        context: ArbitrationContext,
    ) -> ArbitrationDecision:
        """Decide against the current request without mutating playback."""

        return self._arbiter.decide(request, self._active_request, context)

    def play(self, request: ActionRequest) -> ActionOutcome:
        """Start a preflighted sequence and attempt its first physical play."""

        if self._active_request is not None:
            return ActionOutcome.REJECTED_PRIORITY
        preflight = self.preflight(request)
        if preflight.outcome is not ActionOutcome.ACCEPTED:
            return preflight.outcome
        entry = preflight.entry
        if entry is None:
            return ActionOutcome.INVALID_SEQUENCE
        directive = self._runner.start(entry.sequence)
        return self._play_directive(request, directive)

    def cancel(
        self,
        reason: CancelReason,
        mode: CancellationMode,
        *,
        replacement: ActionRequest | None = None,
    ) -> ActionOutcome:
        """Apply one explicit cancellation mode; never synthesize fallback idle."""

        if mode is CancellationMode.GRACEFUL_EXIT:
            outcome = self._runner.request_graceful_exit()
            if outcome is ActionOutcome.ACCEPTED:
                self._arm_current_loop_boundary_watchdog()
            return outcome
        if mode is CancellationMode.IMMEDIATE_CLEAR:
            return self.clear(reason)
        if mode is CancellationMode.REPLACE:
            if replacement is None:
                return ActionOutcome.INVALID_SEQUENCE
            preflight = self.preflight(replacement)
            if preflight.outcome is not ActionOutcome.ACCEPTED:
                return preflight.outcome
            self._watchdog_deadline = None
            self._runner.reset()
            self._active_request = None
            self._state = Track0PlaybackState(
                None,
                None,
                self._state.health,
            )
            return self.play(replacement)
        raise AssertionError("unhandled cancellation mode")

    def clear(self, reason: CancelReason) -> ActionOutcome:
        """Unconditionally invalidate and clear Track 0 without playing idle."""

        del reason
        prior_health = self._state.health
        self._watchdog_deadline = None
        self._allocate_generation()
        try:
            self._player.clear(0, 0.0)
        except Exception:
            self._runner.reset()
            self._active_request = None
            self._state = Track0PlaybackState(
                None,
                None,
                PlaybackHealth.UNKNOWN,
            )
            return ActionOutcome.RENDERER_STATE_UNKNOWN

        self._runner.reset()
        self._active_request = None
        self._state = Track0PlaybackState(None, None, prior_health)
        return ActionOutcome.CLEARED

    def adopt_active_playback(self, request: ActionRequest) -> ActionOutcome:
        """Change request ownership without restarting identical playback."""

        preflight = self.preflight(request)
        if preflight.outcome is not ActionOutcome.ACCEPTED:
            return preflight.outcome
        entry = preflight.entry
        confirmed = self._state.confirmed_epoch
        snapshot = self._runner.snapshot
        if (
            self._active_request is None
            or entry is None
            or confirmed is None
            or snapshot.sequence is None
            or snapshot.current_index is None
            or len(entry.sequence.steps) != 1
        ):
            return ActionOutcome.REJECTED_INCOMPATIBLE_STATE
        current_step = snapshot.sequence.steps[snapshot.current_index]
        adopted_step = entry.sequence.steps[0]
        try:
            adopted_binding = self._registry.resolve(adopted_step.action)
        except KeyError:
            return ActionOutcome.REGISTRY_MISMATCH
        if (
            current_step.action is not adopted_step.action
            or current_step.loop is not adopted_step.loop
            or confirmed.logical_action is not adopted_step.action
            or confirmed.physical_name != adopted_binding.physical_name
        ):
            return ActionOutcome.REJECTED_INCOMPATIBLE_STATE
        self._active_request = request
        return ActionOutcome.ACCEPTED

    def contain_preflight_failure(
        self,
        reason: CancelReason,
    ) -> ActionOutcome:
        """Invalidate old playback after a mandatory proposal cannot play."""

        del reason
        self._watchdog_deadline = None
        self._allocate_generation()
        try:
            self._player.clear(0, 0.0)
        except Exception:
            health = PlaybackHealth.UNKNOWN
            outcome = ActionOutcome.RENDERER_STATE_UNKNOWN
        else:
            health = PlaybackHealth.DEGRADED
            outcome = ActionOutcome.PLAYBACK_DEGRADED
        self._runner.reset()
        self._active_request = None
        self._state = Track0PlaybackState(None, None, health)
        return outcome

    def handle_completion(
        self,
        event: PlaybackEvent,
        *,
        continuation_request: ActionRequest | None = None,
    ) -> ActionOutcome:
        """Translate a runner directive into at most one next-step play."""

        directive = self._runner.handle_completion(event)
        if directive is None:
            return ActionOutcome.ACCEPTED
        if directive.outcome is not ActionOutcome.ACCEPTED:
            return directive.outcome
        if directive.step is None:
            self._watchdog_deadline = None
            if directive.terminal in {
                SequenceTerminal.COMPLETE,
                SequenceTerminal.IDLE,
            }:
                self._active_request = None
                self._state = Track0PlaybackState(
                    None,
                    None,
                    PlaybackHealth.HEALTHY,
                )
            return ActionOutcome.ACCEPTED
        active_request = continuation_request or self._active_request
        if active_request is None:
            return ActionOutcome.INVALID_SEQUENCE
        return self._play_directive(active_request, directive)

    def _play_directive(
        self,
        request: ActionRequest,
        directive: RunnerDirective,
    ) -> ActionOutcome:
        step = directive.step
        if directive.outcome is not ActionOutcome.ACCEPTED or step is None:
            return ActionOutcome.INVALID_SEQUENCE

        try:
            binding = self._registry.resolve(step.action)
        except KeyError:
            self._runner.reset()
            return ActionOutcome.REGISTRY_MISMATCH

        generation = self._allocate_generation()
        playback_request = PlaybackRequest(
            generation=generation,
            track=binding.track,
            logical_action=step.action,
            physical_name=binding.physical_name,
            loop=step.loop,
            speed=step.speed,
            mix_seconds=step.mix_seconds or 0.0,
        )
        try:
            token = self._player.play(playback_request)
            confirmed_epoch = self._runner.accept_playback(
                generation=generation,
                logical_action=step.action,
                physical_name=binding.physical_name,
                playback_token=token,
            )
        except Exception:
            return self._contain_failed_play()

        self._active_request = request
        self._state = Track0PlaybackState(
            desired_action=step.action,
            confirmed_epoch=confirmed_epoch,
            health=PlaybackHealth.HEALTHY,
        )
        self._arm_after_successful_play(step)
        return ActionOutcome.ACCEPTED

    def _contain_failed_play(self) -> ActionOutcome:
        self._watchdog_deadline = None
        self._allocate_generation()
        try:
            self._player.clear(0, 0.0)
        except Exception:
            health = PlaybackHealth.UNKNOWN
            outcome = ActionOutcome.RENDERER_STATE_UNKNOWN
        else:
            health = PlaybackHealth.DEGRADED
            outcome = ActionOutcome.PLAYBACK_DEGRADED
        self._runner.reset()
        self._active_request = None
        self._state = Track0PlaybackState(None, None, health)
        return outcome

    def poll_watchdog(self) -> ActionOutcome | None:
        """Contain a missing completion/boundary callback at its exact deadline."""

        deadline = self._watchdog_deadline
        if deadline is None or self._clock.now() < deadline:
            return None
        self._watchdog_deadline = None
        self._allocate_generation()
        try:
            self._player.clear(0, 0.0)
        except Exception:
            health = PlaybackHealth.UNKNOWN
        else:
            health = PlaybackHealth.DEGRADED
        self._runner.reset()
        self._active_request = None
        self._state = Track0PlaybackState(None, None, health)
        return ActionOutcome.CALLBACK_TIMEOUT

    def _arm_after_successful_play(self, step: PetActionStep) -> None:
        if step.loop:
            self._watchdog_deadline = None
            return
        self._watchdog_deadline = self._deadline_for_step(step)

    def _arm_current_loop_boundary_watchdog(self) -> None:
        snapshot = self._runner.snapshot
        sequence = snapshot.sequence
        current_index = snapshot.current_index
        if sequence is None or current_index is None:
            self._watchdog_deadline = None
            return
        step = sequence.steps[current_index]
        if not step.loop:
            self._watchdog_deadline = None
            return
        self._watchdog_deadline = self._deadline_for_step(step)

    def _deadline_for_step(self, step: PetActionStep) -> float:
        binding = self._registry.resolve(step.action)
        source_duration = binding.source_duration_seconds
        if source_duration is None:
            raise RuntimeError("preflighted playback is missing duration metadata")
        return self._watchdog_policy.deadline(
            self._clock.now(),
            source_duration,
            step.speed,
        )

    def _allocate_generation(self) -> int:
        self._generation += 1
        return self._generation
