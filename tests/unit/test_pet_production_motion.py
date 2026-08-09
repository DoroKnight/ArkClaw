from __future__ import annotations

from dataclasses import replace

from tests.fakes.pet_animation_player import FakeAnimationPlayer, FakePlayerCall

from sjtuclaw.application.pet_action_sequence import (
    AnimationRegistry,
    PlaybackHealth,
    default_animation_registry,
)
from sjtuclaw.application.pet_animation import PetAnimationEngine
from sjtuclaw.application.pet_autonomous_scheduler import AutonomousActionScheduler
from sjtuclaw.application.pet_geometry import Point, Rect, Size
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
from sjtuclaw.application.pet_state import PetFacing, PetMotionState
from sjtuclaw.application.pet_track0 import (
    ActionOutcome,
    PetTrack0Controller,
    PlaybackRequest,
)

_WORKSPACE = (Rect(0, 0, 800, 600),)


class _Clock:
    def now(self) -> float:
        return 100.0


class _FailSecondPlay(FakeAnimationPlayer):
    def __init__(self) -> None:
        super().__init__()
        self._plays = 0

    def play(self, request: PlaybackRequest) -> object:
        self._plays += 1
        if self._plays == 2:
            self.calls.append(
                FakePlayerCall(
                    generation=request.generation,
                    operation="play",
                    playback=request,
                )
            )
            raise RuntimeError("injected second play failure")
        return super().play(request)


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


def _engine(
    *,
    x: float = 100.0,
    player: FakeAnimationPlayer | None = None,
) -> tuple[PetAnimationEngine, PetTrack0Controller, FakeAnimationPlayer]:
    selected = player or FakeAnimationPlayer()
    controller = PetTrack0Controller(player=selected, registry=_registry())
    engine = PetAnimationEngine(
        PetMotionModel(Point(x, 480), Size(100, 120)),
        track0=controller,
        autonomous_scheduler=AutonomousActionScheduler(),
        clock=_Clock(),
    )
    return engine, controller, selected


def test_move_alias_commits_facing_velocity_and_physical_playback() -> None:
    engine, controller, player = _engine()

    outcome = engine.request_action(ProductionAction.MOVE_LEFT, ActionSource.USER)
    moved = engine.advance(0.1, _WORKSPACE)

    assert outcome is ActionOutcome.ACCEPTED
    assert moved.motion.state.motion is PetMotionState.WALKING_LEFT
    assert moved.motion.state.facing is PetFacing.LEFT
    assert moved.motion.horizontal_velocity < 0.0
    assert moved.motion.position.x < 100.0
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Move"
    assert player.calls[-1].playback is not None
    assert player.calls[-1].playback.physical_name == "Move"

    assert engine.request_action(ProductionAction.SIT, ActionSource.USER) is ActionOutcome.ACCEPTED
    assert engine.motion.snapshot.horizontal_velocity == 0.0


def test_mid_loop_boundary_turn_restarts_opposite_move_and_autonomy() -> None:
    engine, controller, player = _engine(x=0.0)
    assert (
        engine.request_action(ProductionAction.MOVE_LEFT, ActionSource.USER)
        is ActionOutcome.ACCEPTED
    )
    old_generation = controller.generation

    snapshot = engine.advance(0.1, _WORKSPACE)

    assert snapshot.motion.position.x == 0.0
    assert snapshot.motion.state.motion is PetMotionState.WALKING_RIGHT
    assert snapshot.motion.state.facing is PetFacing.RIGHT
    assert snapshot.motion.horizontal_velocity > 0.0
    assert controller.generation > old_generation
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Move"
    assert engine.execution_mode is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert engine.autonomous_scheduler_state.dwell_target_seconds is not None
    played = [call.playback for call in player.calls if call.playback is not None]
    assert [request.physical_name for request in played] == ["Move", "Move"]


def test_failed_boundary_turn_stops_and_contains_in_relax_suspended() -> None:
    player = _FailSecondPlay()
    engine, controller, _selected = _engine(x=0.0, player=player)
    assert (
        engine.request_action(ProductionAction.MOVE_LEFT, ActionSource.USER)
        is ActionOutcome.ACCEPTED
    )

    snapshot = engine.advance(0.1, _WORKSPACE)

    assert snapshot.motion.state.motion is PetMotionState.IDLE
    assert snapshot.motion.horizontal_velocity == 0.0
    assert controller.state.health is PlaybackHealth.DEGRADED
    assert controller.state.confirmed_epoch is None
    assert engine.execution_mode is AutonomousExecutionMode.SUSPENDED
