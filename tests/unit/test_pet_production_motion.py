from __future__ import annotations

from dataclasses import replace

import pytest
from tests.fakes.pet_animation_player import FakeAnimationPlayer, FakePlayerCall

from arkclaw.application.pet.pet_action_sequence import (
    AnimationRegistry,
    PlaybackHealth,
    default_animation_registry,
)
from arkclaw.application.pet.pet_animation import PetAnimationEngine
from arkclaw.application.pet.pet_autonomous_scheduler import AutonomousActionScheduler
from arkclaw.application.pet.pet_geometry import Point, Rect, Size
from arkclaw.application.pet.pet_motion import PetMotionModel
from arkclaw.application.pet.pet_production_actions import (
    ActionSource,
    AutonomousExecutionMode,
    ProductionAction,
)
from arkclaw.application.pet.pet_role_pack import (
    AnimationRoleRegistry,
    RoleAnimationBinding,
    build_track0_animation_registry,
    production_track0_action,
)
from arkclaw.application.pet.pet_state import (
    PetActivityState,
    PetFacing,
    PetLifecycleState,
    PetMotionState,
    PetStateTransitionError,
)
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    PetTrack0Controller,
    PlaybackEvent,
    PlaybackRequest,
)

_WORKSPACE = (Rect(0, 0, 800, 600),)


def _execution_mode(engine: PetAnimationEngine) -> AutonomousExecutionMode:
    return engine.execution_mode


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        return self.value


class _ScriptedRandom:
    def __init__(self) -> None:
        self.uniform_values = [2.0, 4.0, 8.0, 15.0]
        self.range_values = [45]

    def uniform(self, minimum: float, maximum: float) -> float:
        value = self.uniform_values.pop(0)
        assert minimum <= value <= maximum
        return value

    def randrange(
        self,
        start: int,
        stop: int | None = None,
        step: int = 1,
    ) -> int:
        assert stop is None
        assert step == 1
        value = self.range_values.pop(0)
        assert 0 <= value < start
        return value


class _MoveLeftRandom(_ScriptedRandom):
    def __init__(self) -> None:
        self.uniform_values = [2.0, 4.0, 8.0, 4.0, 4.0]
        self.range_values = [75]


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


def test_place_for_render_layout_commits_absolute_position_without_state_change() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(100, 120))
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)
    before = model.state

    snapshot = model.place_for_render_layout(Point(32.0, 480.0), workspace)

    assert snapshot.position == Point(32.0, 480.0)
    assert model.position == Point(32.0, 480.0)
    assert model.state == before
    assert snapshot.state.lifecycle is PetLifecycleState.ACTIVE
    assert snapshot.state.motion is PetMotionState.IDLE
    assert snapshot.state.facing is PetFacing.RIGHT


def test_place_for_render_layout_preserves_vertical_position() -> None:
    model = PetMotionModel(Point(1760.0, 700.0), Size(160, 180))
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    snapshot = model.place_for_render_layout(Point(1728.0, 700.0), workspace)

    assert snapshot.position == Point(1728.0, 700.0)
    assert model.position.y == 700.0


def test_place_for_render_layout_accepts_window_grounded_on_workspace_bottom() -> None:
    model = PetMotionModel(Point(0.0, 700.0), Size(160, 180))
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    snapshot = model.place_for_render_layout(Point(32.0, 700.0), workspace)

    assert snapshot.position == Point(32.0, 700.0)


def test_grounded_action_change_cannot_change_world_y() -> None:
    engine, _controller, _player = _engine()
    ground_y = engine.motion.position.y

    for action in (
        ProductionAction.RELAX,
        ProductionAction.SIT,
        ProductionAction.MOVE_RIGHT,
        ProductionAction.RELAX,
    ):
        assert engine.request_action(action, ActionSource.USER) is ActionOutcome.ACCEPTED
        assert engine.motion.position.y == ground_y


def test_grounded_action_change_cannot_change_window_y() -> None:
    engine, _controller, _player = _engine()
    window_y = engine.motion.position.y

    for action in (
        ProductionAction.RELAX,
        ProductionAction.SIT,
        ProductionAction.MOVE_RIGHT,
        ProductionAction.RELAX,
    ):
        assert engine.request_action(action, ActionSource.USER) is ActionOutcome.ACCEPTED
        frame = engine.advance(1.0 / 60.0, _WORKSPACE)
        assert frame.motion.position.y == window_y


