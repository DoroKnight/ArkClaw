from __future__ import annotations

from dataclasses import replace

from tests.fakes.pet_animation_player import FakeAnimationPlayer

from sjtuclaw.application.pet_action_sequence import (
    AnimationRegistry,
    default_animation_registry,
)
from sjtuclaw.application.pet_animation import PetAnimationEngine, PetAnimationEvent
from sjtuclaw.application.pet_autonomous_scheduler import AutonomousActionScheduler
from sjtuclaw.application.pet_geometry import Point, Size
from sjtuclaw.application.pet_motion import PetMotionModel
from sjtuclaw.application.pet_production_actions import (
    ActionSource,
    AutonomousExecutionMode,
    ProductionAction,
)
from sjtuclaw.application.pet_role_pack import (
    AnimationRoleRegistry,
    RoleAnimationBinding,
    build_track0_animation_registry,
    production_track0_action,
)
from sjtuclaw.application.pet_state import (
    PetActivityState,
    PetLayeredStateMachine,
)
from sjtuclaw.application.pet_track0 import (
    ActionOutcome,
    PetTrack0Controller,
    PlaybackEvent,
)


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.value = now

    def now(self) -> float:
        return self.value


def _registry() -> AnimationRegistry:
    roles = AnimationRoleRegistry(
        {
            action: RoleAnimationBinding(
                action,
                "Move"
                if action in {ProductionAction.MOVE_LEFT, ProductionAction.MOVE_RIGHT}
                else action.value.title(),
                mirrored=action is ProductionAction.MOVE_LEFT,
            )
            for action in ProductionAction
        }
    )
    production = build_track0_animation_registry(
        roles,
        source_durations={action: 1.0 for action in ProductionAction},
    )
    legacy = default_animation_registry()
    production_actions = {
        production_track0_action(action) for action in ProductionAction
    }
    return AnimationRegistry(
        {
            action: (
                production.resolve(action)
                if action in production_actions
                else replace(legacy.resolve(action), source_duration_seconds=1.0)
            )
            for action in legacy.actions
        }
    )


def _engine() -> tuple[
    PetAnimationEngine,
    PetTrack0Controller,
    PetLayeredStateMachine,
    FakeAnimationPlayer,
]:
    machine = PetLayeredStateMachine()
    player = FakeAnimationPlayer()
    controller = PetTrack0Controller(player=player, registry=_registry())
    engine = PetAnimationEngine(
        PetMotionModel(Point(100, 480), Size(100, 120), states=machine),
        track0=controller,
        autonomous_scheduler=AutonomousActionScheduler(),
        clock=_Clock(),
    )
    return engine, controller, machine, player


def _callback(controller: PetTrack0Controller) -> PlaybackEvent:
    confirmed = controller.state.confirmed_epoch
    assert confirmed is not None
    return PlaybackEvent(
        generation=confirmed.generation,
        logical_action=confirmed.logical_action,
        physical_name=confirmed.physical_name,
        playback_token=confirmed.playback_token,
    )


def test_explicit_loop_enters_hold_and_boundaries_do_not_restart() -> None:
    engine, controller, _machine, player = _engine()
    assert (
        engine.request_action(ProductionAction.RELAX, ActionSource.TRAY)
        is ActionOutcome.ACCEPTED
    )
    confirmed = controller.state.confirmed_epoch
    assert confirmed is not None
    calls = len(player.calls)

    outcome = engine.handle_playback_event(
        replace(_callback(controller), loop_boundary=True)
    )

    assert outcome is ActionOutcome.ACCEPTED
    assert engine.execution_mode is AutonomousExecutionMode.EXPLICIT_HOLD
    assert controller.state.confirmed_epoch is confirmed
    assert len(player.calls) == calls


def test_same_held_action_is_an_accepted_idempotent_no_op() -> None:
    engine, controller, _machine, player = _engine()
    engine.request_action(ProductionAction.SLEEP, ActionSource.USER)
    confirmed = controller.state.confirmed_epoch
    generation = controller.generation
    calls = len(player.calls)

    outcome = engine.request_action(ProductionAction.SLEEP, ActionSource.AGENT)

    assert outcome is ActionOutcome.ACCEPTED
    assert controller.generation == generation
    assert controller.state.confirmed_epoch is confirmed
    assert len(player.calls) == calls


def test_new_explicit_loop_replaces_hold() -> None:
    engine, controller, machine, _player = _engine()
    engine.request_action(ProductionAction.RELAX, ActionSource.USER)
    old_generation = controller.generation

    outcome = engine.request_action(ProductionAction.SIT, ActionSource.USER)

    assert outcome is ActionOutcome.ACCEPTED
    assert controller.generation > old_generation
    assert machine.snapshot.activity is PetActivityState.SITTING
    assert engine.execution_mode is AutonomousExecutionMode.EXPLICIT_HOLD


