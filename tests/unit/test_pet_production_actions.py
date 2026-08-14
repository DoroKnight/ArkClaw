from __future__ import annotations

import pytest

from arkclaw.application.pet.pet_production_actions import (
    ActionIntent,
    ActionOrigin,
    ActionSource,
    AutonomousExecutionMode,
    PendingExplicitIntent,
    ProductionAction,
    semantic_target,
)
from arkclaw.application.pet.pet_state import (
    PetActivityState,
    PetFacing,
    PetMotionState,
)


def test_production_action_catalog_is_exact() -> None:
    assert tuple(ProductionAction) == (
        ProductionAction.RELAX,
        ProductionAction.MOVE_LEFT,
        ProductionAction.MOVE_RIGHT,
        ProductionAction.SIT,
        ProductionAction.SLEEP,
        ProductionAction.SPECIAL,
        ProductionAction.INTERACT,
    )
    assert tuple(AutonomousExecutionMode) == (
        AutonomousExecutionMode.AUTONOMOUS,
        AutonomousExecutionMode.EXPLICIT_HOLD,
        AutonomousExecutionMode.SUSPENDED,
    )


@pytest.mark.parametrize(
    ("action", "motion", "activity", "facing"),
    (
        (ProductionAction.RELAX, PetMotionState.IDLE, PetActivityState.NONE, None),
        (
            ProductionAction.MOVE_LEFT,
            PetMotionState.WALKING_LEFT,
            PetActivityState.NONE,
            PetFacing.LEFT,
        ),
        (
            ProductionAction.MOVE_RIGHT,
            PetMotionState.WALKING_RIGHT,
            PetActivityState.NONE,
            PetFacing.RIGHT,
        ),
        (ProductionAction.SIT, PetMotionState.IDLE, PetActivityState.SITTING, None),
        (ProductionAction.SLEEP, PetMotionState.IDLE, PetActivityState.SLEEPING, None),
        (ProductionAction.SPECIAL, PetMotionState.IDLE, PetActivityState.SPECIAL, None),
        (ProductionAction.INTERACT, PetMotionState.IDLE, PetActivityState.INTERACT, None),
    ),
)
def test_production_action_semantics_are_complete(
    action: ProductionAction,
    motion: PetMotionState,
    activity: PetActivityState,
    facing: PetFacing | None,
) -> None:
    target = semantic_target(action)
    assert target.motion is motion
    assert target.activity is activity
    assert target.facing is facing


@pytest.mark.parametrize(
    ("origin", "source"),
    (
        (ActionOrigin.EXPLICIT, ActionSource.TRAY),
        (ActionOrigin.EXPLICIT, ActionSource.USER),
        (ActionOrigin.EXPLICIT, ActionSource.AGENT),
        (ActionOrigin.AUTONOMOUS, ActionSource.SCHEDULER),
        (ActionOrigin.SYSTEM, ActionSource.MOTION),
        (ActionOrigin.SYSTEM, ActionSource.LIFECYCLE),
    ),
)
def test_action_intent_accepts_only_frozen_origin_source_pairs(
    origin: ActionOrigin,
    source: ActionSource,
) -> None:
    token = object()
    intent = ActionIntent(ProductionAction.RELAX, origin, source, token)
    assert intent.request_token is token


def test_agent_source_cannot_claim_autonomous_origin() -> None:
    with pytest.raises(ValueError, match="origin and source"):
        ActionIntent(
            ProductionAction.RELAX,
            ActionOrigin.AUTONOMOUS,
            ActionSource.AGENT,
            object(),
        )


def test_pending_explicit_intent_rejects_non_explicit_source() -> None:
    with pytest.raises(ValueError, match="explicit source"):
        PendingExplicitIntent(
            ProductionAction.SIT,
            ActionSource.SCHEDULER,
            object(),
        )

