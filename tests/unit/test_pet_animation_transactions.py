from __future__ import annotations

from dataclasses import replace

import pytest
from tests.fakes.pet_animation_player import FakeAnimationPlayer

from arkclaw.application.pet_action_sequence import (
    AnimationRegistry,
    PetActionName,
    PlaybackHealth,
    default_animation_registry,
)
from arkclaw.application.pet_animation import (
    PetAnimationEngine,
    PetAnimationEvent,
)
from arkclaw.application.pet_geometry import Point, Rect, Size
from arkclaw.application.pet_motion import PetMotionModel
from arkclaw.application.pet_state import (
    PetActivityState,
    PetLayeredStateMachine,
    PetMotionState,
    assert_animation_compatible,
)
from arkclaw.application.pet_track0 import (
    ActionOutcome,
    PetTrack0Controller,
    PlaybackEvent,
)


def _registry_without_duration_for(
    missing: PetActionName | None = None,
) -> AnimationRegistry:
    identity = default_animation_registry()
    return AnimationRegistry(
        {
            action: replace(
                identity.resolve(action),
                source_duration_seconds=(None if action is missing else 1.0),
            )
            for action in identity.actions
        }
    )


def _transaction_engine(
    *,
    initial_epoch: int = 0,
    y: float = 480,
    missing_duration: PetActionName | None = None,
    fail_play: bool = False,
    fail_clear: bool = False,
) -> tuple[
    PetAnimationEngine,
    PetTrack0Controller,
    PetLayeredStateMachine,
    FakeAnimationPlayer,
]:
    machine = PetLayeredStateMachine(initial_epoch=initial_epoch)
    motion = PetMotionModel(
        Point(100, y),
        Size(100, 120),
        states=machine,
    )
    player = FakeAnimationPlayer(fail_play=fail_play, fail_clear=fail_clear)
    controller = PetTrack0Controller(
        player=player,
        registry=_registry_without_duration_for(missing_duration),
    )
    return (
        PetAnimationEngine(motion, track0=controller),
        controller,
        machine,
        player,
    )


def test_action_request_copies_state_proposal_target_epoch() -> None:
    engine, controller, machine, _player = _transaction_engine(initial_epoch=17)

    outcome = engine.handle_event(PetAnimationEvent.start_reading(token=object()))

    assert outcome is ActionOutcome.ACCEPTED
    assert controller.active_request is not None
    assert controller.active_request.semantic_epoch == 18
    assert machine.epoch == 18
    assert machine.snapshot.activity is PetActivityState.READING
    assert_animation_compatible(
        machine.snapshot,
        controller.state.desired_action,
        controller.state.health,
    )


def test_normal_preflight_rejection_commits_neither_state_nor_epoch() -> None:
    engine, controller, machine, player = _transaction_engine(
        initial_epoch=17,
        missing_duration=PetActionName.READ,
    )

    outcome = engine.handle_event(PetAnimationEvent.start_reading(token=object()))

    assert outcome is ActionOutcome.REGISTRY_MISMATCH
    assert machine.epoch == 17
    assert machine.snapshot.activity is PetActivityState.NONE
    assert controller.active_request is None
    assert player.calls == []