def test_resume_autonomous_establishes_fresh_confirmed_relax_dwell() -> None:
    engine, controller, machine, _player = _engine()
    engine.request_action(ProductionAction.SLEEP, ActionSource.USER)

    outcome = engine.resume_autonomous(ActionSource.TRAY)

    assert outcome is ActionOutcome.ACCEPTED
    assert engine.execution_mode is AutonomousExecutionMode.AUTONOMOUS
    assert machine.snapshot.activity is PetActivityState.NONE
    assert engine.autonomous_scheduler_state is not None
    assert engine.autonomous_scheduler_state.dwell_target_seconds is not None
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"


def test_latest_pending_explicit_is_consumed_once_with_fresh_epoch() -> None:
    engine, controller, machine, player = _engine()
    engine.request_action(ProductionAction.SPECIAL, ActionSource.USER)
    protected_epoch = machine.epoch
    completion = _callback(controller)
    assert engine.request_action(ProductionAction.SIT, ActionSource.TRAY) is ActionOutcome.ACCEPTED
    assert (
        engine.request_action(ProductionAction.SLEEP, ActionSource.AGENT)
        is ActionOutcome.ACCEPTED
    )
    assert engine.pending_explicit_action is not None
    assert engine.pending_explicit_action.action is ProductionAction.SLEEP

    outcome = engine.handle_playback_event(completion)
    calls_after_consumption = len(player.calls)
    duplicate = engine.handle_playback_event(completion)

    assert outcome is ActionOutcome.ACCEPTED
    assert duplicate is ActionOutcome.STALE_COMPLETION
    assert machine.epoch == protected_epoch + 1
    assert machine.snapshot.activity is PetActivityState.SLEEPING
    assert engine.execution_mode is AutonomousExecutionMode.EXPLICIT_HOLD
    assert engine.pending_explicit_action is None
    assert len(player.calls) == calls_after_consumption


def test_resume_during_protected_completion_returns_to_autonomous_relax() -> None:
    engine, controller, _machine, _player = _engine()
    engine.request_action(ProductionAction.INTERACT, ActionSource.USER)
    completion = _callback(controller)

    assert engine.resume_autonomous(ActionSource.USER) is ActionOutcome.ACCEPTED
    assert engine.resume_after_protected
    assert engine.handle_playback_event(completion) is ActionOutcome.ACCEPTED
    assert not engine.resume_after_protected
    assert engine.execution_mode is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"


def _assert_mandatory_interrupt_clears_continuation(interrupt: str) -> None:
    engine, _controller, _machine, _player = _engine()
    engine.request_action(ProductionAction.SPECIAL, ActionSource.USER)
    engine.resume_autonomous(ActionSource.USER)
    assert engine.resume_after_protected

    if interrupt == "safety":
        engine.handle_event(PetAnimationEvent.start_falling())
    elif interrupt == "drag":
        engine.start_dragging()
    elif interrupt == "pause":
        engine.pause()
    else:
        engine.begin_closing()

    assert engine.pending_explicit_action is None
    assert not engine.resume_after_protected
    assert engine.execution_mode is AutonomousExecutionMode.SUSPENDED


def test_safety_interrupt_clears_resume_after_protected() -> None:
    _assert_mandatory_interrupt_clears_continuation("safety")


def test_drag_interrupt_clears_resume_after_protected() -> None:
    _assert_mandatory_interrupt_clears_continuation("drag")


def test_pause_interrupt_clears_resume_after_protected() -> None:
    _assert_mandatory_interrupt_clears_continuation("pause")


def test_shutdown_clears_resume_after_protected() -> None:
    _assert_mandatory_interrupt_clears_continuation("shutdown")


def test_safety_completion_recovers_through_confirmed_relax() -> None:
    engine, controller, machine, _player = _engine()
    engine.request_action(ProductionAction.SLEEP, ActionSource.USER)
    assert engine.handle_event(PetAnimationEvent.start_falling()) is ActionOutcome.ACCEPTED

    outcome = engine.handle_playback_event(_callback(controller))

    assert outcome is ActionOutcome.ACCEPTED
    assert machine.snapshot.activity is PetActivityState.NONE
    assert engine.execution_mode is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"


def test_drag_release_completion_recovers_through_confirmed_relax() -> None:
    engine, controller, machine, _player = _engine()
    engine.request_action(ProductionAction.SLEEP, ActionSource.USER)
    assert engine.start_dragging() is ActionOutcome.ACCEPTED
    assert engine.handle_playback_event(_callback(controller)) is ActionOutcome.ACCEPTED
    assert engine.release_drag() is ActionOutcome.ACCEPTED

    outcome = engine.handle_playback_event(_callback(controller))

    assert outcome is ActionOutcome.ACCEPTED
    assert machine.snapshot.activity is PetActivityState.NONE
    assert engine.execution_mode is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"


def test_application_resume_recovers_through_confirmed_relax() -> None:
    engine, controller, machine, _player = _engine()
    engine.request_action(ProductionAction.SLEEP, ActionSource.USER)
    assert engine.pause() is ActionOutcome.CLEARED

    outcome = engine.resume()

    assert outcome is ActionOutcome.ACCEPTED
    assert machine.snapshot.activity is PetActivityState.NONE
    assert engine.execution_mode is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"
