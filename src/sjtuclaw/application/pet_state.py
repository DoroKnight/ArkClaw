"""Framework-independent lifecycle state machine for the placeholder pet."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PetState(Enum):
    """Stable states exposed by the minimal desktop-pet model."""

    IDLE = "idle"
    DRAGGING = "dragging"
    FALLING = "falling"
    LANDING = "landing"
    PAUSED = "paused"
    CLOSING = "closing"


@dataclass(frozen=True, slots=True)
class PetStateSpec:
    """Document a state's priority and lifecycle contract."""

    priority: int
    interruptible: bool
    entry_condition: str
    exit_condition: str


PET_STATE_SPECS: dict[PetState, PetStateSpec] = {
    PetState.IDLE: PetStateSpec(
        priority=0,
        interruptible=True,
        entry_condition="landing completed or a failed close was recovered",
        exit_condition="drag, fall, pause, or close begins",
    ),
    PetState.FALLING: PetStateSpec(
        priority=40,
        interruptible=True,
        entry_condition="drag was released or falling was explicitly started",
        exit_condition="ground contact, drag, pause, or close",
    ),
    PetState.LANDING: PetStateSpec(
        priority=50,
        interruptible=True,
        entry_condition="falling reached the selected workspace floor",
        exit_condition="landing interval completes, drag, pause, or close",
    ),
    PetState.PAUSED: PetStateSpec(
        priority=70,
        interruptible=True,
        entry_condition="the user explicitly pauses the pet",
        exit_condition="the user resumes or application close begins",
    ),
    PetState.DRAGGING: PetStateSpec(
        priority=80,
        interruptible=True,
        entry_condition="the user presses and holds the primary mouse button",
        exit_condition="the button is released, pause begins, or close begins",
    ),
    PetState.CLOSING: PetStateSpec(
        priority=100,
        interruptible=False,
        entry_condition="safe runtime shutdown has been requested",
        exit_condition="the window closes or shutdown fails and is recovered",
    ),
}

_ALLOWED_TRANSITIONS: dict[PetState, frozenset[PetState]] = {
    PetState.IDLE: frozenset(
        {
            PetState.DRAGGING,
            PetState.FALLING,
            PetState.PAUSED,
            PetState.CLOSING,
        }
    ),
    PetState.DRAGGING: frozenset(
        {PetState.FALLING, PetState.PAUSED, PetState.CLOSING}
    ),
    PetState.FALLING: frozenset(
        {
            PetState.DRAGGING,
            PetState.LANDING,
            PetState.PAUSED,
            PetState.CLOSING,
        }
    ),
    PetState.LANDING: frozenset(
        {
            PetState.IDLE,
            PetState.DRAGGING,
            PetState.PAUSED,
            PetState.CLOSING,
        }
    ),
    PetState.PAUSED: frozenset(
        {
            PetState.IDLE,
            PetState.FALLING,
            PetState.LANDING,
            PetState.CLOSING,
        }
    ),
    # This single rollback is reserved for a reported safe-shutdown failure.
    PetState.CLOSING: frozenset({PetState.PAUSED}),
}


class PetStateTransitionError(RuntimeError):
    """Report an invalid transition without carrying GUI or runtime data."""

    def __init__(self) -> None:
        super().__init__("The desktop-pet state transition is not permitted.")


class PetStateMachine:
    """Enforce explicit state transitions independently of Qt."""

    def __init__(self) -> None:
        self._state = PetState.IDLE
        self._resume_state = PetState.IDLE

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def spec(self) -> PetStateSpec:
        return PET_STATE_SPECS[self._state]

    def can_transition(self, target: PetState) -> bool:
        return target is self._state or target in _ALLOWED_TRANSITIONS[self._state]

    def transition(self, target: PetState) -> None:
        if target is self._state:
            return
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            raise PetStateTransitionError
        self._state = target

    def pause(self) -> None:
        if self._state is PetState.PAUSED:
            return
        if self._state is PetState.CLOSING:
            raise PetStateTransitionError
        self._resume_state = (
            PetState.IDLE
            if self._state is PetState.DRAGGING
            else self._state
        )
        self.transition(PetState.PAUSED)

    def resume(self) -> None:
        if self._state is not PetState.PAUSED:
            raise PetStateTransitionError
        target = self._resume_state
        if target not in _ALLOWED_TRANSITIONS[PetState.PAUSED]:
            target = PetState.IDLE
        self.transition(target)

    def begin_closing(self) -> None:
        self.transition(PetState.CLOSING)

    def recover_failed_close(self) -> None:
        if self._state is not PetState.CLOSING:
            raise PetStateTransitionError
        self._resume_state = PetState.IDLE
        self.transition(PetState.PAUSED)
