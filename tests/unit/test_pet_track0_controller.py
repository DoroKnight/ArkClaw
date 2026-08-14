from __future__ import annotations

from dataclasses import replace

from tests.fakes.pet_animation_player import FakeAnimationPlayer

from arkclaw.application.pet.pet_action_sequence import (
    SEQUENCE_CATALOG,
    AnimationRegistry,
    InterruptClass,
    PetActionName,
    PlaybackHealth,
    SequenceName,
    default_animation_registry,
)
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    ActionRequest,
    CancellationMode,
    CancelReason,
    PetTrack0Controller,
    PlaybackEvent,
    Track0PlaybackState,
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
) -> PetTrack0Controller:
    identity = default_animation_registry()
    registry = AnimationRegistry(
        {
            action: replace(
                identity.resolve(action),
                source_duration_seconds=1.0,
            )
            for action in identity.actions
        }
    )
    return PetTrack0Controller(
        player=player,
        registry=registry,
    )


def test_successful_play_confirms_exact_renderer_epoch() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)

    outcome = controller.play(_request(SequenceName.WAVE))

    assert outcome is ActionOutcome.ACCEPTED
    assert controller.state.desired_action is PetActionName.WAVE
    assert controller.state.health is PlaybackHealth.HEALTHY
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.generation == 1
    assert controller.state.confirmed_epoch.logical_action is PetActionName.WAVE
    assert controller.state.confirmed_epoch.physical_name == "wave"
    assert player.calls[0].playback is not None
    assert player.calls[0].playback.track == 0


def test_every_play_and_clear_attempt_consumes_generation() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)

    controller.play(_request(SequenceName.WAVE))
    controller.clear(CancelReason.PAUSE)

    assert [call.generation for call in player.calls] == [1, 2]
    assert controller.generation == 2


def test_replace_installs_new_animation_without_clearing_mix_source() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    controller.play(_request(SequenceName.DRAG_RELEASE))

    outcome = controller.cancel(
        CancelReason.USER_INTERRUPT,
        CancellationMode.REPLACE,
        replacement=_request(SequenceName.DRAG_HOLD),
    )

    assert outcome is ActionOutcome.ACCEPTED
    assert [call.operation for call in player.calls] == ["play", "play"]
    assert [call.generation for call in player.calls] == [1, 2]
    assert controller.state.desired_action is PetActionName.DRAG_START


def test_failed_play_with_successful_containment_is_degraded_and_empty() -> None:
    player = FakeAnimationPlayer(fail_play=True)
    controller = _controller(player)

    outcome = controller.play(_request(SequenceName.WAVE))

    assert outcome is ActionOutcome.PLAYBACK_DEGRADED
    assert controller.state == Track0PlaybackState(
        None,
        None,
        PlaybackHealth.DEGRADED,
    )
    assert [call.operation for call in player.calls] == ["play", "clear"]
    assert [call.generation for call in player.calls] == [1, 2]
    assert controller.runner.snapshot.sequence is None


def test_failed_play_and_failed_containment_make_renderer_unknown() -> None:
    player = FakeAnimationPlayer(fail_play=True, fail_clear=True)
    controller = _controller(player)

    outcome = controller.play(_request(SequenceName.WAVE))

    assert outcome is ActionOutcome.RENDERER_STATE_UNKNOWN
    assert controller.state == Track0PlaybackState(
        None,
        None,
        PlaybackHealth.UNKNOWN,
    )
    assert controller.runner.snapshot.sequence is None


def test_failed_normal_clear_never_reports_old_epoch_as_confirmed() -> None:
    player = FakeAnimationPlayer(fail_clear=True)
    controller = _controller(player)
    controller.play(_request(SequenceName.WAVE))

    outcome = controller.clear(CancelReason.PAUSE)

    assert outcome is ActionOutcome.RENDERER_STATE_UNKNOWN
    assert controller.state == Track0PlaybackState(
        None,
        None,
        PlaybackHealth.UNKNOWN,
    )
    assert controller.runner.snapshot.sequence is None