@pytest.mark.parametrize(
    ("clear_fails", "health", "outcome"),
    [
        (
            False,
            PlaybackHealth.DEGRADED,
            ActionOutcome.PLAYBACK_DEGRADED,
        ),
        (
            True,
            PlaybackHealth.UNKNOWN,
            ActionOutcome.RENDERER_STATE_UNKNOWN,
        ),
    ],
)
def test_mandatory_fall_commits_then_contains_failed_preflight(
    clear_fails: bool,
    health: PlaybackHealth,
    outcome: ActionOutcome,
) -> None:
    engine, controller, machine, player = _transaction_engine(
        missing_duration=PetActionName.DRAG_END,
        fail_clear=clear_fails,
    )
    assert (
        engine.handle_event(PetAnimationEvent.start_reading(token=object()))
        is ActionOutcome.ACCEPTED
    )

    result = engine.handle_event(PetAnimationEvent.start_falling())

    assert result is outcome
    assert machine.snapshot.motion is PetMotionState.FALLING
    assert machine.epoch == 2
    assert controller.state.desired_action is None
    assert controller.state.confirmed_epoch is None
    assert controller.state.health is health
    assert controller.runner.snapshot.sequence is None
    played_actions = [
        call.playback.logical_action
        for call in player.calls
        if call.playback is not None
    ]
    assert PetActionName.DRAG_END not in played_actions
    assert_animation_compatible(
        machine.snapshot,
        controller.state.desired_action,
        controller.state.health,
    )


def test_mandatory_fall_commits_when_degraded_health_blocks_replacement() -> None:
    engine, controller, machine, _player = _transaction_engine(fail_play=True)
    assert (
        engine.handle_event(PetAnimationEvent.start_reading(token=object()))
        is ActionOutcome.PLAYBACK_DEGRADED
    )

    outcome = engine.handle_event(PetAnimationEvent.start_falling())

    assert outcome is ActionOutcome.PLAYBACK_DEGRADED
    assert machine.snapshot.motion is PetMotionState.FALLING
    assert machine.epoch == 2
    assert controller.state.desired_action is None
    assert controller.state.health is PlaybackHealth.DEGRADED


def _current_callback(
    controller: PetTrack0Controller,
    *,
    loop_boundary: bool = False,
) -> PlaybackEvent:
    confirmed = controller.state.confirmed_epoch
    assert confirmed is not None
    return PlaybackEvent(
        generation=confirmed.generation,
        logical_action=confirmed.logical_action,
        physical_name=confirmed.physical_name,
        playback_token=confirmed.playback_token,
        loop_boundary=loop_boundary,
    )


def test_legacy_request_methods_keep_direct_semantics() -> None:
    machine = PetLayeredStateMachine()
    engine = PetAnimationEngine(
        PetMotionModel(
            Point(100, 480),
            Size(100, 120),
            states=machine,
        )
    )

    outcome = engine.request_walk(engine.motion.state.facing)

    assert outcome is ActionOutcome.LEGACY_DIRECT
    assert machine.snapshot.motion is PetMotionState.WALKING_RIGHT


def test_production_drag_lifecycle_uses_one_session_then_new_press_replaces() -> None:
    engine, controller, machine, _player = _transaction_engine()

    first_drag = engine.start_dragging()
    drag_start_callback = _current_callback(controller)
    drag_loop = engine.handle_playback_event(drag_start_callback)
    release = engine.release_drag()
    old_release_callback = _current_callback(controller)
    second_drag = engine.start_dragging()
    stale = engine.handle_playback_event(old_release_callback)

    assert first_drag is ActionOutcome.ACCEPTED
    assert drag_loop is ActionOutcome.ACCEPTED
    assert release is ActionOutcome.ACCEPTED
    assert second_drag is ActionOutcome.ACCEPTED
    assert stale is ActionOutcome.STALE_COMPLETION
    assert machine.snapshot.motion is PetMotionState.DRAGGING
    assert controller.state.desired_action is PetActionName.DRAG_START
    assert_animation_compatible(
        machine.snapshot,
        controller.state.desired_action,
        controller.state.health,
    )


def test_loop_boundary_without_exit_is_observational_through_engine() -> None:
    engine, controller, machine, player = _transaction_engine()
    assert (
        engine.handle_event(PetAnimationEvent.start_reading(token=object()))
        is ActionOutcome.ACCEPTED
    )
    boundary = _current_callback(controller, loop_boundary=True)
    before_calls = len(player.calls)
    before_generation = controller.generation
    before_token = controller.state.confirmed_epoch

    first = engine.handle_playback_event(boundary)
    second = engine.handle_playback_event(boundary)

    assert first is ActionOutcome.ACCEPTED
    assert second is ActionOutcome.ACCEPTED
    assert len(player.calls) == before_calls
    assert controller.generation == before_generation
    assert controller.state.confirmed_epoch is before_token
    assert machine.snapshot.activity is PetActivityState.READING


