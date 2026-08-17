"""Production action controls exposed by the persistent pet tray."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from arkclaw.application.pet.pet_production_actions import ActionSource, ProductionAction
from arkclaw.application.pet.pet_role_pack import (
    AnimationRoleRegistry,
    RoleAnimationBinding,
    build_track0_animation_registry,
)
from arkclaw.application.pet.pet_state import PetMotionState
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    AnimationPlayerCapabilities,
    PetTrack0Controller,
    PlaybackRequest,
    PlaybackToken,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.platform.system_tray import (
    PetTrayState,
    TrayCallbacks,
    _QtSystemTrayView,
)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


def _callbacks(events: list[object]) -> TrayCallbacks:
    return TrayCallbacks(
        refresh=lambda: None,
        toggle_pet_visibility=lambda: None,
        open_agent_window=lambda: None,
        open_dashboard=lambda: events.append("dashboard"),
        toggle_paused=lambda: None,
        set_always_on_top=lambda enabled: None,
        request_safe_exit=lambda: None,
        request_action=lambda action: events.append(action),
        resume_autonomous=lambda: events.append("resume"),
    )


class _Clock:
    def now(self) -> float:
        return 10.0


class _Player:
    capabilities = AnimationPlayerCapabilities(True, True, True, True)

    def __init__(self) -> None:
        self.requests: list[PlaybackRequest] = []

    def play(self, request: PlaybackRequest) -> PlaybackToken:
        self.requests.append(request)
        return object()

    def clear(self, track: int, mix_seconds: float) -> None:
        del track, mix_seconds


class _MalformedPlaybackSource:
    def update(self, delta_seconds: float) -> tuple[object, ...]:
        del delta_seconds
        return (object(),)


def test_tray_exposes_seven_typed_actions_resume_and_role_pack_identity(
    qt_application: QApplication,
) -> None:
    del qt_application
    events: list[object] = []
    parent = QObject()
    view = _QtSystemTrayView(_callbacks(events), parent)

    view.update_state(
        PetTrayState(
            pet_visible=True,
            paused=False,
            always_on_top=True,
            closing=False,
            role_pack_id="schwarz-production",
            available_actions=frozenset(ProductionAction),
        )
    )

    assert view._role_pack_action is not None
    assert view._move_menu is not None
    assert view._resume_autonomous_action is not None
    assert view._role_pack_action.text() == "ACTIVE PET  ·  SCHWARZ / 黑"
    assert view._move_menu.title() == "Move"
    assert view._action_items[ProductionAction.MOVE_LEFT].text() == "Left"
    assert view._action_items[ProductionAction.MOVE_RIGHT].text() == "Right"
    for action in ProductionAction:
        assert view._action_items[action].isEnabled()

    view._action_items[ProductionAction.SLEEP].trigger()
    view._action_items[ProductionAction.MOVE_LEFT].trigger()
    view._resume_autonomous_action.trigger()

    assert events == [
        ProductionAction.SLEEP,
        ProductionAction.MOVE_LEFT,
        "resume",
    ]
    view.close()


def test_tray_exposes_open_dashboard_action_next_to_control_center(
    qt_application: QApplication,
) -> None:
    del qt_application
    events: list[object] = []
    parent = QObject()
    view = _QtSystemTrayView(_callbacks(events), parent)

    dashboard_action = view._open_dashboard_action
    assert dashboard_action is not None
    assert dashboard_action.text() == "Open Dashboard"
    assert dashboard_action.objectName() == "openDashboardAction"

    menu_actions = view._menu.actions()
    labels = [action.text() for action in menu_actions]
    assert "Open Dashboard" in labels
    assert "Open ArkClaw Control Center" not in labels

    dashboard_action.trigger()
    assert events == ["dashboard"]
    view.close()


def test_unavailable_role_is_visibly_disabled_without_substitution(
    qt_application: QApplication,
) -> None:
    del qt_application
    events: list[object] = []
    parent = QObject()
    view = _QtSystemTrayView(_callbacks(events), parent)

    view.update_state(
        PetTrayState(
            pet_visible=True,
            paused=False,
            always_on_top=True,
            closing=False,
            role_pack_id="relax-only",
            available_actions=frozenset({ProductionAction.RELAX}),
        )
    )

    assert view._move_menu is not None
    assert view._action_items[ProductionAction.RELAX].isEnabled()
    assert not view._action_items[ProductionAction.SIT].isEnabled()
    assert not view._move_menu.menuAction().isEnabled()
    view._action_items[ProductionAction.SIT].trigger()
    assert events == []
    view.close()


def test_pet_window_exposes_one_typed_tray_gateway_and_resume_command(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    track0 = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(
                        action,
                        "Move"
                        if action
                        in {
                            ProductionAction.MOVE_LEFT,
                            ProductionAction.MOVE_RIGHT,
                        }
                        else action.value.title(),
                    )
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )
    window = PetWindow(
        clock=clock,
        track0=track0,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )

    sleep = window.request_pet_action(ProductionAction.SLEEP)
    resume = window.resume_pet_autonomous()

    assert sleep is ActionOutcome.ACCEPTED
    assert resume is ActionOutcome.ACCEPTED
    assert window.active_role_pack_id == "schwarz-production"
    assert window.available_pet_actions == frozenset(ProductionAction)
    assert [request.physical_name for request in player.requests] == [
        "Sleep",
        "Relax",
    ]
    window.complete_safe_close()


def test_real_qt_mouse_chain_drags_production_window_with_relax_fallback(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    track0 = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(
                        action,
                        "Move"
                        if action
                        in {
                            ProductionAction.MOVE_LEFT,
                            ProductionAction.MOVE_RIGHT,
                        }
                        else action.value.title(),
                    )
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )
    window = PetWindow(
        clock=clock,
        track0=track0,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )
    window.show()
    original = window.pos()

    QTest.mousePress(
        window,
        Qt.MouseButton.LeftButton,
        pos=QPoint(80, 90),
    )
    assert window.motion_state is PetMotionState.IDLE

    QTest.mouseMove(window, QPoint(30, 30))
    assert window.motion_state is PetMotionState.DRAGGING
    assert player.requests[-1].physical_name == "Relax"
    assert player.requests[-1].loop
    assert window.pos() != original

    QTest.mouseRelease(
        window,
        Qt.MouseButton.LeftButton,
        pos=QPoint(30, 30),
    )
    assert window.motion_state in {
        PetMotionState.FALLING,
        PetMotionState.LANDING,
    }
    window.complete_safe_close()


def test_left_click_requests_interact_once_with_user_source(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    track0 = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(
                        action,
                        "Move"
                        if action
                        in {ProductionAction.MOVE_LEFT, ProductionAction.MOVE_RIGHT}
                        else action.value.title(),
                    )
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )
    window = PetWindow(
        clock=clock,
        track0=track0,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )
    window.show()

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))

    assert [request.physical_name for request in player.requests] == ["Interact"]
    assert track0.active_request is not None
    assert track0.active_request.source is ActionSource.USER
    assert window.motion_state is PetMotionState.IDLE
    window.complete_safe_close()


def test_pet_context_menu_exposes_and_dispatches_production_actions_as_user(
    qt_application: QApplication,
) -> None:
    clock = _Clock()
    player = _Player()
    track0 = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(
                        action,
                        "Move"
                        if action
                        in {ProductionAction.MOVE_LEFT, ProductionAction.MOVE_RIGHT}
                        else action.value.title(),
                    )
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )
    window = PetWindow(
        clock=clock,
        track0=track0,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )
    window.show()
    local = window.rect().center()
    context_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        local,
        window.mapToGlobal(local),
    )

    # Slice 6B: right click requests the Action Palette; the legacy native
    # QMenu is no longer the production Character route.
    palette_requests: list[bool] = []
    window.action_palette_requested.connect(
        lambda: palette_requests.append(True)
    )
    qt_application.sendEvent(window, context_event)
    popup = QApplication.activePopupWidget()

    assert palette_requests == [True]
    assert not isinstance(popup, QMenu)
    assert window.findChild(QMenu) is None
    # Opening the Palette executes zero application action.
    assert track0.active_request is None
    window.complete_safe_close()


def test_malformed_native_playback_event_is_contained_at_window_boundary(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    track0 = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(action, action.value.title())
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )
    window = PetWindow(
        clock=clock,
        track0=track0,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
        playback_event_source=_MalformedPlaybackSource(),  # type: ignore[arg-type]
    )

    window._advance_animation()
    window._advance_animation()

    assert window.active_role_pack_id == "placeholder"
    assert window.available_pet_actions == frozenset()
    window.complete_safe_close()

def _resume_window(clock: _Clock, player: _Player) -> PetWindow:
    track0 = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            AnimationRoleRegistry(
                {
                    action: RoleAnimationBinding(action, action.value.title())
                    for action in ProductionAction
                }
            ),
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=clock,
    )
    return PetWindow(
        clock=clock,
        track0=track0,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )


def test_pet_window_resume_guard_consumes_shared_capability_false(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    # The shared Qt-free capability alone decides the guard: even though
    # RELAX is available and the pet is not closing, a False capability
    # must refuse resume before any animation path runs.
    monkeypatch.setattr(
        "arkclaw.presentation.qt.pet.pet_window.can_resume_autonomous",
        lambda *, closing, available_actions: False,
    )
    clock = _Clock()
    player = _Player()
    window = _resume_window(clock, player)
    try:
        assert window.resume_pet_autonomous() is ActionOutcome.INVALID_SEQUENCE
    finally:
        window.complete_safe_close()
    assert player.requests == []


def test_pet_window_resume_executes_when_shared_capability_true(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    monkeypatch.setattr(
        "arkclaw.presentation.qt.pet.pet_window.can_resume_autonomous",
        lambda *, closing, available_actions: True,
    )
    clock = _Clock()
    player = _Player()
    window = _resume_window(clock, player)
    try:
        assert window.resume_pet_autonomous() is ActionOutcome.ACCEPTED
    finally:
        window.complete_safe_close()
    assert [request.physical_name for request in player.requests] == ["Relax"]
