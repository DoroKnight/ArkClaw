"""Deterministic animation intent and scheduling for the placeholder pet."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Protocol

from sjtuclaw.application.pet_geometry import Rect, Size
from sjtuclaw.application.pet_motion import PetMotionModel, PetMotionSnapshot
from sjtuclaw.application.pet_state import (
    PetBehaviorState,
    PetFacing,
    PetLayeredState,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
)


class MonotonicClock(Protocol):
    def now(self) -> float:
        """Return monotonically increasing seconds."""


class SystemMonotonicClock:
    def now(self) -> float:
        return time.monotonic()


@dataclass(frozen=True, slots=True)
class PetAnimationConfig:
    maximum_delta_seconds: float = 0.1
    breathing_cycle_seconds: float = 2.4
    blinking_duration_seconds: float = 0.14
    blinking_interval_min_seconds: float = 2.0
    blinking_interval_max_seconds: float = 5.0
    walking_duration_seconds: float = 2.4
    thinking_duration_seconds: float = 1.2
    reminder_duration_seconds: float = 0.9
    random_action_interval_min_seconds: float = 4.0
    random_action_interval_max_seconds: float = 8.0

    def __post_init__(self) -> None:
        positive = (
            self.maximum_delta_seconds,
            self.breathing_cycle_seconds,
            self.blinking_duration_seconds,
            self.blinking_interval_min_seconds,
            self.blinking_interval_max_seconds,
            self.walking_duration_seconds,
            self.thinking_duration_seconds,
            self.reminder_duration_seconds,
            self.random_action_interval_min_seconds,
            self.random_action_interval_max_seconds,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("Pet animation timing must be positive.")
        if (
            self.blinking_interval_min_seconds
            > self.blinking_interval_max_seconds
            or self.random_action_interval_min_seconds
            > self.random_action_interval_max_seconds
        ):
            raise ValueError("Pet animation interval bounds are invalid.")


@dataclass(frozen=True, slots=True)
class PetAnimationIntent:
    base_action: PetMotionState
    facing: PetFacing
    loop: bool
    progress: float
    overlays: frozenset[PetBehaviorState]

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("Animation progress must be normalized.")


@dataclass(frozen=True, slots=True)
class PetVisualParameters:
    breathing_amount: float
    eye_openness: float
    body_wiggle: float
    thinking_tilt: float
    reminder_pulse: float


@dataclass(frozen=True, slots=True)
class PetRenderFrame:
    state: PetLayeredState
    animation_time: float
    window_size: Size
    intent: PetAnimationIntent
    visual: PetVisualParameters


@dataclass(frozen=True, slots=True)
class PetAnimationSnapshot:
    motion: PetMotionSnapshot
    frame: PetRenderFrame
    applied_delta_seconds: float


class PetAnimationEngine:
    """Advance movement and visual scheduling using explicit delta time."""

    def __init__(
        self,
        motion: PetMotionModel,
        *,
        rng: random.Random | None = None,
        config: PetAnimationConfig | None = None,
    ) -> None:
        self._motion = motion
        self._rng = rng or random.Random()
        self._config = config or PetAnimationConfig()
        self._animation_time = 0.0
        self._blink_elapsed = 0.0
        self._action_remaining = 0.0
        self._next_blink = self._new_blink_interval()
        self._next_random_action = self._new_random_action_interval()
        self._last_applied_delta = 0.0

    @property
    def motion(self) -> PetMotionModel:
        return self._motion

    @property
    def frame(self) -> PetRenderFrame:
        state = self._motion.state
        progress = self._base_progress(state.motion)
        intent = PetAnimationIntent(
            base_action=state.motion,
            facing=state.facing,
            loop=state.motion
            in {
                PetMotionState.IDLE,
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            },
            progress=progress,
            overlays=state.behaviors,
        )
        return PetRenderFrame(
            state=state,
            animation_time=self._animation_time,
            window_size=self._motion.window_size,
            intent=intent,
            visual=self._visual_parameters(state, progress),
        )

    @property
    def last_applied_delta_seconds(self) -> float:
        return self._last_applied_delta

    def advance(
        self,
        elapsed_seconds: float,
        workspaces: tuple[Rect, ...],
    ) -> PetAnimationSnapshot:
        if elapsed_seconds < 0:
            raise ValueError("Elapsed animation time must not be negative.")
        if self._motion.state.lifecycle is not PetLifecycleState.ACTIVE:
            self._last_applied_delta = 0.0
            motion = self._motion.update(0.0, workspaces)
            return self._snapshot(motion)

        applied = min(
            elapsed_seconds,
            self._config.maximum_delta_seconds,
        )
        self._last_applied_delta = applied
        self._animation_time += applied
        self._advance_action(applied)
        self._advance_blink(applied)
        self._advance_random_action(applied)
        motion = self._motion.update(applied, workspaces)
        return self._snapshot(motion)

    def request_walk(self, direction: PetFacing) -> None:
        self._motion.start_walking(direction)
        self._action_remaining = self._config.walking_duration_seconds

    def request_thinking_animation(self) -> None:
        state = self._motion.state
        if state.motion in {
            PetMotionState.WALKING_LEFT,
            PetMotionState.WALKING_RIGHT,
        }:
            self._motion.stop_walking()
        self._motion.states.start_thinking()
        self._action_remaining = self._config.thinking_duration_seconds

    def request_reminder_animation(self) -> None:
        self._motion.states.start_reminding()
        self._action_remaining = self._config.reminder_duration_seconds

    def start_dragging(self) -> None:
        self._action_remaining = 0.0
        self._motion.start_dragging()

    def release_drag(self) -> None:
        self._motion.release_drag()

    def pause(self) -> None:
        self._motion.pause()

    def resume(self) -> None:
        self._motion.resume()

    def begin_closing(self) -> None:
        self._action_remaining = 0.0
        self._motion.begin_closing()

    def recover_failed_close(self) -> None:
        self._motion.recover_failed_close()

    def _advance_action(self, elapsed_seconds: float) -> None:
        if self._action_remaining <= 0:
            return
        self._action_remaining = max(
            0.0,
            self._action_remaining - elapsed_seconds,
        )
        if self._action_remaining > 0:
            return
        state = self._motion.state
        try:
            if state.motion in {
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            }:
                self._motion.stop_walking()
            elif PetBehaviorState.THINKING in state.behaviors:
                self._motion.states.finish_thinking()
            elif PetBehaviorState.REMINDING in state.behaviors:
                self._motion.states.finish_reminding()
        except PetStateTransitionError:
            return
        self._next_random_action = self._new_random_action_interval()

    def _advance_blink(self, elapsed_seconds: float) -> None:
        state = self._motion.state
        if PetBehaviorState.BLINKING in state.behaviors:
            self._blink_elapsed += elapsed_seconds
            if (
                self._blink_elapsed
                >= self._config.blinking_duration_seconds
            ):
                self._motion.states.finish_blinking()
                self._blink_elapsed = 0.0
                self._next_blink = self._new_blink_interval()
            return
        self._next_blink -= elapsed_seconds
        if self._next_blink <= 0:
            self._motion.states.start_blinking()
            if PetBehaviorState.BLINKING in self._motion.state.behaviors:
                self._blink_elapsed = 0.0
            else:
                self._next_blink = self._new_blink_interval()

    def _advance_random_action(self, elapsed_seconds: float) -> None:
        state = self._motion.state
        if (
            self._action_remaining > 0
            or state.motion is not PetMotionState.IDLE
            or state.behaviors
            != frozenset({PetBehaviorState.BREATHING})
        ):
            return
        self._next_random_action -= elapsed_seconds
        if self._next_random_action > 0:
            return
        selection = self._rng.randrange(3)
        if selection == 0:
            self.request_walk(PetFacing.LEFT)
        elif selection == 1:
            self.request_walk(PetFacing.RIGHT)
        else:
            self.request_thinking_animation()

    def _base_progress(self, motion: PetMotionState) -> float:
        period = (
            self._motion.config.walking_cycle_seconds
            if motion
            in {
                PetMotionState.WALKING_LEFT,
                PetMotionState.WALKING_RIGHT,
            }
            else self._config.breathing_cycle_seconds
        )
        return (self._animation_time % period) / period

    def _visual_parameters(
        self,
        state: PetLayeredState,
        base_progress: float,
    ) -> PetVisualParameters:
        breathing = (
            (1.0 - math.cos(base_progress * math.tau)) / 2.0
            if PetBehaviorState.BREATHING in state.behaviors
            else 0.0
        )
        if PetBehaviorState.BLINKING in state.behaviors:
            blink_progress = min(
                1.0,
                self._blink_elapsed
                / self._config.blinking_duration_seconds,
            )
            eye_openness = abs(2.0 * blink_progress - 1.0)
        else:
            eye_openness = 1.0
        body_wiggle = (
            math.sin(self._animation_time * math.tau * 5.0)
            if PetBehaviorState.DRAG_STRUGGLE in state.behaviors
            else 0.0
        )
        thinking_tilt = (
            math.sin(self._animation_time * math.tau * 0.8)
            if PetBehaviorState.THINKING in state.behaviors
            else 0.0
        )
        reminder_pulse = (
            (1.0 - math.cos(self._animation_time * math.tau * 3.0))
            / 2.0
            if PetBehaviorState.REMINDING in state.behaviors
            else 0.0
        )
        return PetVisualParameters(
            breathing_amount=breathing,
            eye_openness=eye_openness,
            body_wiggle=body_wiggle,
            thinking_tilt=thinking_tilt,
            reminder_pulse=reminder_pulse,
        )

    def _new_blink_interval(self) -> float:
        return self._rng.uniform(
            self._config.blinking_interval_min_seconds,
            self._config.blinking_interval_max_seconds,
        )

    def _new_random_action_interval(self) -> float:
        return self._rng.uniform(
            self._config.random_action_interval_min_seconds,
            self._config.random_action_interval_max_seconds,
        )

    def _snapshot(
        self,
        motion: PetMotionSnapshot,
    ) -> PetAnimationSnapshot:
        return PetAnimationSnapshot(
            motion=motion,
            frame=self.frame,
            applied_delta_seconds=self._last_applied_delta,
        )
