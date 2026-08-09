from __future__ import annotations

from sjtuclaw.application.pet_action_sequence import PetActionName
from sjtuclaw.application.pet_track0 import PlaybackRequest
from sjtuclaw.application.spine38_runtime import (
    Spine38PlaybackEvent,
    Spine38PlaybackEventType,
)
from sjtuclaw.presentation.qt.spine38_player import Spine38AnimationPlayer


class _Runtime:
    def __init__(self) -> None:
        self.set_calls: list[tuple[int, str, bool]] = []
        self.clear_calls: list[int] = []
        self.update_calls: list[float] = []
        self.events: tuple[Spine38PlaybackEvent, ...] = ()

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        self.set_calls.append((track, name, loop))

    def clear_track(self, track: int) -> None:
        self.clear_calls.append(track)

    def update(self, delta_seconds: float) -> tuple[Spine38PlaybackEvent, ...]:
        self.update_calls.append(delta_seconds)
        return self.events


def _request(generation: int, *, loop: bool = True) -> PlaybackRequest:
    return PlaybackRequest(
        generation=generation,
        track=0,
        logical_action=PetActionName.IDLE,
        physical_name="Relax",
        loop=loop,
        speed=1.0,
        mix_seconds=0.0,
    )


def test_player_maps_one_request_and_stamps_loop_identity() -> None:
    runtime = _Runtime()
    player = Spine38AnimationPlayer(runtime)
    token = player.play(_request(7))
    runtime.events = (
        Spine38PlaybackEvent(
            Spine38PlaybackEventType.LOOP_BOUNDARY,
            "Relax",
            1,
        ),
    )

    events = player.update(0.25)

    assert runtime.set_calls == [(0, "Relax", True)]
    assert runtime.update_calls == [0.25]
    assert len(events) == 1
    assert events[0].generation == 7
    assert events[0].logical_action is PetActionName.IDLE
    assert events[0].physical_name == "Relax"
    assert events[0].playback_token is token
    assert events[0].loop_boundary
    assert events[0].boundary_index == 1


def test_new_playback_and_clear_invalidate_old_event_identity() -> None:
    runtime = _Runtime()
    player = Spine38AnimationPlayer(runtime)
    old_token = player.play(_request(1))
    new_token = player.play(_request(2, loop=False))
    runtime.events = (
        Spine38PlaybackEvent(
            Spine38PlaybackEventType.COMPLETE,
            "Relax",
            0,
        ),
    )

    completion = player.update(1.0)
    player.clear(0, 0.0)
    runtime.events = (
        Spine38PlaybackEvent(
            Spine38PlaybackEventType.COMPLETE,
            "Relax",
            0,
        ),
    )

    assert old_token is not new_token
    assert completion[0].generation == 2
    assert completion[0].playback_token is new_token
    assert not completion[0].loop_boundary
    assert player.update(0.1) == ()
    assert runtime.clear_calls == [0]
