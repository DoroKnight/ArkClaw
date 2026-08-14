from __future__ import annotations

from dataclasses import dataclass

import pytest

from arkclaw.application.pet.pet_action_sequence import (
    SEQUENCE_CATALOG,
    InterruptClass,
    PlaybackHealth,
    SequenceName,
)
from arkclaw.application.pet.pet_production_actions import ActionOrigin, ActionSource
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    ActionRequest,
    ArbitrationContext,
    ArbitrationDecision,
    CancellationMode,
    PetActionArbiter,
)


def _request(
    sequence: SequenceName,
    *,
    request_token: object | None = None,
    semantic_epoch: int = 1,
    input_session_token: object | None = None,
    interruption_class: InterruptClass | None = None,
    protected: bool | None = None,
    origin: ActionOrigin = ActionOrigin.SYSTEM,
    source: ActionSource = ActionSource.LIFECYCLE,
) -> ActionRequest:
    entry = SEQUENCE_CATALOG[sequence]
    return ActionRequest(
        sequence_name=sequence,
        interruption_class=(
            entry.interruption_class if interruption_class is None else interruption_class
        ),
        protected=entry.protected if protected is None else protected,
        request_token=object() if request_token is None else request_token,
        semantic_epoch=semantic_epoch,
        input_session_token=input_session_token,
        origin=origin,
        source=source,
    )


def _context(**changes: object) -> ArbitrationContext:
    values: dict[str, object] = {
        "incoming_mode": CancellationMode.REPLACE,
        "runner_authorized_continuation": False,
        "playback_health": PlaybackHealth.HEALTHY,
        "confirmed_semantic_epoch": 1,
        "active_action_compatible": True,
    }
    values.update(changes)
    return ArbitrationContext(**values)  # type: ignore[arg-type]


def test_drag_release_replaces_hold_in_same_input_session() -> None:
    session = object()
    decision = PetActionArbiter().decide(
        _request(SequenceName.DRAG_RELEASE, input_session_token=session),
        _request(SequenceName.DRAG_HOLD, input_session_token=session),
        _context(),
    )

    assert decision == ArbitrationDecision(
        ActionOutcome.ACCEPTED,
        CancellationMode.REPLACE,
    )


def test_new_drag_session_replaces_previous_release() -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.DRAG_HOLD, input_session_token=object()),
        _request(SequenceName.DRAG_RELEASE, input_session_token=object()),
        _context(),
    )

    assert decision.mode is CancellationMode.REPLACE


def test_motion_safety_outranks_user_interaction() -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.FALL_RECOVERY),
        _request(SequenceName.DRAG_HOLD, input_session_token=object()),
        _context(),
    )

    assert decision.mode is CancellationMode.REPLACE


def test_no_active_request_is_accepted_without_a_cancellation_directive() -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.WAVE),
        None,
        _context(),
    )

    assert decision == ArbitrationDecision(ActionOutcome.ACCEPTED, None)


@pytest.mark.parametrize("active_class", tuple(InterruptClass))
def test_system_shutdown_always_wins(active_class: InterruptClass) -> None:
    decision = PetActionArbiter().decide(
        _request(
            SequenceName.IDLE,
            interruption_class=InterruptClass.SYSTEM_SHUTDOWN,
        ),
        _request(
            SequenceName.IDLE,
            interruption_class=active_class,
            protected=active_class is InterruptClass.STRICT_ACTION,
            input_session_token=(
                object() if active_class is InterruptClass.USER_INTERACTION else None
            ),
        ),
        _context(),
    )

    expected_mode = (
        None if active_class is InterruptClass.SYSTEM_SHUTDOWN else CancellationMode.IMMEDIATE_CLEAR
    )
    assert decision == ArbitrationDecision(ActionOutcome.ACCEPTED, expected_mode)


@dataclass(frozen=True, slots=True)
class RankCase:
    incoming: InterruptClass
    active: InterruptClass
    outcome: ActionOutcome
    mode: CancellationMode | None


_UNEQUAL_RANK_CASES = tuple(
    RankCase(
        incoming=incoming,
        active=active,
        outcome=(ActionOutcome.ACCEPTED if incoming > active else ActionOutcome.REJECTED_PRIORITY),
        mode=(CancellationMode.REPLACE if incoming > active else None),
    )
    for incoming in InterruptClass
    for active in InterruptClass
    if incoming is not active and incoming is not InterruptClass.SYSTEM_SHUTDOWN
)


@pytest.mark.parametrize("case", _UNEQUAL_RANK_CASES)
def test_every_unequal_rank_pair_has_a_literal_result(case: RankCase) -> None:
    incoming_session = object() if case.incoming is InterruptClass.USER_INTERACTION else None
    active_session = object() if case.active is InterruptClass.USER_INTERACTION else None
    decision = PetActionArbiter().decide(
        _request(
            SequenceName.IDLE,
            interruption_class=case.incoming,
            protected=case.incoming is InterruptClass.STRICT_ACTION,
            input_session_token=incoming_session,
        ),
        _request(
            SequenceName.IDLE,
            interruption_class=case.active,
            protected=case.active is InterruptClass.STRICT_ACTION,
            input_session_token=active_session,
        ),
        _context(),
    )

    assert decision == ArbitrationDecision(case.outcome, case.mode)


def test_runner_authorized_continuation_is_accepted_without_replacement() -> None:
    active = _request(SequenceName.SLEEP, request_token=object())
    incoming = _request(SequenceName.SLEEP, request_token=object())

    decision = PetActionArbiter().decide(
        incoming,
        active,
        _context(runner_authorized_continuation=True),
    )

    assert decision == ArbitrationDecision(ActionOutcome.ACCEPTED, None)


