from __future__ import annotations

from dataclasses import dataclass

from arkclaw.application.pet_track0 import (
    AnimationPlayerCapabilities,
    PlaybackRequest,
    PlaybackToken,
)


@dataclass(frozen=True, slots=True)
class FakePlayerCall:
    generation: int
    operation: str
    playback: PlaybackRequest | None = None
    track: int | None = None
    mix_seconds: float | None = None


class FakeAnimationPlayer:
    def __init__(
        self,
        *,
        fail_play: bool = False,
        fail_clear: bool = False,
        capabilities: AnimationPlayerCapabilities | None = None,
    ) -> None:
        self._fail_play = fail_play
        self._fail_clear = fail_clear
        self._capabilities = capabilities or AnimationPlayerCapabilities(
            True,
            True,
            True,
            True,
        )
        self._next_token = 0
        self.calls: list[FakePlayerCall] = []

    @property
    def capabilities(self) -> AnimationPlayerCapabilities:
        return self._capabilities

    def play(self, request: PlaybackRequest) -> PlaybackToken:
        self.calls.append(
            FakePlayerCall(
                generation=request.generation,
                operation="play",
                playback=request,
            )
        )
        if self._fail_play:
            raise RuntimeError("injected play failure")
        self._next_token += 1
        return ("fake-playback", self._next_token)

    def clear(self, track: int, mix_seconds: float) -> None:
        self.calls.append(
            FakePlayerCall(
                generation=len(self.calls) + 1,
                operation="clear",
                track=track,
                mix_seconds=mix_seconds,
            )
        )
        if self._fail_clear:
            raise RuntimeError("injected clear failure")
