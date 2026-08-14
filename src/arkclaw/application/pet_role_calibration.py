"""Immutable role calibration facts derived before grounding policy."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from arkclaw.application.pet_production_actions import ProductionAction
from arkclaw.application.spine38_runtime import Spine38RootTransform


class RootMotionKind(StrEnum):
    STATIC_ROOT = "static_root"
    CONSTANT_ACTION_OFFSET = "constant_action_offset"
    TIME_VARYING_ROOT_MOTION = "time_varying_root_motion"


@dataclass(frozen=True, slots=True)
class RootMotionClassification:
    root_reference: Spine38RootTransform
    by_action: Mapping[ProductionAction, RootMotionKind]

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_action", MappingProxyType(dict(self.by_action)))


def classify_root_motion_samples(
    samples_by_action: Mapping[ProductionAction, Sequence[Spine38RootTransform]],
    *,
    tolerance: float = 1e-4,
) -> RootMotionClassification:
    """Classify root translation without consulting visible attachment bounds."""

    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("root motion tolerance is invalid")
    relax_samples = tuple(samples_by_action.get(ProductionAction.RELAX, ()))
    if not relax_samples:
        raise ValueError("Relax root reference is required")
    reference = relax_samples[0]
    classified: dict[ProductionAction, RootMotionKind] = {}
    for action, source_samples in samples_by_action.items():
        samples = tuple(source_samples)
        if not samples:
            raise ValueError("root motion samples must not be empty")
        first = samples[0]
        varies = any(not _near(sample, first, tolerance) for sample in samples[1:])
        if varies:
            kind = RootMotionKind.TIME_VARYING_ROOT_MOTION
        elif _near(first, reference, tolerance):
            kind = RootMotionKind.STATIC_ROOT
        else:
            kind = RootMotionKind.CONSTANT_ACTION_OFFSET
        classified[action] = kind
    return RootMotionClassification(reference, classified)


def _near(
    left: Spine38RootTransform,
    right: Spine38RootTransform,
    tolerance: float,
) -> bool:
    return (
        math.isclose(left.x, right.x, abs_tol=tolerance, rel_tol=0.0)
        and math.isclose(left.y, right.y, abs_tol=tolerance, rel_tol=0.0)
    )