def test_same_sequence_and_request_token_is_duplicate() -> None:
    token = object()
    active = _request(SequenceName.READ, request_token=token)
    incoming = _request(SequenceName.READ, request_token=token)

    decision = PetActionArbiter().decide(incoming, active, _context())

    assert decision == ArbitrationDecision(ActionOutcome.REJECTED_DUPLICATE, None)


@pytest.mark.parametrize(
    ("context", "incoming_epoch", "expected"),
    [
        (_context(), 1, ActionOutcome.REJECTED_DUPLICATE),
        (_context(), 2, ActionOutcome.ACCEPTED),
        (
            _context(playback_health=PlaybackHealth.DEGRADED),
            1,
            ActionOutcome.ACCEPTED,
        ),
        (
            _context(active_action_compatible=False),
            1,
            ActionOutcome.ACCEPTED,
        ),
        (
            _context(confirmed_semantic_epoch=99),
            1,
            ActionOutcome.ACCEPTED,
        ),
    ],
)
def test_equal_motion_safety_replaces_only_stale_or_new_epoch_requests(
    context: ArbitrationContext,
    incoming_epoch: int,
    expected: ActionOutcome,
) -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.LANDING, semantic_epoch=incoming_epoch),
        _request(SequenceName.FALL_RECOVERY, semantic_epoch=1),
        context,
    )

    expected_mode = CancellationMode.REPLACE if expected is ActionOutcome.ACCEPTED else None
    assert decision == ArbitrationDecision(expected, expected_mode)


def test_equal_user_interaction_same_session_same_sequence_is_duplicate() -> None:
    session = object()
    decision = PetActionArbiter().decide(
        _request(SequenceName.DRAG_HOLD, input_session_token=session),
        _request(SequenceName.DRAG_HOLD, input_session_token=session),
        _context(),
    )

    assert decision.outcome is ActionOutcome.REJECTED_DUPLICATE


def test_reverse_drag_phase_in_same_session_is_rejected() -> None:
    session = object()
    decision = PetActionArbiter().decide(
        _request(SequenceName.DRAG_HOLD, input_session_token=session),
        _request(SequenceName.DRAG_RELEASE, input_session_token=session),
        _context(),
    )

    assert decision == ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)


def test_equal_strict_action_rejects_a_different_strict_action() -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.HAPPY),
        _request(SequenceName.WAVE),
        _context(),
    )

    assert decision == ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)


@pytest.mark.parametrize(
    ("protected", "expected"),
    [
        (False, ArbitrationDecision(ActionOutcome.ACCEPTED, CancellationMode.REPLACE)),
        (True, ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)),
    ],
)
def test_equal_normal_action_replacement_respects_active_protection(
    protected: bool,
    expected: ArbitrationDecision,
) -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.TYPE),
        _request(SequenceName.READ, protected=protected),
        _context(),
    )

    assert decision == expected


@pytest.mark.parametrize("incoming_origin", tuple(ActionOrigin))
@pytest.mark.parametrize("active_origin", tuple(ActionOrigin))
def test_normal_action_origin_tie_break_matrix(
    incoming_origin: ActionOrigin,
    active_origin: ActionOrigin,
) -> None:
    source_by_origin = {
        ActionOrigin.SYSTEM: ActionSource.LIFECYCLE,
        ActionOrigin.EXPLICIT: ActionSource.USER,
        ActionOrigin.AUTONOMOUS: ActionSource.SCHEDULER,
    }
    decision = PetActionArbiter().decide(
        _request(
            SequenceName.TYPE,
            origin=incoming_origin,
            source=source_by_origin[incoming_origin],
        ),
        _request(
            SequenceName.READ,
            origin=active_origin,
            source=source_by_origin[active_origin],
        ),
        _context(),
    )

    expected = (
        ArbitrationDecision(ActionOutcome.REJECTED_PRIORITY, None)
        if incoming_origin is ActionOrigin.AUTONOMOUS
        and active_origin is ActionOrigin.EXPLICIT
        else ArbitrationDecision(ActionOutcome.ACCEPTED, CancellationMode.REPLACE)
    )
    assert decision == expected


@pytest.mark.parametrize(
    "source",
    (ActionSource.TRAY, ActionSource.USER, ActionSource.AGENT),
)
def test_explicit_source_does_not_change_normal_action_priority(
    source: ActionSource,
) -> None:
    decision = PetActionArbiter().decide(
        _request(
            SequenceName.TYPE,
            origin=ActionOrigin.EXPLICIT,
            source=source,
        ),
        _request(
            SequenceName.READ,
            origin=ActionOrigin.AUTONOMOUS,
            source=ActionSource.SCHEDULER,
        ),
        _context(),
    )

    assert decision == ArbitrationDecision(
        ActionOutcome.ACCEPTED,
        CancellationMode.REPLACE,
    )


def test_explicit_same_normal_action_outranks_autonomous_request() -> None:
    decision = PetActionArbiter().decide(
        _request(
            SequenceName.READ,
            origin=ActionOrigin.EXPLICIT,
            source=ActionSource.USER,
        ),
        _request(
            SequenceName.READ,
            origin=ActionOrigin.AUTONOMOUS,
            source=ActionSource.SCHEDULER,
        ),
        _context(),
    )

    assert decision == ArbitrationDecision(
        ActionOutcome.ACCEPTED,
        CancellationMode.REPLACE,
    )


def test_equal_idle_is_always_duplicate() -> None:
    decision = PetActionArbiter().decide(
        _request(SequenceName.IDLE),
        _request(SequenceName.IDLE),
        _context(),
    )

    assert decision == ArbitrationDecision(ActionOutcome.REJECTED_DUPLICATE, None)


def test_unprotected_strict_request_is_invalid() -> None:
    with pytest.raises(ValueError):
        _request(SequenceName.WAVE, protected=False)
