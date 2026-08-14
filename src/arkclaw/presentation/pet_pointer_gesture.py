"""Framework-free click/drag gesture transaction for the pet window."""

from __future__ import annotations

import math
from enum import StrEnum

from arkclaw.application.pet_geometry import Point


class PointerGestureState(StrEnum):
    IDLE = "idle"
    PENDING = "pending"
    DRAGGING = "dragging"


class GestureDecision(StrEnum):
    NONE = "none"
    BEGIN_DRAG = "begin_drag"
    DRAG = "drag"
    CLICK = "click"
    CANCEL_PENDING = "cancel_pending"
    RELEASE_ACTIVE_DRAG = "release_active_drag"
    ABORT_ACTIVE_DRAG = "abort_active_drag"


class GestureCancelReason(StrEnum):
    POINTER_CAPTURE_LOST = "pointer_capture_lost"
    WINDOW_HIDDEN = "window_hidden"
    PAUSE_REQUESTED = "pause_requested"
    RENDERER_DEGRADED = "renderer_degraded"
    PLAYBACK_DEGRADED = "playback_degraded"
    CLOSING = "closing"


class PetPointerGesture:
    """Snapshot the system threshold at press and emit semantic decisions."""

    def __init__(self) -> None:
        self._state = PointerGestureState.IDLE
        self._press_local: Point | None = None
        self._press_global: Point | None = None
        self._session_drag_threshold: float | None = None
        self._maximum_distance = 0.0

    @property
    def state(self) -> PointerGestureState:
        return self._state

    @property
    def press_local(self) -> Point | None:
        return self._press_local

    def press(
        self,
        local: Point,
        global_: Point,
        drag_threshold: float,
    ) -> GestureDecision:
        if (
            not math.isfinite(drag_threshold)
            or drag_threshold <= 0.0
        ):
            raise ValueError("drag threshold must be finite and positive")
        if self._state is not PointerGestureState.IDLE:
            self.cancel(GestureCancelReason.CLOSING)
        self._state = PointerGestureState.PENDING
        self._press_local = local
        self._press_global = global_
        self._session_drag_threshold = drag_threshold
        self._maximum_distance = 0.0
        return GestureDecision.NONE

    def move(self, global_: Point) -> GestureDecision:
        if self._state is PointerGestureState.IDLE:
            return GestureDecision.NONE
        if self._state is PointerGestureState.DRAGGING:
            return GestureDecision.DRAG
        start = self._press_global
        threshold = self._session_drag_threshold
        if start is None or threshold is None:
            return GestureDecision.NONE
        distance = abs(global_.x - start.x) + abs(global_.y - start.y)
        self._maximum_distance = max(self._maximum_distance, distance)
        if self._maximum_distance < threshold:
            return GestureDecision.NONE
        self._state = PointerGestureState.DRAGGING
        return GestureDecision.BEGIN_DRAG

    def release(self, global_: Point) -> GestureDecision:
        if self._state is PointerGestureState.IDLE:
            return GestureDecision.NONE
        if self._state is PointerGestureState.PENDING:
            self.move(global_)
        decision = (
            GestureDecision.RELEASE_ACTIVE_DRAG
            if self._state is PointerGestureState.DRAGGING
            else GestureDecision.CLICK
        )
        self._reset()
        return decision

    def cancel(self, reason: GestureCancelReason) -> GestureDecision:
        if self._state is PointerGestureState.IDLE:
            return GestureDecision.NONE
        if self._state is PointerGestureState.PENDING:
            decision = GestureDecision.CANCEL_PENDING
        elif reason is GestureCancelReason.POINTER_CAPTURE_LOST:
            decision = GestureDecision.RELEASE_ACTIVE_DRAG
        else:
            decision = GestureDecision.ABORT_ACTIVE_DRAG
        self._reset()
        return decision

    def _reset(self) -> None:
        self._state = PointerGestureState.IDLE
        self._press_local = None
        self._press_global = None
        self._session_drag_threshold = None
        self._maximum_distance = 0.0
