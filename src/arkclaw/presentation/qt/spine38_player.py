"""Track 0 player adapter for verified Spine 3.8 runtime events."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from arkclaw.application.pet_action_sequence import PetActionName
from arkclaw.application.pet_track0 import (
    AnimationPlayerCapabilities,
    PlaybackEvent,
    PlaybackRequest,
    PlaybackToken,
)
from arkclaw.application.spine38_runtime import (
    Spine38PlaybackEvent,
    Spine38PlaybackEventType,
)

_LAYOUT_EXCLUSIVE_ACTIONS = frozenset(
    {PetActionName.WAVE, PetActionName.HAPPY}
)


class Spine38PlaybackRuntime(Protocol):
    def mix_animation(
        self,
        track: int,
        name: str,
        loop: bool,
        mix_seconds: float,
    ) -> None: ...

    def clear_track(self, track: int) -> None: ...

    def update(self, delta_seconds: float) -> tuple[Spine38PlaybackEvent, ...]: ...


@dataclass(frozen=True, slots=True)
class _ActivePlayback:
    generation: int
    logical_action: PetActionName
    physical_name: str
    loop: bool
    token: PlaybackToken


class Spine38AnimationPlayer:
    """Map one controller request to native Track 0 and stamp callbacks."""

    def __init__(self, runtime: Spine38PlaybackRuntime) -> None:
        self._runtime = runtime
        self._active: _ActivePlayback | None = None
        self._capabilities = AnimationPlayerCapabilities(True, True, True, True)

    @property
    def capabilities(self) -> AnimationPlayerCapabilities:
        return self._capabilities

    def play(self, request: PlaybackRequest) -> PlaybackToken:
        if request.track != 0:
            raise ValueError("Spine38AnimationPlayer owns Track 0 only")
        token = object()
        active = self._active
        mix_seconds = request.mix_seconds
        if request.logical_action in _LAYOUT_EXCLUSIVE_ACTIONS or (
            active is not None
            and active.logical_action in _LAYOUT_EXCLUSIVE_ACTIONS
        ):
            mix_seconds = 0.0
        self._runtime.mix_animation(
            request.track,
            request.physical_name,
            request.loop,
            mix_seconds,
        )
        self._active = _ActivePlayback(
            request.generation,
            request.logical_action,
            request.physical_name,
            request.loop,
            token,
        )
        return token

    def clear(self, track: int, mix_seconds: float) -> None:
        if track != 0 or not math.isfinite(mix_seconds) or mix_seconds < 0.0:
            raise ValueError("invalid Track 0 clear")
        self._runtime.clear_track(track)
        self._active = None

    def update(self, delta_seconds: float) -> tuple[PlaybackEvent, ...]:
        native_events = self._runtime.update(delta_seconds)
        active = self._active
        if active is None:
            return ()
        events: list[PlaybackEvent] = []
        for event in native_events:
            if event.physical_name != active.physical_name:
                raise RuntimeError("Spine playback event identity mismatch")
            loop_boundary = (
                event.event_type is Spine38PlaybackEventType.LOOP_BOUNDARY
            )
            if loop_boundary is not active.loop:
                raise RuntimeError("Spine playback event type mismatch")
            events.append(
                PlaybackEvent(
                    generation=active.generation,
                    logical_action=active.logical_action,
                    physical_name=active.physical_name,
                    playback_token=active.token,
                    loop_boundary=loop_boundary,
                    boundary_index=(event.loop_ordinal if loop_boundary else None),
                )
            )
        return tuple(events)
