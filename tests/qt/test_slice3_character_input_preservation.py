"""Slice 3 characterization: character input leaves the frontend seam inert.

This file freezes the 06/07/08 Slice 3 contract that the Slice 1-2 frontend
presentation infrastructure must not be triggered by Character pointer input:

- completed non-drag Left Click  -> exactly one existing Interact, zero Conversation
- valid Drag                    -> existing Drag/landing, zero Interact, zero Conversation
- rapid double click            -> every completed click follows Interact, no
                                   Conversation, no Interact delay or coalescing
- real Qt double click          -> the Qt MouseButtonDblClick injection adds no
                                   independent Interact/Conversation/Capsule
- Right Click                   -> existing native QMenu, zero Interact, zero Conversation

The frontend seam is composed as a sibling of the real production PetWindow
click chain with a recording adapter; no production wiring is added and no
Conversation host is created.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from arkclaw.application.pet.pet_production_actions import (
    ActionSource,
    ProductionAction,
)
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
from arkclaw.presentation.frontend_presentation import (
    ConversationOpenOrRestoreIntent,
    FrontendPresentationIntent,
    FrontendPresentationResult,
    FrontendPresentationSnapshot,
    PresentationEffect,
    PresentationEffectKind,
    PrimaryPresentation,
    SemanticFocusTarget,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


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


def _build_track0(
    player: _Player,
    clock: _Clock,
) -> PetTrack0Controller:
    return PetTrack0Controller(
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


class _SpyWindow(PetWindow):
    """Records the public production action requests without changing behavior."""

    def __init__(self, **kwargs: object) -> None:
        self.user_actions: list[ProductionAction] = []
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def request_user_pet_action(
        self,
        action: ProductionAction,
    ) -> ActionOutcome:
        self.user_actions.append(action)
        return super().request_user_pet_action(action)


def _make_window(
    player: _Player,
    clock: _Clock,
) -> tuple[PetWindow, PetTrack0Controller]:
    track0 = _build_track0(player, clock)
    return (
        PetWindow(
            clock=clock,
            track0=track0,
            active_role_pack_id="schwarz-production",
            available_production_actions=frozenset(ProductionAction),
        ),
        track0,
    )


def _make_spy_window(
    player: _Player,
    clock: _Clock,
) -> tuple[_SpyWindow, PetTrack0Controller]:
    track0 = _build_track0(player, clock)
    return (
        _SpyWindow(
            clock=clock,
            track0=track0,
            active_role_pack_id="schwarz-production",
            available_production_actions=frozenset(ProductionAction),
        ),
        track0,
    )


class _AppendingSink:
    def __init__(self, effects: list[PresentationEffect]) -> None:
        self._effects = effects

    def apply(self, effect: PresentationEffect) -> None:
        self._effects.append(effect)


class _RecordingCoordinator(FrontendPresentationCoordinator):
    """Records public intents and effects without owning presentation truth."""

    def __init__(self) -> None:
        self.intents: list[FrontendPresentationIntent] = []
        self.effects: list[PresentationEffect] = []
        super().__init__(effect_sink=_AppendingSink(self.effects))

    def dispatch(
        self,
        intent: FrontendPresentationIntent,
    ) -> FrontendPresentationResult:
        self.intents.append(intent)
        return super().dispatch(intent)


def _assert_character_snapshot(snapshot: FrontendPresentationSnapshot) -> None:
    assert snapshot.primary_presentation is PrimaryPresentation.CHARACTER
    assert snapshot.conversation_context is None
    assert snapshot.semantic_focus_target is SemanticFocusTarget.NONE


def _assert_zero_conversation_effects(
    coordinator: _RecordingCoordinator,
    baseline_intents: int,
    baseline_effects: int,
) -> None:
    assert len(coordinator.intents) == baseline_intents
    assert len(coordinator.effects) == baseline_effects
    assert all(
        effect.kind
        not in {
            PresentationEffectKind.CREATE_CONVERSATION,
            PresentationEffectKind.RESTORE_CONVERSATION,
            PresentationEffectKind.HIDE_CONVERSATION,
            PresentationEffectKind.CLOSE_CONVERSATION,
        }
        for effect in coordinator.effects
    )


def test_left_click_interacts_exactly_once_with_zero_conversation(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, track0 = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))

    assert window.user_actions == [ProductionAction.INTERACT]
    assert [request.physical_name for request in player.requests] == ["Interact"]
    assert track0.active_request is not None
    assert track0.active_request.source is ActionSource.USER
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)
    window.complete_safe_close()


def test_left_click_does_not_mutate_an_open_conversation_context(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()

    opened = coordinator.dispatch(ConversationOpenOrRestoreIntent())
    snapshot_before = coordinator.snapshot
    assert snapshot_before.primary_presentation is PrimaryPresentation.CAPSULE
    assert snapshot_before.conversation_context is not None
    assert (
        snapshot_before.semantic_focus_target
        is SemanticFocusTarget.CONVERSATION_INPUT
    )

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))

    assert window.user_actions == [ProductionAction.INTERACT]
    assert [request.physical_name for request in player.requests] == ["Interact"]
    assert coordinator.snapshot == snapshot_before
    assert len(coordinator.intents) == 1
    assert len(coordinator.effects) == len(opened.effects)
    window.complete_safe_close()


def test_drag_is_drag_only_with_zero_interact_and_zero_conversation(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()
    original = window.pos()

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    motion_after_press = window.motion_state
    assert motion_after_press is PetMotionState.IDLE
    assert player.requests == []

    QTest.mouseMove(window, QPoint(30, 30))
    motion_after_move = window.motion_state
    assert motion_after_move is PetMotionState.DRAGGING
    assert player.requests[-1].physical_name == "Relax"
    assert player.requests[-1].loop
    assert window.pos() != original

    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    motion_after_release = window.motion_state
    assert motion_after_release in {
        PetMotionState.FALLING,
        PetMotionState.LANDING,
    }

    assert all(
        request.physical_name != "Interact" for request in player.requests
    )
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)
    window.complete_safe_close()


def test_drag_preserves_an_open_conversation_context(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()

    opened = coordinator.dispatch(ConversationOpenOrRestoreIntent())
    snapshot_before = coordinator.snapshot
    assert snapshot_before.conversation_context is not None

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    QTest.mouseMove(window, QPoint(30, 30))
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))

    motion_after_release = window.motion_state
    assert motion_after_release in {
        PetMotionState.FALLING,
        PetMotionState.LANDING,
    }
    assert all(
        request.physical_name != "Interact" for request in player.requests
    )
    assert coordinator.snapshot == snapshot_before
    assert len(coordinator.intents) == 1
    assert len(coordinator.effects) == len(opened.effects)
    window.complete_safe_close()


def test_rapid_double_click_has_no_conversation_semantic_and_no_interact_delay(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    assert window.user_actions == [ProductionAction.INTERACT]
    assert [request.physical_name for request in player.requests] == ["Interact"]

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))

    assert window.user_actions == [
        ProductionAction.INTERACT,
        ProductionAction.INTERACT,
    ]
    assert [request.physical_name for request in player.requests] == ["Interact"]
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)
    window.complete_safe_close()


def test_real_qt_double_click_has_no_conversation_and_no_extra_interact(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()
    position = QPoint(80, 90)

    # First click of the double-click sequence: press + release completes a
    # normal non-drag Left Click and requests exactly one Interact.
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=position)
    assert window.user_actions == [ProductionAction.INTERACT]
    assert [request.physical_name for request in player.requests] == ["Interact"]

    # The real Qt MouseButtonDblClick injection (QTest.mouseDClick) must not
    # add any independent Character action: no extra Interact, no
    # Conversation, no Capsule, snapshot unchanged.
    QTest.mouseDClick(window, Qt.MouseButton.LeftButton, pos=position)
    assert window.user_actions == [ProductionAction.INTERACT]
    assert [request.physical_name for request in player.requests] == ["Interact"]
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)

    # The trailing release completes the second click through the ordinary
    # PetPointerGesture CLICK path, exactly like a second rapid click:
    # still only Interact, zero Conversation, snapshot unchanged.
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=position)
    assert window.user_actions == [
        ProductionAction.INTERACT,
        ProductionAction.INTERACT,
    ]
    assert [request.physical_name for request in player.requests] == ["Interact"]
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)
    window.complete_safe_close()


def test_qt_dblclick_event_alone_has_no_character_semantic(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()

    QTest.mouseDClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))

    assert window.user_actions == []
    assert player.requests == []
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)
    window.complete_safe_close()


def test_right_click_opens_native_menu_with_zero_interact_and_zero_conversation(
    qt_application: QApplication,
) -> None:
    clock = _Clock()
    player = _Player()
    window, _ = _make_window(player, clock)
    coordinator = _RecordingCoordinator()
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
    assert player.requests == []
    _assert_character_snapshot(coordinator.snapshot)
    _assert_zero_conversation_effects(coordinator, 0, 0)
    window.complete_safe_close()
