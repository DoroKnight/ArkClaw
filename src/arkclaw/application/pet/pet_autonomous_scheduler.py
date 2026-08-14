"""Pure deterministic scheduler for production desktop-pet actions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from arkclaw.application.pet.pet_production_actions import (
    ActionIntent,
    ActionOrigin,
    ActionSource,
    AutonomousExecutionMode,
    ProductionAction,
)


class RandomSource(Protocol):
    def uniform(self, minimum: float, maximum: float) -> float: ...

    def randrange(
        self,
        start: int,
        stop: int | None = None,
        step: int = 1,
    ) -> int: ...


class AutonomousState(StrEnum):
    RELAX = "relax"
    SIT = "sit"
    SLEEP = "sleep"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    SPECIAL = "special"


_ACTION_BY_STATE: Mapping[AutonomousState, ProductionAction] = MappingProxyType(
    {
        AutonomousState.RELAX: ProductionAction.RELAX,
        AutonomousState.SIT: ProductionAction.SIT,
        AutonomousState.SLEEP: ProductionAction.SLEEP,
        AutonomousState.MOVE_LEFT: ProductionAction.MOVE_LEFT,
        AutonomousState.MOVE_RIGHT: ProductionAction.MOVE_RIGHT,
        AutonomousState.SPECIAL: ProductionAction.SPECIAL,
    }
)
_STATE_BY_ACTION = MappingProxyType(
    {action: state for state, action in _ACTION_BY_STATE.items()}
)

_WEIGHTS: Mapping[AutonomousState, Mapping[AutonomousState, int]] = MappingProxyType(
    {
        AutonomousState.RELAX: MappingProxyType(
            {
                AutonomousState.RELAX: 41,
                AutonomousState.SIT: 20,
                AutonomousState.SLEEP: 10,
                AutonomousState.MOVE_LEFT: 12,
                AutonomousState.MOVE_RIGHT: 12,
                AutonomousState.SPECIAL: 5,
            }
        ),
        AutonomousState.SIT: MappingProxyType(
            {
                AutonomousState.RELAX: 35,
                AutonomousState.SIT: 40,
                AutonomousState.SLEEP: 20,
                AutonomousState.MOVE_LEFT: 2,
                AutonomousState.MOVE_RIGHT: 3,
                AutonomousState.SPECIAL: 0,
            }
        ),
        AutonomousState.SLEEP: MappingProxyType(
            {
                AutonomousState.RELAX: 10,
                AutonomousState.SIT: 15,
                AutonomousState.SLEEP: 75,
                AutonomousState.MOVE_LEFT: 0,
                AutonomousState.MOVE_RIGHT: 0,
                AutonomousState.SPECIAL: 0,
            }
        ),
        AutonomousState.MOVE_LEFT: MappingProxyType(
            {
                AutonomousState.RELAX: 45,
                AutonomousState.SIT: 10,
                AutonomousState.SLEEP: 0,
                AutonomousState.MOVE_LEFT: 25,
                AutonomousState.MOVE_RIGHT: 20,
                AutonomousState.SPECIAL: 0,
            }
        ),
        AutonomousState.MOVE_RIGHT: MappingProxyType(
            {
                AutonomousState.RELAX: 45,
                AutonomousState.SIT: 10,
                AutonomousState.SLEEP: 0,
                AutonomousState.MOVE_LEFT: 20,
                AutonomousState.MOVE_RIGHT: 25,
                AutonomousState.SPECIAL: 0,
            }
        ),
    }
)

_DWELL_RANGES: Mapping[AutonomousState, tuple[float, float]] = MappingProxyType(
    {
        AutonomousState.RELAX: (8.0, 20.0),
        AutonomousState.MOVE_LEFT: (4.0, 10.0),
        AutonomousState.MOVE_RIGHT: (4.0, 10.0),
        AutonomousState.SIT: (15.0, 35.0),
        AutonomousState.SLEEP: (30.0, 90.0),
    }
)


@dataclass(frozen=True, slots=True)
class AutonomousSchedulerState:
    last_committed_state: AutonomousState
    entered_at: float
    eligibility_started_at: float
    dwell_target_seconds: float | None
    playback_generation: int | None
    playback_token: object | None
    last_consumed_boundary_index: int
    proposal_eligible: bool
    consecutive_stays: int


@dataclass(frozen=True, slots=True)
class AutonomousBoundaryEvent:
    generation: int
    playback_token: object
    boundary_index: int
    observed_at: float

    def __post_init__(self) -> None:
        if self.generation < 0 or self.boundary_index <= 0:
            raise ValueError("boundary identity is invalid")
        if not math.isfinite(self.observed_at):
            raise ValueError("boundary time must be finite")


@dataclass(frozen=True, slots=True)
class AutonomousRuntimeSnapshot:
    now: float
    execution_mode: AutonomousExecutionMode
    capabilities: frozenset[ProductionAction]

    def __post_init__(self) -> None:
        if not math.isfinite(self.now):
            raise ValueError("runtime time must be finite")


@dataclass(frozen=True, slots=True)
class AutonomousSchedulerDecision:
    state: AutonomousSchedulerState
    proposed_state: AutonomousState | None = None
    intent: ActionIntent | None = None
    stay: bool = False

    def __post_init__(self) -> None:
        if (self.proposed_state is None) is not (self.intent is None):
            raise ValueError("proposal and intent must be present together")
        if self.stay and self.intent is not None:
            raise ValueError("STAY cannot carry an intent")


class AutonomousActionScheduler:
    """Evaluate immutable state and propose at most one low-authority action."""

    def enter(
        self,
        state: AutonomousState,
        *,
        entered_at: float,
        playback_generation: int | None,
        playback_token: object | None,
        rng: RandomSource,
    ) -> AutonomousSchedulerState:
        if not math.isfinite(entered_at):
            raise ValueError("entry time must be finite")
        if playback_generation is not None and playback_generation < 0:
            raise ValueError("playback generation must be non-negative")
        return AutonomousSchedulerState(
            last_committed_state=state,
            entered_at=entered_at,
            eligibility_started_at=entered_at,
            dwell_target_seconds=self._sample_dwell(state, rng),
            playback_generation=playback_generation,
            playback_token=playback_token,
            last_consumed_boundary_index=0,
            proposal_eligible=False,
            consecutive_stays=0,
        )

    def evaluate(
        self,
        state: AutonomousSchedulerState,
        snapshot: AutonomousRuntimeSnapshot,
        event: AutonomousBoundaryEvent | None,
        rng: RandomSource,
    ) -> AutonomousSchedulerDecision:
        if snapshot.execution_mode is not AutonomousExecutionMode.AUTONOMOUS:
            return AutonomousSchedulerDecision(replace(state, proposal_eligible=False))
        if event is None or not self._matches_new_boundary(state, event):
            return AutonomousSchedulerDecision(state)

        consumed = replace(
            state,
            last_consumed_boundary_index=event.boundary_index,
            proposal_eligible=False,
        )
        dwell = state.dwell_target_seconds
        liveness_due = (
            state.last_committed_state is AutonomousState.RELAX
            and event.observed_at >= state.eligibility_started_at + 60.0
        )
        next_after_two_stays = state.consecutive_stays >= 2
        if (
            dwell is None
            or (
                not liveness_due
                and not next_after_two_stays
                and event.observed_at < state.entered_at + dwell
            )
        ):
            return AutonomousSchedulerDecision(consumed)

        destination = self._select_destination(
            state.last_committed_state,
            snapshot.capabilities,
            rng,
            exclude_stay=next_after_two_stays or liveness_due,
        )
        if destination is None:
            return AutonomousSchedulerDecision(consumed)
        if destination is state.last_committed_state:
            stayed = replace(
                consumed,
                entered_at=event.observed_at,
                dwell_target_seconds=self._sample_dwell(destination, rng),
                consecutive_stays=state.consecutive_stays + 1,
            )
            return AutonomousSchedulerDecision(stayed, stay=True)

        intent = ActionIntent(
            action=_ACTION_BY_STATE[destination],
            origin=ActionOrigin.AUTONOMOUS,
            source=ActionSource.SCHEDULER,
            request_token=object(),
        )
        return AutonomousSchedulerDecision(
            replace(consumed, proposal_eligible=True),
            proposed_state=destination,
            intent=intent,
        )

    def commit_accepted(
        self,
        decision: AutonomousSchedulerDecision,
        *,
        committed_at: float,
        playback_generation: int,
        playback_token: object,
        rng: RandomSource,
    ) -> AutonomousSchedulerState:
        destination = decision.proposed_state
        if destination is None or decision.intent is None:
            raise ValueError("decision has no proposed destination")
        return self.enter(
            destination,
            entered_at=committed_at,
            playback_generation=playback_generation,
            playback_token=playback_token,
            rng=rng,
        )

    def reject(
        self,
        decision: AutonomousSchedulerDecision,
        *,
        rejected_at: float,
        rng: RandomSource,
    ) -> AutonomousSchedulerState:
        if decision.proposed_state is None:
            raise ValueError("decision has no proposed destination")
        if not math.isfinite(rejected_at):
            raise ValueError("rejection time must be finite")
        return replace(
            decision.state,
            entered_at=rejected_at,
            dwell_target_seconds=self._sample_dwell(
                decision.state.last_committed_state,
                rng,
            ),
            proposal_eligible=False,
        )

    @staticmethod
    def _matches_new_boundary(
        state: AutonomousSchedulerState,
        event: AutonomousBoundaryEvent,
    ) -> bool:
        return (
            event.generation == state.playback_generation
            and event.playback_token is state.playback_token
            and event.boundary_index > state.last_consumed_boundary_index
        )

    @staticmethod
    def _sample_dwell(state: AutonomousState, rng: RandomSource) -> float | None:
        dwell_range = _DWELL_RANGES.get(state)
        if dwell_range is None:
            return None
        return rng.uniform(*dwell_range)

    @staticmethod
    def _select_destination(
        current: AutonomousState,
        capabilities: frozenset[ProductionAction],
        rng: RandomSource,
        *,
        exclude_stay: bool = False,
    ) -> AutonomousState | None:
        row = _WEIGHTS.get(current)
        if row is None:
            return None
        available = tuple(
            (destination, weight)
            for destination, weight in row.items()
            if (
                weight > 0
                and _ACTION_BY_STATE[destination] in capabilities
                and (not exclude_stay or destination is not current)
            )
        )
        total = sum(weight for _, weight in available)
        if total <= 0:
            return (
                AutonomousState.RELAX
                if ProductionAction.RELAX in capabilities
                else None
            )
        ticket = rng.randrange(total)
        cumulative = 0
        for destination, weight in available:
            cumulative += weight
            if ticket < cumulative:
                return destination
        raise AssertionError("weighted selection did not resolve")


def autonomous_state_for_action(action: ProductionAction) -> AutonomousState:
    return _STATE_BY_ACTION[action]