def test_place_for_render_layout_allows_special_activity_while_idle() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(160, 180))
    model.commit_state_transition(
        model.states.propose(activity=PetActivityState.SPECIAL)
    )
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    snapshot = model.place_for_render_layout(Point(32.0, 480.0), workspace)

    assert snapshot.state.activity is PetActivityState.SPECIAL
    assert snapshot.state.motion is PetMotionState.IDLE
    assert snapshot.position == Point(32.0, 480.0)


def test_place_for_render_layout_rejects_non_idle_motion_without_mutation() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(160, 180))
    model.start_dragging()
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    with pytest.raises(PetStateTransitionError):
        model.place_for_render_layout(Point(32.0, 480.0), workspace)

    assert model.position == Point(0.0, 480.0)


def test_place_for_render_layout_rejects_paused_lifecycle_without_mutation() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(160, 180))
    model.pause()
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    with pytest.raises(PetStateTransitionError):
        model.place_for_render_layout(Point(32.0, 480.0), workspace)

    assert model.position == Point(0.0, 480.0)


def test_place_for_render_layout_rejects_vertical_change_without_mutation() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(160, 180))
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    with pytest.raises(ValueError):
        model.place_for_render_layout(Point(32.0, 500.0), workspace)

    assert model.position == Point(0.0, 480.0)


def test_place_for_render_layout_rejects_out_of_workspace_without_mutation() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(160, 180))
    workspace = Rect(100.0, 0.0, 1920.0, 880.0)

    with pytest.raises(ValueError):
        model.place_for_render_layout(Point(0.0, 480.0), workspace)

    assert model.position == Point(0.0, 480.0)


def test_place_for_render_layout_rejects_non_finite_position_without_mutation() -> None:
    model = PetMotionModel(Point(0.0, 480.0), Size(160, 180))
    workspace = Rect(0.0, 0.0, 1920.0, 880.0)

    with pytest.raises(ValueError):
        model.place_for_render_layout(Point(float("nan"), 480.0), workspace)

    assert model.position == Point(0.0, 480.0)


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


def test_explicit_move_boundary_recovers_through_relax_and_autonomy() -> None:
    engine, controller, player = _engine(x=0.0)
    assert (
        engine.request_action(ProductionAction.MOVE_LEFT, ActionSource.USER)
        is ActionOutcome.ACCEPTED
    )
    old_generation = controller.generation

    snapshot = engine.advance(0.1, _WORKSPACE)

    assert snapshot.motion.position.x == 0.0
    assert snapshot.motion.state.motion is PetMotionState.IDLE
    assert snapshot.motion.state.facing is PetFacing.LEFT
    assert snapshot.motion.horizontal_velocity == 0.0
    assert controller.generation > old_generation
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"
    assert _execution_mode(engine) is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert engine.autonomous_scheduler_state.dwell_target_seconds is not None
    played = [call.playback for call in player.calls if call.playback is not None]
    assert [request.physical_name for request in played] == ["Move", "Relax"]


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


def test_native_relax_loop_boundary_commits_one_autonomous_transaction() -> None:
    player = FakeAnimationPlayer()
    controller = PetTrack0Controller(player=player, registry=_registry())
    clock = _Clock()
    engine = PetAnimationEngine(
        PetMotionModel(Point(100.0, 480.0), Size(100, 120)),
        rng=_ScriptedRandom(),  # type: ignore[arg-type]
        track0=controller,
        autonomous_scheduler=AutonomousActionScheduler(),
        clock=clock,
    )
    assert engine.start_autonomous() is ActionOutcome.ACCEPTED
    relax_epoch = controller.state.confirmed_epoch
    assert relax_epoch is not None
    clock.value = 108.0

    outcome = engine.handle_playback_event(
        PlaybackEvent(
            generation=relax_epoch.generation,
            logical_action=relax_epoch.logical_action,
            physical_name=relax_epoch.physical_name,
            playback_token=relax_epoch.playback_token,
            loop_boundary=True,
            boundary_index=1,
        )
    )

    assert outcome is ActionOutcome.ACCEPTED
    assert engine.motion.state.activity.value == "sitting"
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Sit"
    assert engine.autonomous_scheduler_state is not None
    assert engine.autonomous_scheduler_state.last_committed_state.value == "sit"
    assert _execution_mode(engine) is AutonomousExecutionMode.AUTONOMOUS


