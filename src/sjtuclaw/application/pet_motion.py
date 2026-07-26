"""Deterministic placeholder-pet motion independent of Qt timers."""

from __future__ import annotations

from dataclasses import dataclass

from sjtuclaw.application.pet_geometry import (
    Point,
    Rect,
    Size,
    clamp_window_position,
    select_workspace,
)
from sjtuclaw.application.pet_state import (
    PetState,
    PetStateMachine,
    PetStateTransitionError,
)


@dataclass(frozen=True, slots=True)
class PetMotionConfig:
    gravity: float = 1_800.0
    landing_duration_seconds: float = 0.18

    def __post_init__(self) -> None:
        if self.gravity <= 0 or self.landing_duration_seconds < 0:
            raise ValueError("Pet motion configuration is invalid.")


@dataclass(frozen=True, slots=True)
class PetMotionSnapshot:
    state: PetState
    position: Point
    vertical_velocity: float


class PetMotionModel:
    """Own dragging, falling, landing, pause, and close transitions."""

    def __init__(
        self,
        position: Point,
        window_size: Size,
        config: PetMotionConfig | None = None,
    ) -> None:
        self._position = position
        self._window_size = window_size
        self._config = config or PetMotionConfig()
        self._states = PetStateMachine()
        self._vertical_velocity = 0.0
        self._landing_elapsed = 0.0

    @property
    def state(self) -> PetState:
        return self._states.state

    @property
    def position(self) -> Point:
        return self._position

    @property
    def window_size(self) -> Size:
        return self._window_size

    @property
    def snapshot(self) -> PetMotionSnapshot:
        return PetMotionSnapshot(
            state=self.state,
            position=self._position,
            vertical_velocity=self._vertical_velocity,
        )

    @property
    def accepts_interaction(self) -> bool:
        return self.state not in {PetState.PAUSED, PetState.CLOSING}

    def start_dragging(self) -> None:
        if not self.accepts_interaction:
            raise PetStateTransitionError
        self._states.transition(PetState.DRAGGING)
        self._vertical_velocity = 0.0
        self._landing_elapsed = 0.0

    def drag_to(
        self,
        position: Point,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        if self.state is not PetState.DRAGGING:
            raise PetStateTransitionError
        workspace = select_workspace(position, self._window_size, workspaces)
        self._position = clamp_window_position(
            position,
            self._window_size,
            workspace,
        )
        return self.snapshot

    def release_drag(self) -> None:
        if self.state is not PetState.DRAGGING:
            raise PetStateTransitionError
        self._states.transition(PetState.FALLING)
        self._vertical_velocity = 0.0

    def start_falling(self) -> None:
        self._states.transition(PetState.FALLING)
        self._vertical_velocity = 0.0

    def pause(self) -> None:
        self._states.pause()
        self._vertical_velocity = 0.0

    def resume(self) -> None:
        self._states.resume()

    def begin_closing(self) -> None:
        self._states.begin_closing()
        self._vertical_velocity = 0.0

    def recover_failed_close(self) -> None:
        self._states.recover_failed_close()

    def constrain(self, workspaces: tuple[Rect, ...]) -> PetMotionSnapshot:
        workspace = select_workspace(
            self._position,
            self._window_size,
            workspaces,
        )
        self._position = clamp_window_position(
            self._position,
            self._window_size,
            workspace,
        )
        return self.snapshot

    def update(
        self,
        elapsed_seconds: float,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        if elapsed_seconds < 0:
            raise ValueError("Elapsed time must not be negative.")
        if self.state in {PetState.IDLE, PetState.PAUSED}:
            return self.constrain(workspaces)
        if self.state in {PetState.DRAGGING, PetState.CLOSING}:
            return self.snapshot
        if self.state is PetState.LANDING:
            self._landing_elapsed += elapsed_seconds
            if (
                self._landing_elapsed
                >= self._config.landing_duration_seconds
            ):
                self._states.transition(PetState.IDLE)
                self._landing_elapsed = 0.0
            return self.snapshot

        workspace = select_workspace(
            self._position,
            self._window_size,
            workspaces,
        )
        self._vertical_velocity += self._config.gravity * elapsed_seconds
        candidate = Point(
            self._position.x,
            self._position.y
            + self._vertical_velocity * elapsed_seconds,
        )
        clamped = clamp_window_position(
            candidate,
            self._window_size,
            workspace,
        )
        ground_y = max(
            workspace.y,
            workspace.bottom - self._window_size.height,
        )
        self._position = clamped
        if candidate.y >= ground_y:
            self._position = Point(clamped.x, ground_y)
            self._vertical_velocity = 0.0
            self._landing_elapsed = 0.0
            self._states.transition(PetState.LANDING)
        return self.snapshot
