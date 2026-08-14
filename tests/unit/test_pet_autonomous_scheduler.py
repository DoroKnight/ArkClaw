from __future__ import annotations

import random
from dataclasses import replace

from arkclaw.application.pet.pet_autonomous_scheduler import (
    AutonomousActionScheduler,
    AutonomousBoundaryEvent,
    AutonomousRuntimeSnapshot,
    AutonomousState,
)
from arkclaw.application.pet.pet_production_actions import (
    ActionOrigin,
    ActionSource,
    AutonomousExecutionMode,
    ProductionAction,
)


class _ScriptedRandom:
    def __init__(
        self,
        *,
        uniform_values: list[float] | None = None,
        range_values: list[int] | None = None,
    ) -> None:
        self.uniform_values = list(uniform_values or [])
        self.range_values = list(range_values or [])
        self.uniform_calls = 0
        self.randrange_calls = 0
        self.randrange_starts: list[int] = []

    def uniform(self, minimum: float, maximum: float) -> float:
        self.uniform_calls += 1
        value = self.uniform_values.pop(0)
        assert minimum <= value <= maximum
        return value

    def randrange(
        self,
        start: int,
        stop: int | None = None,
        step: int = 1,
    ) -> int:
        self.randrange_calls += 1
        self.randrange_starts.append(start)
        assert stop is None
        assert step == 1
        value = self.range_values.pop(0)
        assert 0 <= value < start
        return value


def _snapshot(now: float) -> AutonomousRuntimeSnapshot:
    return AutonomousRuntimeSnapshot(
        now=now,
        execution_mode=AutonomousExecutionMode.AUTONOMOUS,
        capabilities=frozenset(ProductionAction),
    )


def _event(token: object, index: int, observed_at: float) -> AutonomousBoundaryEvent:
    return AutonomousBoundaryEvent(
        generation=37,
        playback_token=token,
        boundary_index=index,
        observed_at=observed_at,
    )


def test_seeded_transition_history_is_reproducible_and_live() -> None:
    history = _seeded_history(7)

    assert history == _seeded_history(7)
    assert any(state is not AutonomousState.RELAX for state in history[:3])


def test_distinct_seed_produces_a_distinct_deterministic_history() -> None:
    assert _seeded_history(7) != _seeded_history(19)


def test_relax_move_weight_is_slightly_increased_to_twenty_four_percent() -> None:
    scheduler = AutonomousActionScheduler()
    move_count = 0
    for ticket in range(100):
        token = object()
        rng = _ScriptedRandom(uniform_values=[8.0, 8.0], range_values=[ticket])
        state = scheduler.enter(
            AutonomousState.RELAX,
            entered_at=0.0,
            playback_generation=37,
            playback_token=token,
            rng=rng,
        )
        decision = scheduler.evaluate(
            state,
            _snapshot(8.0),
            _event(token, 1, 8.0),
            rng,
        )
        if decision.proposed_state in {
            AutonomousState.MOVE_LEFT,
            AutonomousState.MOVE_RIGHT,
        }:
            move_count += 1

    assert move_count == 24


def test_duplicate_loop_boundary_is_side_effect_free() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(uniform_values=[8.0])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )
    consumed = scheduler.evaluate(state, _snapshot(1.0), _event(token, 1, 1.0), rng)
    calls = (rng.uniform_calls, rng.randrange_calls)

    duplicate = scheduler.evaluate(
        consumed.state,
        _snapshot(100.0),
        _event(token, 1, 1.0),
        rng,
    )

    assert duplicate.state == consumed.state
    assert duplicate.intent is None
    assert not duplicate.stay
    assert (rng.uniform_calls, rng.randrange_calls) == calls


def test_stay_consumes_boundary_once_without_restarting_playback() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(uniform_values=[8.0, 12.0], range_values=[0])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )

    stay = scheduler.evaluate(state, _snapshot(8.0), _event(token, 1, 8.0), rng)
    duplicate = scheduler.evaluate(
        stay.state,
        _snapshot(30.0),
        _event(token, 1, 8.0),
        rng,
    )

    assert stay.stay
    assert stay.intent is None
    assert stay.state.last_committed_state is AutonomousState.RELAX
    assert stay.state.last_consumed_boundary_index == 1
    assert stay.state.dwell_target_seconds == 12.0
    assert stay.state.playback_generation == 37
    assert stay.state.playback_token is token
    assert duplicate.state == stay.state
    assert rng.uniform_calls == 2
    assert rng.randrange_calls == 1


def test_new_loop_boundary_with_same_generation_and_token_is_valid() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(uniform_values=[8.0, 8.0], range_values=[0, 50])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )
    stayed = scheduler.evaluate(state, _snapshot(8.0), _event(token, 1, 8.0), rng)

    proposed = scheduler.evaluate(
        stayed.state,
        _snapshot(16.0),
        _event(token, 2, 16.0),
        rng,
    )

    assert proposed.proposed_state is AutonomousState.SIT
    assert proposed.intent is not None
    assert proposed.intent.action is ProductionAction.SIT
    assert proposed.intent.origin is ActionOrigin.AUTONOMOUS
    assert proposed.intent.source is ActionSource.SCHEDULER
    assert proposed.state.last_committed_state is AutonomousState.RELAX
    assert proposed.state.last_consumed_boundary_index == 2


