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
    PetFacing,
    PetLayeredState,
    PetLayeredStateMachine,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
    ProposedStateTransition,
)


@dataclass(frozen=True, slots=True)
class PetMotionConfig:
    gravity: float = 1_800.0
    landing_duration_seconds: float = 0.18
    walking_stride_pixels: float = 24.0
    walking_cycle_seconds: float = 0.8

    def __post_init__(self) -> None:
        if (
            self.gravity <= 0
            or self.landing_duration_seconds < 0
            or self.walking_stride_pixels <= 0
            or self.walking_cycle_seconds <= 0
        ):
            raise ValueError("Pet motion configuration is invalid.")

    @property
    def walking_speed(self) -> float:
        return self.walking_stride_pixels / self.walking_cycle_seconds


@dataclass(frozen=True, slots=True)
class PetMotionSnapshot:
    state: PetLayeredState
    position: Point
    vertical_velocity: float


class PetMotionModel:
    """Own dragging, falling, landing, pause, and close transitions."""

    def __init__(
        self,
        position: Point,
        window_size: Size,
        config: PetMotionConfig | None = None,
        *,
        states: PetLayeredStateMachine | None = None,
    ) -> None:
        self._position = position
        self._window_size = window_size
        self._config = config or PetMotionConfig()
        self._states = states or PetLayeredStateMachine()
        self._vertical_velocity = 0.0
        self._landing_elapsed = 0.0

    @property
    def state(self) -> PetLayeredState:
        return self._states.snapshot

    @property
    def states(self) -> PetLayeredStateMachine:
        return self._states

    def commit_state_transition(
        self,
        proposal: ProposedStateTransition,
    ) -> None:
        """Commit state authority output and synchronize motion-local facts."""

        self._states.commit(proposal)
        target = proposal.target_state
        if (
            target.lifecycle is not PetLifecycleState.ACTIVE
            or target.motion in {PetMotionState.DRAGGING, PetMotionState.FALLING}
        ):
            self._vertical_velocity = 0.0
            self._landing_elapsed = 0.0

    @property
    def position(self) -> Point:
        return self._position

    @property
    def window_size(self) -> Size:
        return self._window_size

    @property
    def config(self) -> PetMotionConfig:
        return self._config

    @property
    def snapshot(self) -> PetMotionSnapshot:
        return PetMotionSnapshot(
            state=self.state,
            position=self._position,
            vertical_velocity=self._vertical_velocity,
        )

    @property
    def accepts_interaction(self) -> bool:
        return self.state.lifecycle is not PetLifecycleState.CLOSING

    def start_dragging(self) -> None:
        if not self.accepts_interaction:
            raise PetStateTransitionError
        self._states.start_dragging()
        self._vertical_velocity = 0.0
        self._landing_elapsed = 0.0

    def drag_to(
        self,
        position: Point,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        if self.state.motion is not PetMotionState.DRAGGING:
            raise PetStateTransitionError
        workspace = select_workspace(position, self._window_size, workspaces)
        self._position = clamp_window_position(
            position,
            self._window_size,
            workspace,
        )
        return self.snapshot

    def release_drag(self) -> None:
        self._states.release_drag()
        self._vertical_velocity = 0.0

    def start_falling(self) -> None:
        self._states.start_falling()
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

    def start_walking(self, direction: PetFacing) -> None:
        self._states.start_walking(direction)

    def stop_walking(self) -> None:
        self._states.stop_walking()

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

    def restore_position(
        self,
        position: Point,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        """Restore and constrain a persisted position without changing state."""

        workspace = select_workspace(
            position,
            self._window_size,
            workspaces,
        )
        self._position = clamp_window_position(
            position,
            self._window_size,
            workspace,
        )
        self._vertical_velocity = 0.0
        self._landing_elapsed = 0.0
        return self.snapshot

    def update(
        self,
        elapsed_seconds: float,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        if elapsed_seconds < 0:
            raise ValueError("Elapsed time must not be negative.")
        state = self.state
        if state.lifecycle is not PetLifecycleState.ACTIVE:
            return self.constrain(workspaces)
        if state.motion is PetMotionState.IDLE:
            return self.constrain(workspaces)
        if state.motion is PetMotionState.DRAGGING:
            return self.snapshot
        if state.motion in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            return self._update_walking(elapsed_seconds, workspaces)
        if state.motion is PetMotionState.LANDING:
            self._landing_elapsed += elapsed_seconds
            if (
                self._landing_elapsed
                >= self._config.landing_duration_seconds
            ):
                self._states.finish_landing()
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
            self._states.land()
        return self.snapshot

    def _update_walking(
        self,
        elapsed_seconds: float,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        workspace = select_workspace(
            self._position,
            self._window_size,
            workspaces,
        )
        moving_left = self.state.motion is PetMotionState.WALKING_LEFT
        direction = -1.0 if moving_left else 1.0
        candidate = Point(
            self._position.x
            + direction * self._config.walking_speed * elapsed_seconds,
            self._position.y,
        )
        clamped = clamp_window_position(
            candidate,
            self._window_size,
            workspace,
        )
        self._position = clamped
        if clamped.x != candidate.x:
            self._states.start_walking(
                PetFacing.RIGHT if moving_left else PetFacing.LEFT
            )
        return self.snapshot
