from __future__ import annotations

from dataclasses import replace

import pytest
from tests.fakes.pet_animation_player import FakeAnimationPlayer

from arkclaw.application.pet.pet_action_sequence import (
    SEQUENCE_CATALOG,
    AnimationRegistry,
    InterruptClass,
    PlaybackHealth,
    SequenceName,
    default_animation_registry,
)
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    ActionRequest,
    AnimationPlayerCapabilities,
    CancellationMode,
    CancelReason,
    PetTrack0Controller,
    PlaybackEvent,
    WatchdogPolicy,
    sequencing_enabled,
)


class FakeClock:
    def __init__(self, now: float = 10.0) -> None:
        self.value = now

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _registry(duration: float | None = 1.0) -> AnimationRegistry:
    identity = default_animation_registry()
    return AnimationRegistry(
        {
            action: replace(
                identity.resolve(action),
                source_duration_seconds=duration,
            )
            for action in identity.actions
        }
    )


def _request(sequence_name: SequenceName) -> ActionRequest:
    entry = SEQUENCE_CATALOG[sequence_name]
    return ActionRequest(
        sequence_name=sequence_name,
        interruption_class=entry.interruption_class,
        protected=entry.protected,
        request_token=object(),
        semantic_epoch=1,
        input_session_token=(
            object() if entry.interruption_class is InterruptClass.USER_INTERACTION else None
        ),
    )


def _controller(
    player: FakeAnimationPlayer,
    clock: FakeClock,
    *,
    duration: float | None = 1.0,
) -> PetTrack0Controller:
    return PetTrack0Controller(
        player=player,
        registry=_registry(duration),
        clock=clock,
    )


@pytest.mark.parametrize("missing", range(4))
def test_each_missing_capability_disables_production_sequencing(
    missing: int,
) -> None:
    values = [True, True, True, True]
    values[missing] = False
    capabilities = AnimationPlayerCapabilities(*values)

    assert not sequencing_enabled(capabilities)


def test_all_capabilities_enable_production_sequencing() -> None:
    assert sequencing_enabled(AnimationPlayerCapabilities(True, True, True, True))


@pytest.mark.parametrize(
    ("source_duration", "speed", "expected"),
    [(0.4, 1.0, 10.65), (4.0, 2.0, 12.5), (40.0, 2.0, 31.0)],
)
def test_watchdog_deadline_uses_bounded_tolerance(
    source_duration: float,
    speed: float,
    expected: float,
) -> None:
    assert WatchdogPolicy().deadline(
        10.0,
        source_duration,
        speed,
    ) == pytest.approx(expected)


@pytest.mark.parametrize("speed", [0.0, -1.0])
def test_watchdog_rejects_non_positive_speed(speed: float) -> None:
    with pytest.raises(ValueError):
        WatchdogPolicy().deadline(10.0, 1.0, speed)


def test_missing_capability_rejects_preflight_without_mutation() -> None:
    capabilities = AnimationPlayerCapabilities(True, False, True, True)
    player = FakeAnimationPlayer(capabilities=capabilities)
    clock = FakeClock()
    controller = _controller(player, clock)

    outcome = controller.play(_request(SequenceName.WAVE))

    assert outcome is ActionOutcome.SEQUENCING_DISABLED_CAPABILITY
    assert player.calls == []
    assert controller.generation == 0


def test_missing_duration_never_arms_or_guesses_a_deadline() -> None:
    player = FakeAnimationPlayer()
    clock = FakeClock()
    controller = _controller(player, clock, duration=None)

    outcome = controller.play(_request(SequenceName.WAVE))

    assert outcome is ActionOutcome.REGISTRY_MISMATCH
    assert controller.watchdog_deadline is None
    assert player.calls == []


def test_one_shot_deadline_is_armed_only_after_successful_play() -> None:
    player = FakeAnimationPlayer()
    clock = FakeClock()
    controller = _controller(player, clock, duration=0.4)

    controller.play(_request(SequenceName.WAVE))

    assert controller.watchdog_deadline == pytest.approx(10.65)
    assert controller.poll_watchdog() is None


def test_loop_has_no_deadline_until_graceful_exit_is_pending() -> None:
    player = FakeAnimationPlayer()
    clock = FakeClock()
    controller = _controller(player, clock)
    controller.play(_request(SequenceName.SLEEP))
    start_epoch = controller.state.confirmed_epoch
    assert start_epoch is not None
    controller.handle_completion(
        PlaybackEvent(
            generation=start_epoch.generation,
            logical_action=start_epoch.logical_action,
            physical_name=start_epoch.physical_name,
            playback_token=start_epoch.playback_token,
        )
    )

    assert controller.watchdog_deadline is None
    controller.cancel(
        CancelReason.USER_INTERRUPT,
        CancellationMode.GRACEFUL_EXIT,
    )
    assert controller.watchdog_deadline == pytest.approx(11.25)


def test_replace_only_loop_never_arms_boundary_watchdog() -> None:
    player = FakeAnimationPlayer()
    clock = FakeClock()
    controller = _controller(player, clock)
    controller.play(_request(SequenceName.DRAG_HOLD))
    start_epoch = controller.state.confirmed_epoch
    assert start_epoch is not None
    controller.handle_completion(
        PlaybackEvent(
            generation=start_epoch.generation,
            logical_action=start_epoch.logical_action,
            physical_name=start_epoch.physical_name,
            playback_token=start_epoch.playback_token,
        )
    )

    outcome = controller.cancel(
        CancelReason.USER_INTERRUPT,
        CancellationMode.GRACEFUL_EXIT,
    )

    assert outcome is ActionOutcome.INVALID_SEQUENCE
    assert controller.watchdog_deadline is None


def test_timeout_clear_success_is_degraded_without_fallback_play() -> None:
    player = FakeAnimationPlayer()
    clock = FakeClock()
    controller = _controller(player, clock, duration=0.4)
    controller.play(_request(SequenceName.WAVE))
    clock.advance(0.66)

    outcome = controller.poll_watchdog()

    assert outcome is ActionOutcome.CALLBACK_TIMEOUT
    assert controller.state.health is PlaybackHealth.DEGRADED
    assert controller.state.desired_action is None
    assert controller.state.confirmed_epoch is None
    assert controller.runner.snapshot.sequence is None
    assert [call.operation for call in player.calls] == ["play", "clear"]


def test_timeout_clear_failure_makes_renderer_unknown() -> None:
    player = FakeAnimationPlayer(fail_clear=True)
    clock = FakeClock()
    controller = _controller(player, clock, duration=0.4)
    controller.play(_request(SequenceName.WAVE))
    clock.advance(0.66)

    outcome = controller.poll_watchdog()

    assert outcome is ActionOutcome.CALLBACK_TIMEOUT
    assert controller.state.health is PlaybackHealth.UNKNOWN
    assert [call.operation for call in player.calls] == ["play", "clear"]
