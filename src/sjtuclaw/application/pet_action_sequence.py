"""Immutable action vocabulary, sequence catalog, and animation bindings.

Provenance: this is an independent Python rewrite informed by the ArkPets
project by Harry Huang (GPL-3.0), specifically ``AnimData.java``,
``AnimComposer.java``, ``AnimClipGroup.java``, and ``AnimClip.java`` under
``core/src/cn/harryh/arkpets/animations``. No ArkPets Java source or comments,
character assets, mobility logic, root-motion ownership, or stochastic
behavior matrix are vendored or reproduced here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum
from types import MappingProxyType


class PetActionName(StrEnum):
    """Logical animation names shared by the application and Spine asset."""

    IDLE = "idle"
    BREATHING = "breathing"
    BLINK = "blink"
    WALK_LEFT = "walk_left"
    WALK_RIGHT = "walk_right"
    RUN_LEFT = "run_left"
    RUN_RIGHT = "run_right"
    SIT_DOWN = "sit_down"
    SIT_IDLE = "sit_idle"
    SLEEP_START = "sleep_start"
    SLEEP_LOOP = "sleep_loop"
    SLEEP_END = "sleep_end"
    WAVE = "wave"
    HAPPY = "happy"
    THINK = "think"
    READ = "read"
    TYPE = "type"
    REMIND = "remind"
    CONFUSED = "confused"
    ANGRY = "angry"
    DRAG_START = "drag_start"
    DRAG_LOOP = "drag_loop"
    DRAG_END = "drag_end"
    LANDING = "landing"
    RETURN_IDLE = "return_idle"


class SequenceName(StrEnum):
    """Named application-level action sequences."""

    IDLE = "idle"
    BREATHING = "breathing"
    BLINK = "blink"
    WALK_LEFT = "walk_left"
    WALK_RIGHT = "walk_right"
    RUN_LEFT = "run_left"
    RUN_RIGHT = "run_right"
    SIT = "sit"
    SLEEP = "sleep"
    WAVE = "wave"
    HAPPY = "happy"
    THINK = "think"
    READ = "read"
    TYPE = "type"
    REMIND = "remind"
    CONFUSED = "confused"
    ANGRY = "angry"
    DRAG_HOLD = "drag_hold"
    DRAG_RELEASE = "drag_release"
    FALL_RECOVERY = "fall_recovery"
    LANDING = "landing"
    PRODUCTION_RELAX = "production_relax"
    PRODUCTION_MOVE_LEFT = "production_move_left"
    PRODUCTION_MOVE_RIGHT = "production_move_right"
    PRODUCTION_SIT = "production_sit"
    PRODUCTION_SLEEP = "production_sleep"
    PRODUCTION_SPECIAL = "production_special"
    PRODUCTION_INTERACT = "production_interact"


class SequenceTerminal(StrEnum):
    """Behavior after the final sequence step completes."""

    COMPLETE = "complete"
    HOLD = "hold"
    IDLE = "idle"


class InterruptClass(IntEnum):
    """Fixed request priority classes; higher values outrank lower values."""

    IDLE = 0
    NORMAL_ACTION = 100
    STRICT_ACTION = 200
    USER_INTERACTION = 300
    MOTION_SAFETY = 400
    SYSTEM_SHUTDOWN = 500


class PlaybackHealth(StrEnum):
    """How confidently the application knows the renderer's Track 0 state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PetActionStep:
    """One immutable playback instruction inside a sequence."""

    action: PetActionName
    loop: bool
    speed: float = 1.0
    mix_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.speed <= 0:
            raise ValueError("speed must be positive")
        if self.mix_seconds is not None and self.mix_seconds < 0:
            raise ValueError("mix_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class PetActionSequence:
    """Ordered steps plus the sole loop and terminal control metadata."""

    steps: tuple[PetActionStep, ...]
    loop_index: int | None = None
    loop_exit_index: int | None = None
    terminal: SequenceTerminal = SequenceTerminal.COMPLETE

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("a sequence must contain at least one step")
        if self.loop_index is None:
            if self.loop_exit_index is not None:
                raise ValueError("a loop exit requires a loop")
            return
        if not 0 <= self.loop_index < len(self.steps):
            raise ValueError("loop_index is out of range")
        if not self.steps[self.loop_index].loop:
            raise ValueError("loop_index must identify a looping step")
        if self.loop_exit_index is not None and not (0 <= self.loop_exit_index < len(self.steps)):
            raise ValueError("loop_exit_index is out of range")

    def then(self, step: PetActionStep) -> PetActionSequence:
        """Return a new sequence with ``step`` appended."""

        return replace(self, steps=(*self.steps, step))


@dataclass(frozen=True, slots=True)
class SequenceCatalogEntry:
    """A standard sequence and its stable request policy."""

    track: int
    sequence: PetActionSequence
    interruption_class: InterruptClass
    protected: bool = False

    def __post_init__(self) -> None:
        if self.track not in {0, 1, 2}:
            raise ValueError("track must be 0, 1, or 2")
        if self.interruption_class is InterruptClass.STRICT_ACTION and not self.protected:
            raise ValueError("strict actions must be protected")


def _step(action: PetActionName, *, loop: bool = False) -> PetActionStep:
    return PetActionStep(action=action, loop=loop)


def _entry(
    track: int,
    steps: tuple[PetActionStep, ...],
    interruption_class: InterruptClass,
    *,
    loop_index: int | None = None,
    loop_exit_index: int | None = None,
    terminal: SequenceTerminal = SequenceTerminal.COMPLETE,
    protected: bool = False,
) -> SequenceCatalogEntry:
    return SequenceCatalogEntry(
        track=track,
        sequence=PetActionSequence(
            steps,
            loop_index=loop_index,
            loop_exit_index=loop_exit_index,
            terminal=terminal,
        ),
        interruption_class=interruption_class,
        protected=protected,
    )


_RETURN_IDLE = _step(PetActionName.RETURN_IDLE)


SEQUENCE_CATALOG: Mapping[SequenceName, SequenceCatalogEntry] = MappingProxyType(
    {
        SequenceName.IDLE: _entry(
            0,
            (_step(PetActionName.IDLE, loop=True),),
            InterruptClass.IDLE,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.BREATHING: _entry(
            1,
            (_step(PetActionName.BREATHING, loop=True),),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.BLINK: _entry(
            2,
            (_step(PetActionName.BLINK),),
            InterruptClass.NORMAL_ACTION,
        ),
        SequenceName.WALK_LEFT: _entry(
            0,
            (_step(PetActionName.WALK_LEFT, loop=True), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            loop_exit_index=1,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.WALK_RIGHT: _entry(
            0,
            (_step(PetActionName.WALK_RIGHT, loop=True), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            loop_exit_index=1,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.RUN_LEFT: _entry(
            0,
            (_step(PetActionName.RUN_LEFT, loop=True), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            loop_exit_index=1,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.RUN_RIGHT: _entry(
            0,
            (_step(PetActionName.RUN_RIGHT, loop=True), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            loop_exit_index=1,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.SIT: _entry(
            0,
            (
                _step(PetActionName.SIT_DOWN),
                _step(PetActionName.SIT_IDLE, loop=True),
                _RETURN_IDLE,
            ),
            InterruptClass.NORMAL_ACTION,
            loop_index=1,
            loop_exit_index=2,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.SLEEP: _entry(
            0,
            (
                _step(PetActionName.SLEEP_START),
                _step(PetActionName.SLEEP_LOOP, loop=True),
                _step(PetActionName.SLEEP_END),
                _RETURN_IDLE,
            ),
            InterruptClass.NORMAL_ACTION,
            loop_index=1,
            loop_exit_index=2,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.WAVE: _entry(
            0,
            (_step(PetActionName.WAVE), _RETURN_IDLE),
            InterruptClass.STRICT_ACTION,
            terminal=SequenceTerminal.IDLE,
            protected=True,
        ),
        SequenceName.HAPPY: _entry(
            0,
            (_step(PetActionName.HAPPY), _RETURN_IDLE),
            InterruptClass.STRICT_ACTION,
            terminal=SequenceTerminal.IDLE,
            protected=True,
        ),
        SequenceName.THINK: _entry(
            0,
            (_step(PetActionName.THINK), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.READ: _entry(
            0,
            (_step(PetActionName.READ, loop=True), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            loop_exit_index=1,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.TYPE: _entry(
            0,
            (_step(PetActionName.TYPE, loop=True), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            loop_exit_index=1,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.REMIND: _entry(
            0,
            (_step(PetActionName.REMIND), _RETURN_IDLE),
            InterruptClass.NORMAL_ACTION,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.CONFUSED: _entry(
            0,
            (_step(PetActionName.CONFUSED), _RETURN_IDLE),
            InterruptClass.STRICT_ACTION,
            terminal=SequenceTerminal.IDLE,
            protected=True,
        ),
        SequenceName.ANGRY: _entry(
            0,
            (_step(PetActionName.ANGRY), _RETURN_IDLE),
            InterruptClass.STRICT_ACTION,
            terminal=SequenceTerminal.IDLE,
            protected=True,
        ),
        SequenceName.DRAG_HOLD: _entry(
            0,
            (
                _step(PetActionName.DRAG_START),
                _step(PetActionName.DRAG_LOOP, loop=True),
            ),
            InterruptClass.USER_INTERACTION,
            loop_index=1,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.DRAG_RELEASE: _entry(
            0,
            (_step(PetActionName.DRAG_END),),
            InterruptClass.USER_INTERACTION,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.FALL_RECOVERY: _entry(
            0,
            (_step(PetActionName.DRAG_END),),
            InterruptClass.MOTION_SAFETY,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.LANDING: _entry(
            0,
            (_step(PetActionName.LANDING), _RETURN_IDLE),
            InterruptClass.MOTION_SAFETY,
            terminal=SequenceTerminal.IDLE,
        ),
        SequenceName.PRODUCTION_RELAX: _entry(
            0,
            (_step(PetActionName.IDLE, loop=True),),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.PRODUCTION_MOVE_LEFT: _entry(
            0,
            (_step(PetActionName.WALK_LEFT, loop=True),),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.PRODUCTION_MOVE_RIGHT: _entry(
            0,
            (_step(PetActionName.WALK_RIGHT, loop=True),),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.PRODUCTION_SIT: _entry(
            0,
            (_step(PetActionName.SIT_IDLE, loop=True),),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.PRODUCTION_SLEEP: _entry(
            0,
            (_step(PetActionName.SLEEP_LOOP, loop=True),),
            InterruptClass.NORMAL_ACTION,
            loop_index=0,
            terminal=SequenceTerminal.HOLD,
        ),
        SequenceName.PRODUCTION_SPECIAL: _entry(
            0,
            (_step(PetActionName.WAVE),),
            InterruptClass.STRICT_ACTION,
            protected=True,
        ),
        SequenceName.PRODUCTION_INTERACT: _entry(
            0,
            (_step(PetActionName.HAPPY),),
            InterruptClass.STRICT_ACTION,
            protected=True,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class AnimationBinding:
    """Map one logical action to its case-sensitive renderer name."""

    action: PetActionName
    physical_name: str
    track: int
    source_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.physical_name:
            raise ValueError("physical_name must not be empty")
        if self.track not in {0, 1, 2}:
            raise ValueError("track must be 0, 1, or 2")
        if self.source_duration_seconds is not None and self.source_duration_seconds <= 0:
            raise ValueError("source duration must be positive")


class AnimationRegistryError(ValueError):
    """Raised when animation bindings violate the frozen registry contract."""


class AnimationRegistry:
    """Validated immutable logical-to-physical animation bindings."""

    def __init__(self, bindings: Mapping[PetActionName, AnimationBinding]) -> None:
        copied = dict(bindings)
        if set(copied) != set(PetActionName):
            raise AnimationRegistryError("registry must bind every logical action")
        if any(action is not binding.action for action, binding in copied.items()):
            raise AnimationRegistryError("registry keys must match binding actions")
        actions_by_physical: dict[str, set[PetActionName]] = {}
        for action, binding in copied.items():
            actions_by_physical.setdefault(binding.physical_name, set()).add(action)
        allowed_alias = {PetActionName.WALK_LEFT, PetActionName.WALK_RIGHT}
        if any(
            len(actions) > 1 and actions != allowed_alias
            for actions in actions_by_physical.values()
        ):
            raise AnimationRegistryError("physical animation names must be unique")
        for action, binding in copied.items():
            expected_track = _expected_track(action)
            if binding.track != expected_track:
                raise AnimationRegistryError("animation binding has an invalid track")
        self._bindings: Mapping[PetActionName, AnimationBinding] = MappingProxyType(copied)

    @property
    def actions(self) -> tuple[PetActionName, ...]:
        return tuple(self._bindings)

    def resolve(self, action: PetActionName) -> AnimationBinding:
        return self._bindings[action]

    def validate_loaded_names(self, loaded_names: Iterable[str]) -> None:
        available = frozenset(loaded_names)
        if any(binding.physical_name not in available for binding in self._bindings.values()):
            raise AnimationRegistryError("a required animation is not loaded")

    def validate_track_sequence(
        self,
        track: int,
        sequence: PetActionSequence,
    ) -> None:
        if track not in {0, 1, 2}:
            raise AnimationRegistryError("sequence track is invalid")
        if any(self.resolve(step.action).track != track for step in sequence.steps):
            raise AnimationRegistryError("sequence contains an action for another track")

    def validate_sequence(
        self,
        entry: SequenceCatalogEntry,
        *,
        require_duration_metadata: bool,
    ) -> None:
        self.validate_track_sequence(entry.track, entry.sequence)
        if require_duration_metadata and any(
            self.resolve(step.action).source_duration_seconds is None
            for step in entry.sequence.steps
        ):
            raise AnimationRegistryError("source duration metadata is required")


def _expected_track(action: PetActionName) -> int:
    if action is PetActionName.BREATHING:
        return 1
    if action is PetActionName.BLINK:
        return 2
    return 0


def default_animation_registry() -> AnimationRegistry:
    """Build the exact case-sensitive identity registry for the approved asset."""

    return AnimationRegistry(
        {
            action: AnimationBinding(
                action=action,
                physical_name=action.value,
                track=_expected_track(action),
            )
            for action in PetActionName
        }
    )