@pytest.mark.parametrize("mismatch", ["generation", "physical_name"])
def test_callback_identity_mismatch_is_stale_and_side_effect_free(
    mismatch: str,
) -> None:
    engine, controller, machine, player = _transaction_engine()
    engine.start_dragging()
    callback = _current_callback(controller)
    if mismatch == "generation":
        callback = replace(callback, generation=callback.generation + 1)
    else:
        callback = replace(callback, physical_name="wrong_binding")
    before_calls = len(player.calls)
    before_epoch = machine.epoch

    outcome = engine.handle_playback_event(callback)

    assert outcome is ActionOutcome.STALE_COMPLETION
    assert len(player.calls) == before_calls
    assert machine.epoch == before_epoch
    assert controller.state.desired_action is PetActionName.DRAG_START


def test_return_idle_commits_semantic_destination_before_playback() -> None:
    engine, controller, machine, player = _transaction_engine()
    assert engine.request_thinking_animation() is ActionOutcome.ACCEPTED
    think_completion = _current_callback(controller)

    return_idle = engine.handle_playback_event(think_completion)

    assert return_idle is ActionOutcome.ACCEPTED
    assert machine.snapshot.activity is PetActivityState.NONE
    assert controller.active_request is not None
    assert controller.active_request.semantic_epoch == machine.epoch == 2
    assert controller.state.desired_action is PetActionName.RETURN_IDLE
    assert player.calls[-1].playback is not None
    assert player.calls[-1].playback.logical_action is PetActionName.RETURN_IDLE
    assert_animation_compatible(
        machine.snapshot,
        controller.state.desired_action,
        controller.state.health,
    )

    idle = engine.handle_playback_event(_current_callback(controller))

    assert idle is ActionOutcome.ACCEPTED
    assert machine.epoch == 2
    assert controller.active_request is not None
    assert controller.active_request.sequence_name.value == "idle"
    desired_after_idle: PetActionName | None = controller.state.desired_action
    assert desired_after_idle is PetActionName.IDLE
    assert_animation_compatible(
        machine.snapshot,
        desired_after_idle,
        controller.state.health,
    )


def test_queued_old_completion_during_drag_is_stale() -> None:
    engine, controller, machine, player = _transaction_engine()
    assert engine.request_thinking_animation() is ActionOutcome.ACCEPTED
    old_completion = _current_callback(controller)
    assert engine.start_dragging() is ActionOutcome.ACCEPTED
    before_calls = len(player.calls)

    outcome = engine.handle_playback_event(old_completion)

    assert outcome is ActionOutcome.STALE_COMPLETION
    assert len(player.calls) == before_calls
    assert machine.snapshot.motion is PetMotionState.DRAGGING
    desired_after_drag: PetActionName | None = controller.state.desired_action
    assert desired_after_drag is PetActionName.DRAG_START


def test_production_one_shot_waits_for_real_completion_callback() -> None:
    engine, controller, machine, _player = _transaction_engine()
    assert engine.request_thinking_animation() is ActionOutcome.ACCEPTED

    engine.advance(10.0, (Rect(0, 0, 800, 600),))

    assert machine.snapshot.activity is PetActivityState.THINKING
    assert controller.state.desired_action is PetActionName.THINK


