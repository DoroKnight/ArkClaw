"""Deterministic placeholder-pet motion independent of Qt timers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from arkclaw.application.pet.pet_geometry import (
    Point,
    Rect,
    Size,
    clamp_drag_position,
    clamp_window_position,
    select_workspace,
)
from arkclaw.application.pet.pet_state import (
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
    horizontal_velocity: float


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
        self._horizontal_velocity = 0.0
        self._landing_elapsed = 0.0
        self._pending_direction_turn: PetFacing | None = None

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
        if target.motion is PetMotionState.WALKING_LEFT:
            self._horizontal_velocity = -self._config.walking_speed
        elif target.motion is PetMotionState.WALKING_RIGHT:
            self._horizontal_velocity = self._config.walking_speed
        else:
            self._horizontal_velocity = 0.0
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
            horizontal_velocity=self._horizontal_velocity,
        )

    @property
    def accepts_interaction(self) -> bool:
        return self.state.lifecycle is not PetLifecycleState.CLOSING

    def start_dragging(self) -> None:
        if not self.accepts_interaction:
            raise PetStateTransitionError
        self._states.start_dragging()
        self._vertical_velocity = 0.0
        self._horizontal_velocity = 0.0
        self._landing_elapsed = 0.0

    def drag_to(
        self,
        position: Point,
        workspaces: tuple[Rect, ...],
    ) -> PetMotionSnapshot:
        if self.state.motion is not PetMotionState.DRAGGING:
            raise PetStateTransitionError
        workspace = select_workspace(position, self._window_size, workspaces)
        self._position = clamp_drag_position(
            position,
            self._window_size,
            workspace,
        )
        return self.snapshot

    def release_drag(
        self,
        workspaces: tuple[Rect, ...] | None = None,
    ) -> PetMotionSnapshot:
        if workspaces is not None:
            workspace = select_workspace(
                self._position,
                self._window_size,
                workspaces,
            )
            maximum_x = max(
                workspace.x,
                workspace.right - self._window_size.width,
            )
            released_x = min(max(self._position.x, workspace.x), maximum_x)
            if self.state.lifecycle is PetLifecycleState.PAUSED:
                self._position = clamp_window_position(
                    Point(released_x, self._position.y),
                    self._window_size,
                    workspace,
                )
            else:
                ground_y = max(
                    workspace.y,
                    workspace.bottom - self._window_size.height,
                )
                released_y = (
                    ground_y
                    if self._position.y + self._window_size.height
                    >= workspace.bottom
                    else self._position.y
                )
                self._position = Point(released_x, released_y)
        self._states.release_drag()
        self._vertical_velocity = 0.0
        self._horizontal_velocity = 0.0
        self._landing_elapsed = 0.0
        if (
            workspaces is not None
            and self.state.lifecycle is PetLifecycleState.ACTIVE
            and self._position.y + self._window_size.height
            >= workspace.bottom
        ):
            self._states.land()
        return self.snapshot

    def start_falling(self) -> None:
        self._states.start_falling()
        self._vertical_velocity = 0.0
        self._horizontal_velocity = 0.0

    def pause(self) -> None:
        self._states.pause()
        self._vertical_velocity = 0.0
        self._horizontal_velocity = 0.0

    def resume(self) -> None:
        self._states.resume()

    def begin_closing(self) -> None:
        self._states.begin_closing()
        self._vertical_velocity = 0.0
        self._horizontal_velocity = 0.0

    def recover_failed_close(self) -> None:
        self._states.recover_failed_close()

    def start_walking(self, direction: PetFacing) -> None:
        self._states.start_walking(direction)
        self._horizontal_velocity = (
            -self._config.walking_speed
            if direction is PetFacing.LEFT
            else self._config.walking_speed
        )

    def stop_walking(self) -> None:
        self._states.stop_walking()
        self._horizontal_velocity = 0.0

    def take_pending_direction_turn(self) -> PetFacing | None:
        """Consume one contained workspace-boundary direction proposal."""

        direction = self._pending_direction_turn
        self._pending_direction_turn = None
        return direction

    def constrain(self, workspaces: tuple[Rect, ...]) -> PetMotionSnapshot:
        workspace = select_workspace(
            self._position,
            self._window_size,
            workspaces,
        )
        clamped = clamp_window_position(
            self._position,
            self._window_size,
            workspace,
        )
        self._position = (
            Point(
                clamped.x,
                max(workspace.y, workspace.bottom - self._window_size.height),
            )
            if (
                self.state.lifecycle is PetLifecycleState.ACTIVE
                and self.state.motion is PetMotionState.IDLE
            )
            else clamped
        )
        return self.snapshot

    def place_for_render_layout(
        self,
        position: Point,
        workspace: Rect,
    ) -> PetMotionSnapshot:
        """Commit one render-layout target position without touching state.

        The resolved body position becomes the new official desktop position.
        The call is atomic: an invalid state, a vertical change, or a window
        that leaves the workspace raises without mutating position or layered
        state, and it never resets velocity or landing timers.
        """

        if (
            self.state.lifecycle is not PetLifecycleState.ACTIVE
            or self.state.motion is not PetMotionState.IDLE
        ):
            raise PetStateTransitionError
        if not (math.isfinite(position.x) and math.isfinite(position.y)):
            raise ValueError("Render-layout position must be finite.")
        if not math.isclose(position.y, self._position.y):
            raise ValueError(
                "Render-layout placement must not change the vertical position."
            )
        if not (
            position.x >= workspace.x
            and position.x + self._window_size.width <= workspace.right
            and position.y >= workspace.y
            and position.y + self._window_size.height <= workspace.bottom
        ):
            raise ValueError(
                "Render-layout placement must keep the window inside the workspace."
            )
        self._position = position
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
        clamped = clamp_window_position(
            position,
            self._window_size,
            workspace,
        )
        self._position = Point(
            clamped.x,
            max(workspace.y, workspace.bottom - self._window_size.height),
        )
        self._vertical_velocity = 0.0
        self._horizontal_velocity = 0.0
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
        candidate = Point(
            self._position.x + self._horizontal_velocity * elapsed_seconds,
            self._position.y,
        )
        clamped = clamp_window_position(
            candidate,
            self._window_size,
            workspace,
        )
        self._position = clamped
        if clamped.x != candidate.x:
            self._horizontal_velocity = 0.0
            self._pending_direction_turn = (
                PetFacing.RIGHT if moving_left else PetFacing.LEFT
            )
        return self.snapshot
