"""Narrow presentation-neutral Command Descriptor Adapter (Slice 5A).

Authority: 08 §14.1 (Slice 5A), 07 §19, 06 §9.2, 09 §18.

This module adapts the *existing* authoritative command/action source into
minimal, immutable, presentation-safe Palette descriptors.  It is a
data/adapter seam only:

- it never owns command execution truth (the existing coordinator callbacks
  remain the single execution owner),
- it never holds QWidget/QAction/QMenu/backend objects,
- building or enumerating descriptors performs zero execution side effects,
- dispatch routes a descriptor back to the *same existing callback exactly
  once*.

The descriptor schema is deliberately minimal: semantic id, label, group,
enabled, disabled reason, checked/conditional state, and a serializable
invoke intent (07 §19).  No field beyond authority is added.

Single-semantic invariant: every CommandId maps to exactly one
CommandInvokeIntent in the single module table below.  The builder, the
descriptor constructor and the dispatch seam all derive from that one table,
so command_id and invoke_intent can never silently disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from arkclaw.application.pet.pet_production_actions import (
    ProductionAction,
    can_resume_autonomous,
)
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_service import AutostartSnapshot
from arkclaw.presentation.frontend_presentation import (
    ConversationOpenOrRestoreIntent,
    FrontendPresentationIntent,
)


class CommandGroup(StrEnum):
    """Frozen 06 §9.2 grouping of the one Palette hierarchy."""

    AGENT = "agent"
    CHARACTER = "character"
    SYSTEM = "system"


class CommandId(StrEnum):
    """Stable semantic identity of each frozen Palette command."""

    ASK_ARKCLAW = "ask_arkclaw"
    OPEN_CHAT_WORK = "open_chat_work"
    OPEN_CHARACTER_ANIMATION = "open_character_animation"
    OPEN_SETTINGS = "open_settings"
    PAUSE_CONTINUE = "pause_continue"
    RESUME_AUTONOMOUS = "resume_autonomous"
    RELAX = "relax"
    SIT = "sit"
    SLEEP = "sleep"
    INTERACT = "interact"
    SPECIAL = "special"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    ALWAYS_ON_TOP = "always_on_top"
    START_WITH_WINDOWS = "start_with_windows"
    HIDE_PET = "hide_pet"
    QUIT = "quit"


class CommandInvokeIntent(StrEnum):
    """Serializable presentation intent carried by a descriptor.

    The intent is data only: it identifies *which* existing callback the
    dispatch seam must invoke.  It never carries a closure or a widget.
    """

    CONVERSATION_OPEN_OR_RESTORE = "conversation_open_or_restore"
    OPEN_CHAT_WORK = "open_chat_work"
    OPEN_CHARACTER_ANIMATION = "open_character_animation"
    OPEN_SETTINGS = "open_settings"
    PRODUCTION_ACTION = "production_action"
    RESUME_AUTONOMOUS = "resume_autonomous"
    TOGGLE_PAUSED = "toggle_paused"
    SET_ALWAYS_ON_TOP = "set_always_on_top"
    SET_AUTOSTART = "set_autostart"
    TOGGLE_PET_VISIBILITY = "toggle_pet_visibility"
    REQUEST_SAFE_EXIT = "request_safe_exit"


# Single authoritative semantic table (08 §14.1 "without duplicating command
# semantics").  Build, construction and dispatch all read this one mapping so
# no second, drifting command_id -> invoke_intent claim can exist.
_COMMAND_INVOKE_INTENT_BY_COMMAND_ID: dict[CommandId, CommandInvokeIntent] = {
    CommandId.ASK_ARKCLAW: CommandInvokeIntent.CONVERSATION_OPEN_OR_RESTORE,
    CommandId.OPEN_CHAT_WORK: CommandInvokeIntent.OPEN_CHAT_WORK,
    CommandId.OPEN_CHARACTER_ANIMATION: CommandInvokeIntent.OPEN_CHARACTER_ANIMATION,
    CommandId.OPEN_SETTINGS: CommandInvokeIntent.OPEN_SETTINGS,
    CommandId.PAUSE_CONTINUE: CommandInvokeIntent.TOGGLE_PAUSED,
    CommandId.RESUME_AUTONOMOUS: CommandInvokeIntent.RESUME_AUTONOMOUS,
    CommandId.RELAX: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.SIT: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.SLEEP: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.INTERACT: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.SPECIAL: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.MOVE_LEFT: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.MOVE_RIGHT: CommandInvokeIntent.PRODUCTION_ACTION,
    CommandId.ALWAYS_ON_TOP: CommandInvokeIntent.SET_ALWAYS_ON_TOP,
    CommandId.START_WITH_WINDOWS: CommandInvokeIntent.SET_AUTOSTART,
    CommandId.HIDE_PET: CommandInvokeIntent.TOGGLE_PET_VISIBILITY,
    CommandId.QUIT: CommandInvokeIntent.REQUEST_SAFE_EXIT,
}


@dataclass(frozen=True, slots=True)
class CommandDescriptor:
    """Immutable presentation-safe projection of one existing command.

    Field schema follows 07 §19 / 08 §14.1: semantic id, label, group,
    enabled, checked/conditional state and invoke intent.  Only str/enum/
    bool/None values are allowed so the descriptor can never leak a widget,
    a callback or a mutable backend object.

    Construction enforces the single-semantic invariant: a command_id whose
    invoke_intent does not match the module table raises ValueError instead
    of silently carrying a second semantic claim.
    """

    command_id: CommandId
    label: str
    group: CommandGroup
    enabled: bool
    invoke_intent: CommandInvokeIntent
    checked: bool | None = None
    disabled_reason: str | None = None
    conditional: bool = False

    def __post_init__(self) -> None:
        expected = _COMMAND_INVOKE_INTENT_BY_COMMAND_ID.get(self.command_id)
        if expected is None or self.invoke_intent is not expected:
            raise ValueError(
                f"command_id {self.command_id!r} requires invoke_intent "
                f"{expected!r}, got {self.invoke_intent!r}"
            )


class CommandDescriptorSource(Protocol):
    """Read-only state surface of the existing command source.

    Structurally mirrors the public state the production coordinator and
    tray already expose (PetTrayCommands + PetProductionActionCommands +
    autostart snapshot).  The adapter never writes to this source.
    """

    @property
    def pet_visible(self) -> bool: ...

    @property
    def pet_paused(self) -> bool: ...

    @property
    def pet_always_on_top(self) -> bool: ...

    @property
    def pet_closing(self) -> bool: ...

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]: ...

    @property
    def autostart_snapshot(self) -> AutostartSnapshot: ...

    @property
    def autostart_busy(self) -> bool: ...


class CommandDispatcher(Protocol):
    """Dispatch boundary that routes back to the existing callbacks.

    The two read properties expose the *authoritative current state* of the
    execution owner (PetApplicationCoordinator.pet_always_on_top and the
    autostart controller snapshot).  SET targets are derived from these at
    dispatch time; a stale descriptor.checked snapshot never becomes the
    application mutation target.
    """

    @property
    def pet_always_on_top(self) -> bool: ...

    @property
    def autostart_enabled(self) -> bool: ...

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome: ...

    def resume_pet_autonomous(self) -> ActionOutcome: ...

    def toggle_paused(self) -> None: ...

    def set_always_on_top(self, enabled: bool) -> None: ...

    def set_autostart_enabled(self, enabled: bool) -> None: ...

    def open_agent_window(self) -> None: ...

    def open_chat_work(self) -> None: ...

    def open_character_animation(self) -> None: ...

    def open_settings(self) -> None: ...

    def toggle_pet_visibility(self) -> None: ...

    def request_safe_exit(self) -> None: ...

    def dispatch_presentation_intent(
        self,
        intent: FrontendPresentationIntent,
    ) -> object: ...


_REASON_PET_CLOSING = "pet_closing"
_REASON_ACTION_UNAVAILABLE = "action_unavailable"
_REASON_AUTOSTART_BUSY = "autostart_busy"
_REASON_AUTOSTART_UNAVAILABLE = "autostart_unavailable"

_PRODUCTION_ACTION_BY_COMMAND_ID: dict[CommandId, ProductionAction] = {
    CommandId.RELAX: ProductionAction.RELAX,
    CommandId.SIT: ProductionAction.SIT,
    CommandId.SLEEP: ProductionAction.SLEEP,
    CommandId.INTERACT: ProductionAction.INTERACT,
    CommandId.SPECIAL: ProductionAction.SPECIAL,
    CommandId.MOVE_LEFT: ProductionAction.MOVE_LEFT,
    CommandId.MOVE_RIGHT: ProductionAction.MOVE_RIGHT,
}

_CHARACTER_ACTION_ORDER: tuple[CommandId, ...] = (
    CommandId.RELAX,
    CommandId.SIT,
    CommandId.SLEEP,
    CommandId.INTERACT,
    CommandId.SPECIAL,
    CommandId.MOVE_LEFT,
    CommandId.MOVE_RIGHT,
)


# Thin compatibility alias: the adapter keeps the historical public name,
# but the one production implementation of the Resume Autonomous validity
# predicate lives in pet_production_actions.can_resume_autonomous.
resume_autonomous_available = can_resume_autonomous


def _production_action_descriptor(
    command_id: CommandId,
    *,
    available_actions: frozenset[ProductionAction],
    closing: bool,
) -> CommandDescriptor:
    enabled = not closing and _PRODUCTION_ACTION_BY_COMMAND_ID[
        command_id
    ] in available_actions
    disabled_reason = (
        _REASON_PET_CLOSING
        if closing
        else (None if enabled else _REASON_ACTION_UNAVAILABLE)
    )
    return CommandDescriptor(
        command_id=command_id,
        label=command_id.value.replace("_", " ").title(),
        group=CommandGroup.CHARACTER,
        enabled=enabled,
        invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[command_id],
        disabled_reason=disabled_reason,
    )


def build_command_descriptors(
    source: CommandDescriptorSource,
) -> tuple[CommandDescriptor, ...]:
    """Project the frozen 06 §9.2 hierarchy from one existing command source.

    Pure read-only projection: no callback is invoked and no state is
    mutated.  The same source always produces the same deterministic tuple.
    """
    closing = source.pet_closing
    available_actions = source.available_pet_actions
    autostart = source.autostart_snapshot
    descriptors: list[CommandDescriptor] = [
        CommandDescriptor(
            command_id=CommandId.ASK_ARKCLAW,
            label="Ask ArkClaw",
            group=CommandGroup.AGENT,
            enabled=not closing,
            invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[
                CommandId.ASK_ARKCLAW
            ],
            disabled_reason=_REASON_PET_CLOSING if closing else None,
        ),
    ]
    descriptors.append(
        CommandDescriptor(
            command_id=CommandId.PAUSE_CONTINUE,
            label="Continue" if source.pet_paused else "Pause",
            group=CommandGroup.CHARACTER,
            enabled=not closing,
            invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[
                CommandId.PAUSE_CONTINUE
            ],
            disabled_reason=_REASON_PET_CLOSING if closing else None,
        )
    )
    resume_enabled = can_resume_autonomous(
        closing=closing,
        available_actions=available_actions,
    )
    descriptors.append(
        CommandDescriptor(
            command_id=CommandId.RESUME_AUTONOMOUS,
            label="Resume Autonomous",
            group=CommandGroup.CHARACTER,
            enabled=resume_enabled,
            invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[
                CommandId.RESUME_AUTONOMOUS
            ],
            disabled_reason=(
                _REASON_PET_CLOSING
                if closing
                else (None if resume_enabled else _REASON_ACTION_UNAVAILABLE)
            ),
            conditional=True,
        )
    )
    for command_id in _CHARACTER_ACTION_ORDER:
        descriptors.append(
            _production_action_descriptor(
                command_id,
                available_actions=available_actions,
                closing=closing,
            )
        )
    descriptors.append(
        CommandDescriptor(
            command_id=CommandId.ALWAYS_ON_TOP,
            label="Always on Top",
            group=CommandGroup.SYSTEM,
            enabled=not closing,
            invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[
                CommandId.ALWAYS_ON_TOP
            ],
            checked=source.pet_always_on_top,
            disabled_reason=_REASON_PET_CLOSING if closing else None,
        )
    )
    autostart_toggle_allowed = autostart.user_toggle_allowed and not (
        source.autostart_busy
    )
    autostart_enabled = (
        not closing and autostart.user_toggle_allowed and not source.autostart_busy
    )
    autostart_reason = (
        _REASON_PET_CLOSING
        if closing
        else (
            _REASON_AUTOSTART_BUSY
            if source.autostart_busy
            else (
                None
                if autostart_toggle_allowed
                else _REASON_AUTOSTART_UNAVAILABLE
            )
        )
    )
    descriptors.append(
        CommandDescriptor(
            command_id=CommandId.START_WITH_WINDOWS,
            label="Start with Windows",
            group=CommandGroup.SYSTEM,
            enabled=autostart_enabled,
            invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[
                CommandId.START_WITH_WINDOWS
            ],
            checked=autostart.enabled,
            disabled_reason=autostart_reason,
        )
    )
    for command_id, label in (
        (
            CommandId.HIDE_PET,
            "Hide Character" if source.pet_visible else "Show Character",
        ),
        (CommandId.QUIT, "Quit"),
    ):
        descriptors.append(
            CommandDescriptor(
                command_id=command_id,
                label=label,
                group=CommandGroup.SYSTEM,
                enabled=not closing,
                invoke_intent=_COMMAND_INVOKE_INTENT_BY_COMMAND_ID[command_id],
                disabled_reason=_REASON_PET_CLOSING if closing else None,
            )
        )
    return tuple(descriptors)


def dispatch_command_descriptor(
    descriptor: CommandDescriptor,
    dispatcher: CommandDispatcher,
) -> object | None:
    """Invoke exactly one existing callback for one enabled descriptor.

    Disabled descriptors are refused: nothing is dispatched and no execution
    side effect can occur.  The Ask command emits only the frozen
    ConversationOpenOrRestore presentation intent (07 §20.1); it never starts
    a backend task.

    Routing uses the single authoritative semantic table; a descriptor whose
    invoke_intent disagrees with its command_id raises ValueError instead of
    silently executing one of the two semantics.  Always on Top and Start
    with Windows derive their SET target from the dispatcher's authoritative
    current state at dispatch time, never from the stale checked snapshot.
    """
    if not descriptor.enabled:
        return None
    intent = _COMMAND_INVOKE_INTENT_BY_COMMAND_ID.get(descriptor.command_id)
    if intent is None or descriptor.invoke_intent is not intent:
        raise ValueError(
            "descriptor semantic mismatch: command_id "
            f"{descriptor.command_id!r} -> invoke_intent "
            f"{descriptor.invoke_intent!r} (expected {intent!r})"
        )
    if intent is CommandInvokeIntent.OPEN_CHAT_WORK:
        dispatcher.open_chat_work()
        return None
    if intent is CommandInvokeIntent.OPEN_CHARACTER_ANIMATION:
        dispatcher.open_character_animation()
        return None
    if intent is CommandInvokeIntent.OPEN_SETTINGS:
        dispatcher.open_settings()
        return None
    if intent is CommandInvokeIntent.CONVERSATION_OPEN_OR_RESTORE:
        return dispatcher.dispatch_presentation_intent(
            ConversationOpenOrRestoreIntent()
        )
    if intent is CommandInvokeIntent.TOGGLE_PAUSED:
        dispatcher.toggle_paused()
        return None
    if intent is CommandInvokeIntent.RESUME_AUTONOMOUS:
        return dispatcher.resume_pet_autonomous()
    if intent is CommandInvokeIntent.PRODUCTION_ACTION:
        return dispatcher.request_pet_action(
            _PRODUCTION_ACTION_BY_COMMAND_ID[descriptor.command_id]
        )
    if intent is CommandInvokeIntent.SET_ALWAYS_ON_TOP:
        dispatcher.set_always_on_top(not dispatcher.pet_always_on_top)
        return None
    if intent is CommandInvokeIntent.SET_AUTOSTART:
        dispatcher.set_autostart_enabled(not dispatcher.autostart_enabled)
        return None
    if intent is CommandInvokeIntent.TOGGLE_PET_VISIBILITY:
        dispatcher.toggle_pet_visibility()
        return None
    if intent is CommandInvokeIntent.REQUEST_SAFE_EXIT:
        dispatcher.request_safe_exit()
        return None
    return None


__all__ = [
    "CommandDescriptor",
    "CommandDescriptorSource",
    "CommandDispatcher",
    "CommandGroup",
    "CommandId",
    "CommandInvokeIntent",
    "build_command_descriptors",
    "dispatch_command_descriptor",
    "resume_autonomous_available",
]