def test_pause_resume_and_close_use_transaction_boundary() -> None:
    engine, controller, machine, _player = _transaction_engine()
    assert engine.request_walk(engine.motion.state.facing) is ActionOutcome.ACCEPTED

    paused = engine.pause()
    resumed = engine.resume()
    closing = engine.begin_closing()

    assert paused is ActionOutcome.CLEARED
    assert resumed is ActionOutcome.ACCEPTED
    assert closing is ActionOutcome.CLEARED
    assert machine.snapshot.lifecycle.value == "closing"
    assert controller.state.desired_action is None
    assert_animation_compatible(
        machine.snapshot,
        controller.state.desired_action,
        controller.state.health,
    )


def test_clear_does_not_hide_degraded_health_without_reprobe() -> None:
    engine, controller, machine, _player = _transaction_engine(fail_play=True)
    assert (
        engine.handle_event(PetAnimationEvent.start_reading(token=object()))
        is ActionOutcome.PLAYBACK_DEGRADED
    )

    outcome = engine.pause()

    assert outcome is ActionOutcome.CLEARED
    assert machine.snapshot.lifecycle.value == "paused"
    assert controller.state.health is PlaybackHealth.DEGRADED


def test_new_drag_transaction_resets_previous_fall_velocity() -> None:
    engine, _controller, _machine, _player = _transaction_engine(y=100)
    engine.start_dragging()
    engine.release_drag()
    falling = engine.advance(0.1, (Rect(0, 0, 800, 600),)).motion
    assert falling.vertical_velocity > 0

    outcome = engine.start_dragging()

    assert outcome is ActionOutcome.ACCEPTED
    assert engine.motion.snapshot.vertical_velocity == 0


def test_higher_priority_drag_replaces_pending_graceful_exit() -> None:
    engine, controller, machine, player = _transaction_engine()
    engine.handle_event(PetAnimationEvent.start_reading(token=object()))
    old_boundary = _current_callback(controller, loop_boundary=True)
    assert engine.request_graceful_exit() is ActionOutcome.ACCEPTED
    assert controller.runner.snapshot.pending_graceful_exit

    replacement = engine.start_dragging()
    before_calls = len(player.calls)
    stale_boundary = engine.handle_playback_event(old_boundary)

    assert replacement is ActionOutcome.ACCEPTED
    assert stale_boundary is ActionOutcome.STALE_COMPLETION
    assert len(player.calls) == before_calls
    assert not controller.runner.snapshot.pending_graceful_exit
    assert machine.snapshot.motion is PetMotionState.DRAGGING
    assert controller.state.desired_action is PetActionName.DRAG_START


def test_new_request_after_completion_replaces_return_idle() -> None:
    engine, controller, machine, player = _transaction_engine()
    assert engine.request_thinking_animation() is ActionOutcome.ACCEPTED
    think_completion = _current_callback(controller)

    assert engine.handle_playback_event(think_completion) is ActionOutcome.ACCEPTED
    return_idle_completion = _current_callback(controller)
    assert controller.state.desired_action is PetActionName.RETURN_IDLE

    assert engine.start_dragging() is ActionOutcome.ACCEPTED
    before_calls = len(player.calls)
    outcome = engine.handle_playback_event(return_idle_completion)

    assert outcome is ActionOutcome.STALE_COMPLETION
    assert len(player.calls) == before_calls
    assert machine.snapshot.motion is PetMotionState.DRAGGING
    desired_after_drag: PetActionName | None = controller.state.desired_action
    assert desired_after_drag is PetActionName.DRAG_START


def test_duplicate_old_completion_after_replacement_never_advances() -> None:
    engine, controller, machine, player = _transaction_engine()
    engine.request_thinking_animation()
    old_completion = _current_callback(controller)
    engine.start_dragging()
    before_calls = len(player.calls)

    first = engine.handle_playback_event(old_completion)
    second = engine.handle_playback_event(old_completion)

    assert first is second is ActionOutcome.STALE_COMPLETION
    assert len(player.calls) == before_calls
    assert machine.snapshot.motion is PetMotionState.DRAGGING
    assert controller.state.desired_action is PetActionName.DRAG_START
