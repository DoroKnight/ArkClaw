"""Slice 5A — Command Descriptor Adapter characterization (Qt-free).

Authority: 08 §14.1 (Slice 5A), 07 §19, 06 §9.2, 09 §18.
The adapter seam does not exist yet (08 §14.1 lists the candidate
presentation-neutral descriptor module as "does not exist"), so the whole
module import is the contract RED until the seam is added.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.presentation.frontend_presentation import (
    ConversationOpenOrRestoreIntent,
    FrontendPresentationIntent,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"


class FakeCommandSource:
    """Qt-free structural stand-in for the existing command source.

    Mirrors the public state exposed by the production coordinator / tray
    (PetTrayCommands + PetProductionActionCommands + autostart snapshot).
    """

    def __init__(
        self,
        *,
        pet_visible: bool = True,
        pet_paused: bool = False,
        pet_always_on_top: bool = False,
        pet_closing: bool = False,
        available_actions: frozenset[ProductionAction] = frozenset(
            ProductionAction
        ),
        autostart_snapshot: AutostartSnapshot | None = None,
        autostart_busy: bool = False,
    ) -> None:
        self._pet_visible = pet_visible
        self._pet_paused = pet_paused
        self._pet_always_on_top = pet_always_on_top
        self._pet_closing = pet_closing
        self._available_actions = available_actions
        self._autostart_snapshot = autostart_snapshot or (
            AutostartSnapshot.for_status(AutostartStatus.DISABLED)
        )
        self._autostart_busy = autostart_busy

    @property
    def pet_visible(self) -> bool:
        return self._pet_visible

    @property
    def pet_paused(self) -> bool:
        return self._pet_paused

    @property
    def pet_always_on_top(self) -> bool:
        return self._pet_always_on_top

    @property
    def pet_closing(self) -> bool:
        return self._pet_closing

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]:
        return self._available_actions

    @property
    def autostart_snapshot(self) -> AutostartSnapshot:
        return self._autostart_snapshot

    @property
    def autostart_busy(self) -> bool:
        return self._autostart_busy


class RecordingCommandDispatcher:
    """Records every callback invocation without executing real commands."""

    def __init__(
        self,
        *,
        pet_always_on_top: bool = False,
        autostart_enabled: bool = False,
    ) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.requested_actions: list[ProductionAction] = []
        self.presentation_intents: list[FrontendPresentationIntent] = []
        self._pet_always_on_top = pet_always_on_top
        self._autostart_enabled = autostart_enabled

    @property
    def pet_always_on_top(self) -> bool:
        return self._pet_always_on_top

    @property
    def autostart_enabled(self) -> bool:
        return self._autostart_enabled

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        self.calls.append(("request_pet_action", (action,)))
        self.requested_actions.append(action)
        return ActionOutcome.ACCEPTED

    def resume_pet_autonomous(self) -> ActionOutcome:
        self.calls.append(("resume_pet_autonomous", ()))
        return ActionOutcome.ACCEPTED

    def toggle_paused(self) -> None:
        self.calls.append(("toggle_paused", ()))

    def set_always_on_top(self, enabled: bool) -> None:
        self.calls.append(("set_always_on_top", (enabled,)))

    def set_autostart_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_autostart_enabled", (enabled,)))

    def open_agent_window(self) -> None:
        self.calls.append(("open_agent_window", ()))

    def toggle_pet_visibility(self) -> None:
        self.calls.append(("toggle_pet_visibility", ()))

    def request_safe_exit(self) -> None:
        self.calls.append(("request_safe_exit", ()))

    def dispatch_presentation_intent(
        self,
        intent: FrontendPresentationIntent,
    ) -> object:
        self.calls.append(("dispatch_presentation_intent", (intent,)))
        self.presentation_intents.append(intent)
        return None


def _default_source() -> FakeCommandSource:
    return FakeCommandSource()


def test_adapter_seam_exists_and_is_qt_free() -> None:
    import arkclaw.presentation.command_descriptor_adapter as adapter

    assert adapter.build_command_descriptors is not None
    assert adapter.dispatch_command_descriptor is not None
    source = Path(adapter.__file__).read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "QApplication" not in source


def test_adapter_core_imports_without_qt() -> None:
    probe = (
        "import builtins\n"
        "real_import = builtins.__import__\n"
        "def guarded(name, *args, **kwargs):\n"
        "    if name == 'PySide6' or name.startswith('PySide6.'):\n"
        "        raise AssertionError('PySide6 must not be imported')\n"
        "    return real_import(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded\n"
        "import arkclaw.presentation.command_descriptor_adapter as m\n"
        "assert callable(m.build_command_descriptors)\n"
        "assert callable(m.dispatch_command_descriptor)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_descriptor_projection_is_stable_and_deterministic() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
    )

    first = build_command_descriptors(_default_source())
    second = build_command_descriptors(_default_source())

    assert first == second
    assert first
    assert all(descriptor.enabled for descriptor in first)


def test_agent_character_system_grouping_matches_frozen_hierarchy() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandGroup,
        build_command_descriptors,
    )

    descriptors = build_command_descriptors(_default_source())
    grouped = {
        group: [d.command_id for d in descriptors if d.group is group]
        for group in CommandGroup
    }

    assert grouped[CommandGroup.AGENT] == ["ask_arkclaw"]
    assert grouped[CommandGroup.CHARACTER] == [
        "pause_continue",
        "resume_autonomous",
        "relax",
        "sit",
        "sleep",
        "interact",
        "special",
        "move_left",
        "move_right",
    ]
    assert grouped[CommandGroup.SYSTEM] == [
        "always_on_top",
        "start_with_windows",
        "hide_pet",
        "quit",
    ]


def test_character_availability_reflects_available_actions() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    available = frozenset({ProductionAction.RELAX, ProductionAction.INTERACT})
    source = FakeCommandSource(available_actions=available)
    descriptors = {
        d.command_id: d for d in build_command_descriptors(source)
    }

    assert descriptors[CommandId.RELAX].enabled is True
    assert descriptors[CommandId.INTERACT].enabled is True
    assert descriptors[CommandId.SIT].enabled is False
    assert descriptors[CommandId.SLEEP].enabled is False
    assert descriptors[CommandId.MOVE_LEFT].enabled is False
    assert descriptors[CommandId.SPECIAL].enabled is False
    assert descriptors[CommandId.SIT].disabled_reason == "action_unavailable"


def test_resume_autonomous_is_conditional_on_relax_availability() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    without_relax = FakeCommandSource(
        available_actions=frozenset({ProductionAction.INTERACT})
    )
    with_relax = FakeCommandSource(
        available_actions=frozenset({ProductionAction.RELAX})
    )

    disabled = {
        d.command_id: d
        for d in build_command_descriptors(without_relax)
    }[CommandId.RESUME_AUTONOMOUS]
    enabled = {
        d.command_id: d for d in build_command_descriptors(with_relax)
    }[CommandId.RESUME_AUTONOMOUS]

    assert disabled.conditional is True
    assert disabled.enabled is False
    assert disabled.disabled_reason == "action_unavailable"
    assert enabled.conditional is True
    assert enabled.enabled is True


def test_pause_continue_label_and_semantic_are_state_aware() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    running = {
        d.command_id: d for d in build_command_descriptors(_default_source())
    }[CommandId.PAUSE_CONTINUE]
    paused = {
        d.command_id: d
        for d in build_command_descriptors(
            FakeCommandSource(pet_paused=True)
        )
    }[CommandId.PAUSE_CONTINUE]

    assert running.label == "Pause"
    assert paused.label == "Continue"


def test_closing_disables_every_command_with_honest_reason() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
    )

    descriptors = build_command_descriptors(
        FakeCommandSource(pet_closing=True)
    )

    assert descriptors
    assert all(not d.enabled for d in descriptors)
    assert all(d.disabled_reason == "pet_closing" for d in descriptors)


def test_always_on_top_checked_state_and_toggle_dispatch() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    on_source = FakeCommandSource(pet_always_on_top=True)
    on = {
        d.command_id: d for d in build_command_descriptors(on_source)
    }[CommandId.ALWAYS_ON_TOP]
    dispatcher = RecordingCommandDispatcher(pet_always_on_top=True)

    assert on.checked is True
    dispatch_command_descriptor(on, dispatcher)

    assert dispatcher.calls == [("set_always_on_top", (False,))]


def test_start_with_windows_reflects_autostart_state() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    enabled = FakeCommandSource(
        autostart_snapshot=AutostartSnapshot.for_status(
            AutostartStatus.ENABLED
        )
    )
    unavailable = FakeCommandSource(
        autostart_snapshot=AutostartSnapshot.for_status(
            AutostartStatus.UNAVAILABLE
        )
    )
    busy = FakeCommandSource(
        autostart_snapshot=AutostartSnapshot.for_status(
            AutostartStatus.ENABLED
        ),
        autostart_busy=True,
    )

    enabled_d = {
        d.command_id: d for d in build_command_descriptors(enabled)
    }[CommandId.START_WITH_WINDOWS]
    unavailable_d = {
        d.command_id: d for d in build_command_descriptors(unavailable)
    }[CommandId.START_WITH_WINDOWS]
    busy_d = {
        d.command_id: d for d in build_command_descriptors(busy)
    }[CommandId.START_WITH_WINDOWS]

    assert enabled_d.checked is True
    assert enabled_d.enabled is True
    assert unavailable_d.checked is False
    assert unavailable_d.enabled is False
    assert unavailable_d.disabled_reason == "autostart_unavailable"
    assert busy_d.enabled is False
    assert busy_d.disabled_reason == "autostart_busy"


def test_hide_pet_label_reflects_visibility_command() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    visible = {
        d.command_id: d for d in build_command_descriptors(_default_source())
    }[CommandId.HIDE_PET]
    hidden = {
        d.command_id: d
        for d in build_command_descriptors(
            FakeCommandSource(pet_visible=False)
        )
    }[CommandId.HIDE_PET]

    assert visible.label == "Hide Character"
    assert hidden.label == "Show Character"


def test_interact_descriptor_dispatches_existing_interact_semantic_once() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        CommandInvokeIntent,
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    interact = {
        d.command_id: d
        for d in build_command_descriptors(_default_source())
    }[CommandId.INTERACT]
    dispatcher = RecordingCommandDispatcher()

    assert interact.label == "Interact"
    assert interact.invoke_intent is CommandInvokeIntent.PRODUCTION_ACTION
    result = dispatch_command_descriptor(interact, dispatcher)

    assert dispatcher.requested_actions == [ProductionAction.INTERACT]
    assert dispatcher.calls == [
        ("request_pet_action", (ProductionAction.INTERACT,))
    ]
    assert result is ActionOutcome.ACCEPTED


def test_ask_arkclaw_emits_only_conversation_open_or_restore_intent() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        CommandInvokeIntent,
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    ask = {
        d.command_id: d
        for d in build_command_descriptors(_default_source())
    }[CommandId.ASK_ARKCLAW]
    dispatcher = RecordingCommandDispatcher()

    assert ask.invoke_intent is CommandInvokeIntent.CONVERSATION_OPEN_OR_RESTORE
    dispatch_command_descriptor(ask, dispatcher)

    assert len(dispatcher.presentation_intents) == 1
    assert isinstance(
        dispatcher.presentation_intents[0], ConversationOpenOrRestoreIntent
    )
    assert len(dispatcher.requested_actions) == 0
    assert len(dispatcher.calls) == 1


def test_every_enabled_descriptor_dispatches_exactly_once() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    descriptors = build_command_descriptors(_default_source())
    dispatcher = RecordingCommandDispatcher()

    for descriptor in descriptors:
        before = len(dispatcher.calls)
        dispatch_command_descriptor(descriptor, dispatcher)
        assert len(dispatcher.calls) - before == 1

    assert len(dispatcher.calls) == len(descriptors)


def test_disabled_descriptor_dispatch_is_refused_without_side_effect() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    descriptors = {
        d.command_id: d
        for d in build_command_descriptors(
            FakeCommandSource(available_actions=frozenset())
        )
    }
    dispatcher = RecordingCommandDispatcher()

    refused = dispatch_command_descriptor(
        descriptors[CommandId.SIT], dispatcher
    )
    no_op = dispatch_command_descriptor(
        descriptors[CommandId.SPECIAL], dispatcher
    )

    assert refused is None
    assert no_op is None
    assert dispatcher.calls == []


def test_build_has_zero_execution_side_effects() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
    )

    source = _default_source()
    dispatcher = RecordingCommandDispatcher()

    build_command_descriptors(source)

    assert dispatcher.calls == []
    assert dispatcher.requested_actions == []
    assert dispatcher.presentation_intents == []


def test_descriptors_are_immutable_and_presentation_safe() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
    )

    descriptors = build_command_descriptors(_default_source())

    with pytest.raises(FrozenInstanceError):
        descriptors[0].label = "changed"  # type: ignore[misc]

    for descriptor in descriptors:
        for field in fields(descriptor):
            value = getattr(descriptor, field.name)
            assert isinstance(value, (str, bool, type(None))), (
                f"{field.name} leaks non-presentation type: {type(value)}"
            )


def test_capability_inventory_matches_frozen_baseline() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    descriptor_ids = {
        d.command_id for d in build_command_descriptors(_default_source())
    }
    frozen_command_ids = set(CommandId)

    assert descriptor_ids == frozen_command_ids
    assert "settings" not in {str(command_id) for command_id in descriptor_ids}


def test_role_identity_is_presentation_only_and_not_a_command() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
    )

    descriptors = build_command_descriptors(_default_source())

    assert "role_heading" not in {str(d.command_id) for d in descriptors}


def test_resume_autonomous_availability_mirrors_existing_production_guard() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
        resume_autonomous_available,
    )

    # Exact mirror of the existing production guard
    # (PetWindow._resume_pet_autonomous, pet_window.py): resume is invalid
    # while closing or while RELAX is not among the available production
    # actions.  Cross-states such as "RELAX available but resume invalid" or
    # "RELAX missing but resume valid" are impossible per that guard.
    assert (
        resume_autonomous_available(
            closing=False,
            available_actions=frozenset({ProductionAction.RELAX}),
        )
        is True
    )
    assert (
        resume_autonomous_available(
            closing=False,
            available_actions=frozenset(),
        )
        is False
    )
    assert (
        resume_autonomous_available(
            closing=True,
            available_actions=frozenset({ProductionAction.RELAX}),
        )
        is False
    )

    # Availability of *unrelated* actions never changes the result: the
    # predicate depends only on closing and RELAX availability.
    assert (
        resume_autonomous_available(
            closing=False,
            available_actions=frozenset(
                {ProductionAction.RELAX, ProductionAction.SIT}
            ),
        )
        is True
    )
    assert (
        resume_autonomous_available(
            closing=False,
            available_actions=frozenset(
                {ProductionAction.SIT, ProductionAction.SLEEP}
            ),
        )
        is False
    )

    # The builder derives the descriptor through the same single predicate.
    source = FakeCommandSource(
        available_actions=frozenset(
            {ProductionAction.RELAX, ProductionAction.SIT}
        )
    )
    resume = {
        d.command_id: d for d in build_command_descriptors(source)
    }[CommandId.RESUME_AUTONOMOUS]
    assert resume.enabled is resume_autonomous_available(
        closing=False,
        available_actions=source.available_pet_actions,
    )
    assert resume.conditional is True


def test_stale_checked_snapshot_cannot_decide_always_on_top_target() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    stale = {
        d.command_id: d
        for d in build_command_descriptors(
            FakeCommandSource(pet_always_on_top=False)
        )
    }[CommandId.ALWAYS_ON_TOP]
    assert stale.checked is False

    # authoritative state has since drifted to True
    dispatcher = RecordingCommandDispatcher(pet_always_on_top=True)

    dispatch_command_descriptor(stale, dispatcher)

    # Target is derived from the authoritative current state at dispatch
    # time (SET(not current) -> False); the stale snapshot value must not
    # dictate the application mutation target.
    assert dispatcher.calls == [("set_always_on_top", (False,))]


def test_stale_checked_snapshot_cannot_decide_autostart_target() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
        dispatch_command_descriptor,
    )

    stale = {
        d.command_id: d
        for d in build_command_descriptors(
            FakeCommandSource(
                autostart_snapshot=AutostartSnapshot.for_status(
                    AutostartStatus.DISABLED
                )
            )
        )
    }[CommandId.START_WITH_WINDOWS]
    assert stale.checked is False

    dispatcher = RecordingCommandDispatcher(autostart_enabled=True)

    dispatch_command_descriptor(stale, dispatcher)

    assert dispatcher.calls == [("set_autostart_enabled", (False,))]


def test_command_id_invoke_intent_mismatch_is_rejected() -> None:
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandDescriptor,
        CommandGroup,
        CommandId,
        CommandInvokeIntent,
    )

    with pytest.raises(ValueError):
        CommandDescriptor(
            command_id=CommandId.QUIT,
            label="Quit",
            group=CommandGroup.SYSTEM,
            enabled=True,
            invoke_intent=CommandInvokeIntent.TOGGLE_PAUSED,
        )

def test_descriptor_resume_enabled_consumes_shared_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arkclaw.presentation.command_descriptor_adapter as adapter
    from arkclaw.presentation.command_descriptor_adapter import (
        CommandId,
        build_command_descriptors,
    )

    # The descriptor projection must be driven by the shared Qt-free
    # capability, not by a re-implemented boolean inside the adapter.
    monkeypatch.setattr(
        adapter,
        "can_resume_autonomous",
        lambda *, closing, available_actions: False,
    )
    source = FakeCommandSource(
        available_actions=frozenset({ProductionAction.RELAX})
    )
    resume = {
        d.command_id: d for d in build_command_descriptors(source)
    }[CommandId.RESUME_AUTONOMOUS]
    assert resume.enabled is False

    monkeypatch.setattr(
        adapter,
        "can_resume_autonomous",
        lambda *, closing, available_actions: True,
    )
    source = FakeCommandSource(
        available_actions=frozenset({ProductionAction.SIT})
    )
    resume = {
        d.command_id: d for d in build_command_descriptors(source)
    }[CommandId.RESUME_AUTONOMOUS]
    assert resume.enabled is True
