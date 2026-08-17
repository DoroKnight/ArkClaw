"""Qt-free Resume Autonomous capability (Stage 9 / Slice 5A-P prerequisite).

Authority: 08 14.1 "without duplicating command semantics"; 06 9.2/9.3
"Resume Autonomous (if valid)"; 07 19 (existing method / active-state
proof).  These tests characterise the single authoritative Qt-free validity
predicate and prove the descriptor projection consumes the same function
object, so no second implementation of the Resume validity rule exists.
"""

from __future__ import annotations

from arkclaw.application.pet.pet_production_actions import (
    ProductionAction,
    can_resume_autonomous,
)


def test_can_resume_autonomous_is_false_while_closing() -> None:
    assert (
        can_resume_autonomous(
            closing=True,
            available_actions=frozenset({ProductionAction.RELAX}),
        )
        is False
    )


def test_can_resume_autonomous_is_false_when_relax_unavailable() -> None:
    assert (
        can_resume_autonomous(
            closing=False,
            available_actions=frozenset(),
        )
        is False
    )


def test_can_resume_autonomous_is_true_when_not_closing_and_relax_available() -> None:
    assert (
        can_resume_autonomous(
            closing=False,
            available_actions=frozenset({ProductionAction.RELAX}),
        )
        is True
    )


def test_can_resume_autonomous_ignores_unrelated_action_availability() -> None:
    assert (
        can_resume_autonomous(
            closing=False,
            available_actions=frozenset(
                {ProductionAction.SIT, ProductionAction.SLEEP}
            ),
        )
        is False
    )
    assert (
        can_resume_autonomous(
            closing=False,
            available_actions=frozenset(
                {ProductionAction.RELAX, ProductionAction.SPECIAL}
            ),
        )
        is True
    )


def test_resume_validity_has_exactly_one_production_implementation() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        resume_autonomous_available,
    )

    # The adapter name must be a direct alias of the authoritative Qt-free
    # capability, never a second function body with its own boolean rule.
    assert resume_autonomous_available is can_resume_autonomous