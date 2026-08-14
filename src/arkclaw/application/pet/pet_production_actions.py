"""Content-free production action vocabulary for the desktop pet."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from arkclaw.application.pet.pet_state import (
    PetActivityState,
    PetFacing,
    PetMotionState,
)


class ProductionAction(StrEnum):
    RELAX = "relax"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    SIT = "sit"
    SLEEP = "sleep"
    SPECIAL = "special"
    INTERACT = "interact"


class ActionOrigin(StrEnum):
    SYSTEM = "system"
    EXPLICIT = "explicit"
    AUTONOMOUS = "autonomous"


class ActionSource(StrEnum):
    TRAY = "tray"
    USER = "user"
    AGENT = "agent"
    SCHEDULER = "scheduler"
    MOTION = "motion"
    LIFECYCLE = "lifecycle"


class AutonomousExecutionMode(StrEnum):
    AUTONOMOUS = "autonomous"
    EXPLICIT_HOLD = "explicit_hold"
    SUSPENDED = "suspended"


_SOURCES_BY_ORIGIN = MappingProxyType(
    {
        ActionOrigin.SYSTEM: frozenset({ActionSource.MOTION, ActionSource.LIFECYCLE}),
        ActionOrigin.EXPLICIT: frozenset(
            {ActionSource.TRAY, ActionSource.USER, ActionSource.AGENT}
        ),
        ActionOrigin.AUTONOMOUS: frozenset({ActionSource.SCHEDULER}),
    }
)


def validate_action_authority(origin: ActionOrigin, source: ActionSource) -> None:
    """Reject an origin/source pair that claims incompatible authority."""

    if source not in _SOURCES_BY_ORIGIN[origin]:
        raise ValueError("action origin and source are incompatible")


@dataclass(frozen=True, slots=True)
class ActionIntent:
    action: ProductionAction
    origin: ActionOrigin
    source: ActionSource
    request_token: object

    def __post_init__(self) -> None:
        validate_action_authority(self.origin, self.source)
        if self.request_token is None:
            raise ValueError("request_token must not be None")


@dataclass(frozen=True, slots=True)
class PendingExplicitIntent:
    action: ProductionAction
    source: ActionSource
    request_token: object

    def __post_init__(self) -> None:
        if self.source not in _SOURCES_BY_ORIGIN[ActionOrigin.EXPLICIT]:
            raise ValueError("pending action requires an explicit source")
        if self.request_token is None:
            raise ValueError("request_token must not be None")

    @property
    def intent(self) -> ActionIntent:
        return ActionIntent(
            self.action,
            ActionOrigin.EXPLICIT,
            self.source,
            self.request_token,
        )


@dataclass(frozen=True, slots=True)
class SemanticActionTarget:
    motion: PetMotionState
    activity: PetActivityState
    facing: PetFacing | None = None


_SEMANTIC_TARGETS = MappingProxyType(
    {
        ProductionAction.RELAX: SemanticActionTarget(
            PetMotionState.IDLE,
            PetActivityState.NONE,
        ),
        ProductionAction.MOVE_LEFT: SemanticActionTarget(
            PetMotionState.WALKING_LEFT,
            PetActivityState.NONE,
            PetFacing.LEFT,
        ),
        ProductionAction.MOVE_RIGHT: SemanticActionTarget(
            PetMotionState.WALKING_RIGHT,
            PetActivityState.NONE,
            PetFacing.RIGHT,
        ),
        ProductionAction.SIT: SemanticActionTarget(
            PetMotionState.IDLE,
            PetActivityState.SITTING,
        ),
        ProductionAction.SLEEP: SemanticActionTarget(
            PetMotionState.IDLE,
            PetActivityState.SLEEPING,
        ),
        ProductionAction.SPECIAL: SemanticActionTarget(
            PetMotionState.IDLE,
            PetActivityState.SPECIAL,
        ),
        ProductionAction.INTERACT: SemanticActionTarget(
            PetMotionState.IDLE,
            PetActivityState.INTERACT,
        ),
    }
)


def semantic_target(action: ProductionAction) -> SemanticActionTarget:
    return _SEMANTIC_TARGETS[action]