def test_missing_drag_animations_use_relax_and_recover_autonomy() -> None:
    player = FakeAnimationPlayer()
    controller = PetTrack0Controller(player=player, registry=_registry())
    engine = PetAnimationEngine(
        PetMotionModel(Point(100.0, 480.0), Size(100, 120)),
        track0=controller,
        autonomous_scheduler=AutonomousActionScheduler(),
        clock=_Clock(),
        use_relax_motion_fallback=True,
    )
    assert engine.start_autonomous() is ActionOutcome.ACCEPTED
    assert (
        engine.request_action(ProductionAction.SLEEP, ActionSource.USER)
        is ActionOutcome.ACCEPTED
    )

    assert engine.start_dragging() is ActionOutcome.ACCEPTED
    assert engine.motion.state.motion is PetMotionState.DRAGGING
    assert engine.execution_mode is AutonomousExecutionMode.SUSPENDED
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"
    drag_relax_epoch = controller.state.confirmed_epoch
    drag_relax_calls = tuple(player.calls)
    assert player.calls[-1].playback is not None
    assert player.calls[-1].playback.loop

    engine.motion.drag_to(Point(-500.0, 650.0), _WORKSPACE)
    assert engine.release_drag(_WORKSPACE) is ActionOutcome.ACCEPTED
    released = engine.motion.snapshot
    assert released.position == Point(0.0, 480.0)
    assert released.state.motion is PetMotionState.LANDING

    engine.advance(0.1, _WORKSPACE)
    settled = engine.advance(0.1, _WORKSPACE)

    assert settled.motion.state.motion is PetMotionState.IDLE
    assert settled.motion.horizontal_velocity == 0.0
    assert settled.motion.vertical_velocity == 0.0
    assert _execution_mode(engine) is AutonomousExecutionMode.AUTONOMOUS
    assert engine.autonomous_scheduler_state is not None
    assert controller.state.confirmed_epoch is not None
    assert controller.state.confirmed_epoch.physical_name == "Relax"
    assert controller.state.confirmed_epoch is drag_relax_epoch
    assert tuple(player.calls) == drag_relax_calls
    assert (
        engine.request_action(ProductionAction.SPECIAL, ActionSource.USER)
        is ActionOutcome.ACCEPTED
    )


def test_autonomous_move_boundary_turns_opposite_without_relax() -> None:
    player = FakeAnimationPlayer()
    controller = PetTrack0Controller(player=player, registry=_registry())
    clock = _Clock()
    engine = PetAnimationEngine(
        PetMotionModel(Point(0.0, 480.0), Size(100, 120)),
        rng=_MoveLeftRandom(),  # type: ignore[arg-type]
        track0=controller,
        autonomous_scheduler=AutonomousActionScheduler(),
        clock=clock,
    )
    assert engine.start_autonomous() is ActionOutcome.ACCEPTED
    relax_epoch = controller.state.confirmed_epoch
    assert relax_epoch is not None
    clock.value = 108.0
    assert (
        engine.handle_playback_event(
            PlaybackEvent(
                generation=relax_epoch.generation,
                logical_action=relax_epoch.logical_action,
                physical_name=relax_epoch.physical_name,
                playback_token=relax_epoch.playback_token,
                loop_boundary=True,
                boundary_index=1,
            )
        )
        is ActionOutcome.ACCEPTED
    )

    turned = engine.advance(0.1, _WORKSPACE)

    assert turned.motion.position.x == 0.0
    assert turned.motion.state.motion is PetMotionState.WALKING_RIGHT
    assert turned.motion.state.facing is PetFacing.RIGHT
    assert turned.motion.horizontal_velocity > 0.0
    assert _execution_mode(engine) is AutonomousExecutionMode.AUTONOMOUS
    played = [call.playback for call in player.calls if call.playback is not None]
    assert [request.physical_name for request in played] == [
        "Relax",
        "Move",
        "Move",
    ]
