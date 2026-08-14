from __future__ import annotations

from arkclaw.application.pet_production_actions import ProductionAction
from arkclaw.application.pet_role_calibration import (
    RootMotionKind,
    classify_root_motion_samples,
)
from arkclaw.application.spine38_runtime import Spine38RootTransform


def test_relax_move_sit_root_motion_is_classified_before_grounding_policy() -> None:
    samples = {
        ProductionAction.RELAX: (
            Spine38RootTransform(0.0, 0.0),
            Spine38RootTransform(0.0, 0.0),
        ),
        ProductionAction.MOVE_LEFT: (
            Spine38RootTransform(0.0, 0.0),
            Spine38RootTransform(1.0, 0.0),
        ),
        ProductionAction.SIT: (
            Spine38RootTransform(0.0, -2.0),
            Spine38RootTransform(0.0, -2.0),
        ),
    }

    result = classify_root_motion_samples(samples)

    assert result.root_reference == Spine38RootTransform(0.0, 0.0)
    assert result.by_action[ProductionAction.RELAX] is RootMotionKind.STATIC_ROOT
    assert (
        result.by_action[ProductionAction.MOVE_LEFT]
        is RootMotionKind.TIME_VARYING_ROOT_MOTION
    )
    assert (
        result.by_action[ProductionAction.SIT]
        is RootMotionKind.CONSTANT_ACTION_OFFSET
    )

