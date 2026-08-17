from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMenu, QPushButton

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_state import PetLifecycleState
from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.theme.design_tokens import (
    ThemeVariant,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.theme_controller import QtTheme
from arkclaw.presentation.qt.ui.control_center import (
    SCHWARZ_ACTIONS,
    ControlCenterView,
    PetPresentationSnapshot,
)
from arkclaw.presentation.qt.ui.main_window import MainWindow
from arkclaw.presentation.qt.ui.production_action_menu import (
    ProductionActionMenuSection,
    prepare_arkclaw_menu,
)


@pytest.fixture
def qt_application() -> Iterator[QApplication]:
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    yield app
    app.processEvents()
    if owns_application:
        app.quit()


def _run_until(
    predicate: Callable[[], bool],
    timeout_seconds: float = 5.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    QCoreApplication.processEvents()
    return predicate()


def test_control_center_exposes_frozen_navigation_and_honest_capabilities(
    qt_application: QApplication,
) -> None:
    del qt_application
    view = ControlCenterView(None)

    assert view.current_page == "home"
    assert tuple(view.pages) == (
        "home",
        "pets",
        "animations",
        "interaction",
        "appearance",
        "settings",
    )
    assert not view.home_page.interact_button.isEnabled()
    assert len(SCHWARZ_ACTIONS) == 7
    assert view.pets_page.findChildren(QPushButton, "addCharacterButton") == []

    view.navigate("animations")
    assert view.current_page == "animations"
    assert "Move Left" in {action.name for action in SCHWARZ_ACTIONS}
    assert "Move Right" in {action.name for action in SCHWARZ_ACTIONS}


def test_control_center_degrades_to_icon_rail_and_inspector_drawer(
    qt_application: QApplication,
) -> None:
    del qt_application
    view = ControlCenterView(None)

    view.apply_width(1180)
    assert view.sidebar.width() == 208
    assert view.inspector.isVisibleTo(view)
    assert not view.details_button.isVisibleTo(view)

    view.apply_width(1000)
    assert view.sidebar.width() == 72
    assert view.inspector.isVisibleTo(view)

    view.apply_width(900)
    assert view.sidebar.width() == 72
    assert view.inspector.isHidden()
    assert not view.details_button.isHidden()

    view.open_inspector()
    assert not view.inspector.isHidden()
    view.close_inspector()
    assert view.inspector.isHidden()


def test_runtime_snapshot_uses_distinct_hidden_paused_and_ready_states(
    qt_application: QApplication,
) -> None:
    del qt_application
    view = ControlCenterView(None)

    hidden = PetPresentationSnapshot(
        visible=False,
        paused=False,
        action="Relaxing",
        attached=True,
    )
    view.update_pet(hidden, runtime_ready=True)
    assert view.home_page.lifecycle_badge.text() == "Hidden"
    assert view.home_page.visibility_button.text() == "Show"

    paused = PetPresentationSnapshot(
        visible=True,
        paused=True,
        action="Relaxing",
        attached=True,
    )
    view.update_pet(paused, runtime_ready=True)
    assert view.home_page.lifecycle_badge.text() == "Paused"
    assert view.home_page.pause_button.text() == "Resume"

    ready = PetPresentationSnapshot(
        visible=True,
        paused=False,
        action="Moving left",
        attached=True,
    )
    view.update_pet(ready, runtime_ready=True)
    assert view.home_page.lifecycle_badge.text() == "Ready"
    assert view.home_page.interact_button.isEnabled()
    assert "Moving left" in view.home_page.action_label.text()


def test_animation_inspector_emits_current_arkclaw_action(
    qt_application: QApplication,
) -> None:
    del qt_application
    view = ControlCenterView(None)
    requested: list[str] = []
    view.action_requested.connect(requested.append)

    view.inspector.show_action(SCHWARZ_ACTIONS[-1])
    play = view.inspector.findChild(QPushButton, "playDesktopActionButton")

    assert play is not None
    assert play.isEnabled()
    play.click()
    assert requested == ["Interact"]


def test_context_menu_uses_arkclaw_action_deck_style(
    qt_application: QApplication,
) -> None:
    del qt_application
    menu = QMenu()
    requested: list[ProductionAction] = []
    prepare_arkclaw_menu(menu, object_name="arkclawPetContextMenu", theme=QtTheme.DARK)
    section = ProductionActionMenuSection(
        menu,
        request_action=requested.append,
        resume_autonomous=lambda: None,
    )
    section.update(
        role_pack_id="schwarz-production",
        available_actions=frozenset(ProductionAction),
        closing=False,
    )

    assert menu.objectName() == "arkclawPetContextMenu"
    accent = load_design_tokens().theme(ThemeVariant.DARK).accent.default
    assert accent in menu.styleSheet()
    assert menu.minimumWidth() == 244
    assert section.role_pack_action.text() == "ACTIVE PET  ·  SCHWARZ / 黑"
    assert section.move_menu.objectName() == "arkclawMoveActionMenu"


def test_home_controls_drive_existing_pet_coordinator(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "control-center.json")
    )
    window = MainWindow(bridge, hide_on_close=True)
    pet = PetWindow(
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )
    coordinator = PetApplicationCoordinator(bridge, window, pet)

    coordinator.show_pet()
    assert _run_until(lambda: bridge.accepting_commands)
    assert window.control_center.home_page.lifecycle_badge.text() == "Ready"

    requested_actions: list[str] = []
    window.pet_action_requested.connect(requested_actions.append)
    window.control_center.home_page.interact_button.click()
    assert requested_actions == ["Interact"]

    window.control_center.home_page.pause_button.click()
    assert pet.lifecycle_state is PetLifecycleState.PAUSED
    assert window.control_center.home_page.lifecycle_badge.text() == "Paused"

    window.control_center.home_page.visibility_button.click()
    assert not pet.isVisible()
    assert window.control_center.home_page.lifecycle_badge.text() == "Hidden"

    pet.request_safe_exit()
    assert _run_until(lambda: not bridge.runtime_thread.isRunning())
    assert bridge.runtime_thread.pending_task_count_at_close == 0

def test_menu_resume_enabled_state_consumes_shared_capability(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    menu = QMenu()
    section = ProductionActionMenuSection(
        menu,
        request_action=lambda action: None,
        resume_autonomous=lambda: None,
    )
    # Frozen baseline states (unchanged production semantic).
    section.update(
        role_pack_id="schwarz-production",
        available_actions=frozenset({ProductionAction.RELAX}),
        closing=False,
    )
    assert section.resume_autonomous_action.isEnabled()
    section.update(
        role_pack_id="schwarz-production",
        available_actions=frozenset({ProductionAction.RELAX}),
        closing=True,
    )
    assert not section.resume_autonomous_action.isEnabled()
    section.update(
        role_pack_id="schwarz-production",
        available_actions=frozenset({ProductionAction.SIT}),
        closing=False,
    )
    assert not section.resume_autonomous_action.isEnabled()

    # The enabled state must be driven by the shared Qt-free capability, not
    # by a re-implemented boolean inside the menu.
    monkeypatch.setattr(
        "arkclaw.presentation.qt.ui.production_action_menu.can_resume_autonomous",
        lambda *, closing, available_actions: False,
    )
    section.update(
        role_pack_id="schwarz-production",
        available_actions=frozenset({ProductionAction.RELAX}),
        closing=False,
    )
    assert not section.resume_autonomous_action.isEnabled()
    monkeypatch.setattr(
        "arkclaw.presentation.qt.ui.production_action_menu.can_resume_autonomous",
        lambda *, closing, available_actions: True,
    )
    section.update(
        role_pack_id="schwarz-production",
        available_actions=frozenset({ProductionAction.SIT}),
        closing=False,
    )
    assert section.resume_autonomous_action.isEnabled()
    menu.close()