def test_graceful_cancel_only_arms_runner_and_sends_no_player_command() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    controller.play(_request(SequenceName.SLEEP))
    epoch = controller.state.confirmed_epoch
    assert epoch is not None
    controller.handle_completion(
        PlaybackEvent(
            generation=epoch.generation,
            logical_action=epoch.logical_action,
            physical_name=epoch.physical_name,
            playback_token=epoch.playback_token,
        )
    )
    assert len(player.calls) == 2

    outcome = controller.cancel(
        CancelReason.USER_INTERRUPT,
        CancellationMode.GRACEFUL_EXIT,
    )

    assert outcome is ActionOutcome.ACCEPTED
    assert len(player.calls) == 2
    assert controller.runner.snapshot.pending_graceful_exit


def test_immediate_clear_resets_runner_without_fallback_idle() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    controller.play(_request(SequenceName.WAVE))

    outcome = controller.cancel(
        CancelReason.SYSTEM_SHUTDOWN,
        CancellationMode.IMMEDIATE_CLEAR,
    )

    assert outcome is ActionOutcome.CLEARED
    assert [call.operation for call in player.calls] == ["play", "clear"]
    assert controller.state.desired_action is None
    assert controller.state.confirmed_epoch is None
    assert controller.runner.snapshot.sequence is None


def test_stale_callback_after_replacement_is_side_effect_free() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    controller.play(_request(SequenceName.DRAG_RELEASE))
    stale = controller.state.confirmed_epoch
    assert stale is not None
    controller.cancel(
        CancelReason.USER_INTERRUPT,
        CancellationMode.REPLACE,
        replacement=_request(SequenceName.DRAG_HOLD),
    )
    before_state = controller.state
    before_calls = tuple(player.calls)

    outcome = controller.handle_completion(
        PlaybackEvent(
            generation=stale.generation,
            logical_action=stale.logical_action,
            physical_name=stale.physical_name,
            playback_token=stale.playback_token,
        )
    )

    assert outcome is ActionOutcome.STALE_COMPLETION
    assert controller.state == before_state
    assert tuple(player.calls) == before_calls


def test_non_track_zero_sequence_fails_preflight_without_player_mutation() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    request = ActionRequest(
        sequence_name=SequenceName.BREATHING,
        interruption_class=InterruptClass.NORMAL_ACTION,
        protected=False,
        request_token=object(),
        semantic_epoch=1,
    )

    preflight = controller.preflight(request)
    outcome = controller.play(request)

    assert preflight.outcome is ActionOutcome.INVALID_SEQUENCE
    assert outcome is ActionOutcome.INVALID_SEQUENCE
    assert player.calls == []
    assert controller.generation == 0


def test_catalog_request_policy_cannot_be_forged_during_preflight() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    forged = ActionRequest(
        sequence_name=SequenceName.WAVE,
        interruption_class=InterruptClass.NORMAL_ACTION,
        protected=False,
        request_token=object(),
        semantic_epoch=1,
    )

    assert controller.preflight(forged).outcome is ActionOutcome.INVALID_SEQUENCE
    assert controller.play(forged) is ActionOutcome.INVALID_SEQUENCE
    assert player.calls == []


def test_direct_second_play_cannot_bypass_replacement_protocol() -> None:
    player = FakeAnimationPlayer()
    controller = _controller(player)
    controller.play(_request(SequenceName.WAVE))
    before_state = controller.state

    outcome = controller.play(_request(SequenceName.HAPPY))

    assert outcome is ActionOutcome.REJECTED_PRIORITY
    assert controller.state == before_state
    assert [call.operation for call in player.calls] == ["play"]


def test_player_exceptions_do_not_escape_controller_boundary() -> None:
    player = FakeAnimationPlayer(fail_play=True, fail_clear=True)
    controller = _controller(player)

    play_outcome = controller.play(_request(SequenceName.WAVE))
    clear_outcome = controller.clear(CancelReason.RENDERER_FAILURE)

    assert play_outcome is ActionOutcome.RENDERER_STATE_UNKNOWN
    assert clear_outcome is ActionOutcome.RENDERER_STATE_UNKNOWN
