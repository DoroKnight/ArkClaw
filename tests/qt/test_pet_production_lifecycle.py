"""Persistent tray lifetime for production pet actions."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.presentation.qt.platform.system_tray import (
    PetTrayState,
    SystemTrayController,
    TrayCallbacks,
)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


class _Commands:
    pet_visible = True
    pet_paused = False
    pet_always_on_top = True
    pet_closing = False
    active_role_pack_id = "schwarz-production"
    available_pet_actions = frozenset(ProductionAction)

    def __init__(self) -> None:
        self.actions: list[ProductionAction] = []
        self.resume_count = 0
        self.exit_count = 0

    def toggle_pet_visibility(self) -> None:
        self.pet_visible = not self.pet_visible

    def open_agent_window(self) -> None:
        pass

    def toggle_paused(self) -> None:
        self.pet_paused = not self.pet_paused

    def set_always_on_top(self, enabled: bool) -> None:
        self.pet_always_on_top = enabled

    def request_safe_exit(self) -> None:
        self.exit_count += 1

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        self.actions.append(action)
        return ActionOutcome.ACCEPTED

    def resume_pet_autonomous(self) -> ActionOutcome:
        self.resume_count += 1
        return ActionOutcome.ACCEPTED


class _View:
    def __init__(self, callbacks: TrayCallbacks) -> None:
        self.callbacks = callbacks
        self.visible = False
        self.states: list[PetTrayState] = []

    def show(self) -> None:
        self.visible = True

    def is_visible(self) -> bool:
        return self.visible

    def update_state(self, state: PetTrayState) -> None:
        self.states.append(state)

    def close(self) -> None:
        self.visible = False


def test_actions_hide_and_resume_never_exit_but_explicit_exit_is_once(
    qt_application: QApplication,
) -> None:
    del qt_application
    commands = _Commands()
    views: list[_View] = []

    def factory(callbacks: TrayCallbacks, parent: QObject) -> _View:
        del parent
        view = _View(callbacks)
        views.append(view)
        return view

    tray = SystemTrayController(
        commands,
        production_actions=commands,
        view_factory=factory,
    )
    view = views[0]

    assert view.callbacks.request_action is not None
    assert view.callbacks.resume_autonomous is not None
    view.callbacks.request_action(ProductionAction.SPECIAL)
    view.callbacks.resume_autonomous()
    view.callbacks.toggle_pet_visibility()

    assert commands.exit_count == 0
    assert tray.visible
    assert commands.actions == [ProductionAction.SPECIAL]
    assert commands.resume_count == 1

    view.callbacks.request_safe_exit()
    view.callbacks.request_safe_exit()
    assert commands.exit_count == 1