def test_two_eligible_stays_exclude_stay_from_the_next_candidate_set() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(
        uniform_values=[8.0, 8.0, 8.0, 8.0],
        range_values=[0, 0, 0],
    )
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )

    first = scheduler.evaluate(state, _snapshot(8.0), _event(token, 1, 8.0), rng)
    second = scheduler.evaluate(
        first.state,
        _snapshot(16.0),
        _event(token, 2, 16.0),
        rng,
    )
    third = scheduler.evaluate(
        second.state,
        _snapshot(24.0),
        _event(token, 3, 24.0),
        rng,
    )

    assert first.stay
    assert second.stay
    assert third.intent is not None
    assert third.intent.action is ProductionAction.SIT
    assert third.proposed_state is AutonomousState.SIT
    assert rng.randrange_starts == [100, 100, 59]


def test_old_boundary_cannot_trigger_after_new_dwell_deadline() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(uniform_values=[10.0], range_values=[50])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )
    early = scheduler.evaluate(state, _snapshot(5.0), _event(token, 1, 5.0), rng)

    replayed = scheduler.evaluate(
        early.state,
        _snapshot(10.0),
        _event(token, 1, 5.0),
        rng,
    )

    assert early.state.last_consumed_boundary_index == 1
    assert replayed.intent is None
    assert rng.randrange_calls == 0


def test_rejected_proposal_keeps_source_and_consumes_no_destination_dwell() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(uniform_values=[8.0, 12.0], range_values=[50])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )
    proposal = scheduler.evaluate(state, _snapshot(8.0), _event(token, 1, 8.0), rng)

    rejected = scheduler.reject(proposal, rejected_at=9.0, rng=rng)

    assert rejected.last_committed_state is AutonomousState.RELAX
    assert rejected.last_consumed_boundary_index == 1
    assert rejected.entered_at == 9.0
    assert rejected.dwell_target_seconds == 12.0
    assert not rejected.proposal_eligible
    assert rng.uniform_calls == 2


def test_commit_samples_destination_dwell_only_after_acceptance() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    next_token = object()
    rng = _ScriptedRandom(uniform_values=[8.0, 15.0], range_values=[50])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )
    proposal = scheduler.evaluate(state, _snapshot(8.0), _event(token, 1, 8.0), rng)
    assert rng.uniform_calls == 1

    committed = scheduler.commit_accepted(
        proposal,
        committed_at=8.0,
        playback_generation=38,
        playback_token=next_token,
        rng=rng,
    )

    assert committed.last_committed_state is AutonomousState.SIT
    assert committed.entered_at == 8.0
    assert committed.dwell_target_seconds == 15.0
    assert committed.playback_generation == 38
    assert committed.playback_token is next_token
    assert committed.last_consumed_boundary_index == 0


def test_mismatched_playback_epoch_is_ignored() -> None:
    scheduler = AutonomousActionScheduler()
    token = object()
    rng = _ScriptedRandom(uniform_values=[8.0])
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=37,
        playback_token=token,
        rng=rng,
    )

    decision = scheduler.evaluate(
        state,
        _snapshot(100.0),
        replace(_event(object(), 1, 100.0), generation=38),
        rng,
    )

    assert decision.state == state
    assert decision.intent is None


def _seeded_history(seed: int) -> tuple[AutonomousState, ...]:
    scheduler = AutonomousActionScheduler()
    rng = random.Random(seed)
    token = object()
    state = scheduler.enter(
        AutonomousState.RELAX,
        entered_at=0.0,
        playback_generation=1,
        playback_token=token,
        rng=rng,
    )
    history: list[AutonomousState] = []
    for boundary_index in range(1, 6):
        observed_at = float(boundary_index * 100)
        decision = scheduler.evaluate(
            state,
            AutonomousRuntimeSnapshot(
                now=observed_at,
                execution_mode=AutonomousExecutionMode.AUTONOMOUS,
                capabilities=frozenset(ProductionAction) - {ProductionAction.SPECIAL},
            ),
            AutonomousBoundaryEvent(
                generation=state.playback_generation or 0,
                playback_token=state.playback_token,
                boundary_index=boundary_index if state.playback_generation == 1 else 1,
                observed_at=observed_at,
            ),
            rng,
        )
        if decision.proposed_state is None:
            state = decision.state
        else:
            token = object()
            state = scheduler.commit_accepted(
                decision,
                committed_at=observed_at,
                playback_generation=boundary_index + 1,
                playback_token=token,
                rng=rng,
            )
        history.append(state.last_committed_state)
    return tuple(history)
