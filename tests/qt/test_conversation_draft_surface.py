"""Slice 4 Qt surface characterization: draft binding, render safety, collapse.

Proves through the public host/model seam:
- widget edit intent -> authoritative model draft updated
- model render -> widget reflects snapshot, with no feedback loop / duplicate revision
- collapse/restore preserves the authoritative draft and visible editor content
- Character Left Click / Drag leave the draft untouched
- Enter submits an inert snapshot and never clears the draft
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from arkclaw.application.pet.pet_production_actions import (
    ProductionAction,
)
from arkclaw.application.pet.pet_role_pack import (
    AnimationRoleRegistry,
    RoleAnimationBinding,
    build_track0_animation_registry,
)
from arkclaw.application.pet.pet_track0 import (
    ActionOutcome,
    AnimationPlayerCapabilities,
    PetTrack0Controller,
    PlaybackRequest,
    PlaybackToken,
)
from arkclaw.presentation.conversation_draft_safety import DraftEditIntent
from arkclaw.presentation.frontend_presentation import (
    CloseConversationIntent,
    CollapseConversationIntent,
    ConversationOpenOrRestoreIntent,
    FrontendPresentationIntent,
    FrontendPresentationModel,
    FrontendPresentationResult,
    PresentationEffect,
)
from arkclaw.presentation.qt.conversation_surface_effect_sink import (
    ConversationSurfaceEffectSink,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.ui.conversation_capsule import ConversationCapsule


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
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


def _build_track0(player: _Player, clock: _Clock) -> PetTrack0Controller:
    return PetTrack0Controller(
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


class _SpyWindow(PetWindow):
    """Records public production action requests without changing behavior."""

    def __init__(self, **kwargs: object) -> None:
        self.user_actions: list[ProductionAction] = []
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def request_user_pet_action(
        self,
        action: ProductionAction,
    ) -> ActionOutcome:
        self.user_actions.append(action)
        return super().request_user_pet_action(action)


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


def _wire_capsule_to_coordinator(
    capsule: ConversationCapsule,
    coordinator: FrontendPresentationCoordinator,
) -> None:
    capsule.edit_requested.connect(coordinator.apply_draft_edit)


def test_widget_edit_updates_authoritative_model_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("draft-test-conversation")
    _wire_capsule_to_coordinator(capsule, coordinator)

    QTest.keyClicks(capsule.input_edit, "hello")
    QApplication.processEvents()

    snapshot = coordinator.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    # Each committed keystroke advances the revision deterministically.
    assert snapshot.revision == 5
    _dispose(capsule)


def test_render_draft_reflects_snapshot_without_feedback_loop(
    qt_application: QApplication,
) -> None:
    del qt_application
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("render-test-conversation")
    _wire_capsule_to_coordinator(capsule, coordinator)
    spy = QSignalSpy(capsule.edit_requested)

    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    before = coordinator.draft_snapshot
    capsule.render_draft(before)
    QApplication.processEvents()

    assert capsule.input_edit.toPlainText() == "hello"
    assert coordinator.draft_snapshot == before
    assert spy.count() == 0
    _dispose(capsule)


def test_render_draft_restores_caret_and_selection(
    qt_application: QApplication,
) -> None:
    del qt_application
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("caret-test-conversation")
    coordinator.apply_draft_edit(
        DraftEditIntent(text="hello", caret=5, selection=(1, 3))
    )

    capsule.render_draft(coordinator.draft_snapshot)

    cursor = capsule.input_edit.textCursor()
    assert capsule.input_edit.toPlainText() == "hello"
    assert cursor.hasSelection()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (1, 3)
    _dispose(capsule)


def test_render_draft_does_not_steal_external_focus(
    qt_application: QApplication,
) -> None:
    del qt_application
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("focus-test-conversation")
    external = QLineEdit()
    external.show()
    external.setFocus()
    QApplication.processEvents()
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))

    capsule.render_draft(coordinator.draft_snapshot)
    QApplication.processEvents()

    assert QApplication.focusWidget() is external
    _dispose(capsule)
    external.close()


def test_collapse_restore_preserves_draft_in_host(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "hello")
    QApplication.processEvents()
    draft_before = coordinator.draft_snapshot
    assert draft_before.text == "hello"

    coordinator.dispatch(CollapseConversationIntent())
    QApplication.processEvents()

    assert sink.host is host
    assert not host.isVisible()
    assert coordinator.draft_snapshot == draft_before

    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    QApplication.processEvents()

    assert sink.host is host
    assert host.isVisible()
    assert coordinator.draft_snapshot == draft_before
    assert host.input_edit.toPlainText() == "hello"
    # Restore reuses the exact same host instance; no second host exists.
    assert sink.host is host
    assert len(_capsule_widgets()) >= 1
    # Clean up the host so it cannot leak into later modules run in the
    # same process (test isolation).
    _dispose(host)


def test_enter_captures_inert_snapshot_without_clearing_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("submit-test-conversation")
    _wire_capsule_to_coordinator(capsule, coordinator)
    capsule.submit_requested.connect(coordinator.submit_draft)

    QTest.keyClicks(capsule.input_edit, "hello")
    QTest.keyClick(capsule.input_edit, Qt.Key.Key_Return)
    QApplication.processEvents()

    snapshot = coordinator.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    assert snapshot.submitted_snapshot_identity is not None
    _dispose(capsule)


def test_left_click_interacts_and_preserves_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    draft_before = coordinator.draft_snapshot

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))

    assert window.user_actions == [ProductionAction.INTERACT]
    assert [r.physical_name for r in player.requests] == ["Interact"]
    assert coordinator.draft_snapshot == draft_before
    assert len(coordinator.intents) == 1
    window.complete_safe_close()


def test_drag_preserves_draft_with_zero_interact(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _Clock()
    player = _Player()
    window, _ = _make_spy_window(player, clock)
    coordinator = _RecordingCoordinator()
    window.show()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    draft_before = coordinator.draft_snapshot

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    QTest.mouseMove(window, QPoint(30, 30))
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))

    assert window.user_actions == []
    assert all(
        request.physical_name != "Interact" for request in player.requests
    )
    assert coordinator.draft_snapshot == draft_before
    assert len(coordinator.intents) == 1
    window.complete_safe_close()


# --- Review-fix: caret-only binding (cursor move must reach the model) ---

def test_caret_only_movement_updates_model_without_revision(
    qt_application: QApplication,
) -> None:
    del qt_application
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("caret-only-conversation")
    capsule.edit_requested.connect(model.apply_draft_edit)
    capsule.show()
    capsule.input_edit.setFocus()
    QApplication.processEvents()

    QTest.keyClicks(capsule.input_edit, "hello")
    QApplication.processEvents()
    before = model.draft_snapshot
    assert before.caret == 5

    cursor = capsule.input_edit.textCursor()
    cursor.setPosition(2)
    capsule.input_edit.setTextCursor(cursor)
    QApplication.processEvents()

    snapshot = model.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.caret == 2
    assert snapshot.revision == before.revision
    _dispose(capsule)


# --- Review-fix: selection-only binding (selection must reach the model) ---

def test_selection_only_change_updates_model_without_revision(
    qt_application: QApplication,
) -> None:
    del qt_application
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("selection-only-conversation")
    capsule.edit_requested.connect(model.apply_draft_edit)
    capsule.show()
    capsule.input_edit.setFocus()
    QApplication.processEvents()

    QTest.keyClicks(capsule.input_edit, "hello")
    QApplication.processEvents()
    before = model.draft_snapshot

    cursor = capsule.input_edit.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
    capsule.input_edit.setTextCursor(cursor)
    QApplication.processEvents()

    snapshot = model.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.selection == (1, 3)
    assert snapshot.revision == before.revision
    _dispose(capsule)


# --- Review-fix: real Qt input-method event path (QInputMethodEvent) ---

def test_real_qt_input_method_preedit_reaches_model_without_commit(
    qt_application: QApplication,
) -> None:
    del qt_application
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("ime-preedit-conversation")
    capsule.edit_requested.connect(model.apply_draft_edit)
    capsule.show()
    capsule.input_edit.setFocus()
    QApplication.processEvents()

    QTest.keyClicks(capsule.input_edit, "hello")
    QApplication.processEvents()

    preedit_event = QInputMethodEvent("ni", [])
    QApplication.sendEvent(capsule.input_edit, preedit_event)
    QApplication.processEvents()

    snapshot = model.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.ime_composition == "ni"
    assert snapshot.revision == 5
    _dispose(capsule)


def test_real_qt_input_method_commit_updates_draft_once(
    qt_application: QApplication,
) -> None:
    del qt_application
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("ime-commit-conversation")
    capsule.edit_requested.connect(model.apply_draft_edit)
    capsule.show()
    capsule.input_edit.setFocus()
    QApplication.processEvents()

    QTest.keyClicks(capsule.input_edit, "hello")
    QApplication.processEvents()

    preedit_event = QInputMethodEvent("ni", [])
    QApplication.sendEvent(capsule.input_edit, preedit_event)
    QApplication.processEvents()
    assert model.draft_snapshot.ime_composition == "ni"

    commit_event = QInputMethodEvent("", [])
    commit_event.setCommitString("ni")
    QApplication.sendEvent(capsule.input_edit, commit_event)
    QApplication.processEvents()

    snapshot = model.draft_snapshot
    assert snapshot.text == "helloni"
    assert snapshot.ime_composition is None
    assert snapshot.revision == 6
    _dispose(capsule)


def test_submit_refused_while_qt_composition_active(
    qt_application: QApplication,
) -> None:
    del qt_application
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    capsule = ConversationCapsule("ime-submit-conversation")
    capsule.edit_requested.connect(model.apply_draft_edit)
    capsule.submit_requested.connect(model.submit_draft)
    capsule.show()
    capsule.input_edit.setFocus()
    QApplication.processEvents()

    QTest.keyClicks(capsule.input_edit, "hello")
    QApplication.processEvents()

    preedit_event = QInputMethodEvent("ni", [])
    QApplication.sendEvent(capsule.input_edit, preedit_event)
    QApplication.processEvents()
    assert model.draft_snapshot.ime_composition == "ni"

    QTest.keyClick(capsule.input_edit, Qt.Key.Key_Return)
    QApplication.processEvents()

    snapshot = model.draft_snapshot
    assert snapshot.submitted_snapshot_identity is None
    assert snapshot.text == "hello"
    _dispose(capsule)


# --- Review-fix: real host seam binding (no manual test wiring) ---

def test_sink_binding_routes_edit_to_authoritative_model(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "hello")
    QApplication.processEvents()

    assert coordinator.draft_snapshot.text == "hello"
    _dispose(host)


def test_enter_through_real_seam_captures_inert_snapshot(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "hello")
    QTest.keyClick(host.input_edit, Qt.Key.Key_Return)
    QApplication.processEvents()

    snapshot = coordinator.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    assert snapshot.submitted_snapshot_identity is not None
    _dispose(host)


def test_restore_auto_renders_authoritative_draft_without_manual_render(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    coordinator.dispatch(CollapseConversationIntent())
    QApplication.processEvents()
    assert not host.isVisible()

    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    QApplication.processEvents()

    assert host.isVisible()
    assert coordinator.draft_snapshot.text == "hello"
    assert host.input_edit.toPlainText() == "hello"
    _dispose(host)


def test_repeated_restore_does_not_duplicate_revision_increments(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "x")
    QApplication.processEvents()

    assert coordinator.draft_snapshot.text == "x"
    assert coordinator.draft_snapshot.revision == 1
    _dispose(host)


def _capsule_widgets() -> list[ConversationCapsule]:
    return [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, ConversationCapsule)
    ]


def _dispose(capsule: ConversationCapsule) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    capsule.close()
    capsule.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)






def _dispatch_discarding(
    coordinator: FrontendPresentationCoordinator,
) -> Callable[[FrontendPresentationIntent], None]:
    """Return a None-returning intent handler for the effect sink."""

    def handler(
        intent: FrontendPresentationIntent,
    ) -> None:
        coordinator.dispatch(intent)

    return handler
# --- Review-fix: Qt IME composition survives ordinary collapse/restore ---

def test_qt_ime_composition_survives_collapse_restore_without_commit(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "hello")
    QApplication.processEvents()
    assert coordinator.draft_snapshot.text == "hello"

    preedit_event = QInputMethodEvent("ni", [])
    QApplication.sendEvent(host.input_edit, preedit_event)
    QApplication.processEvents()
    before = coordinator.draft_snapshot
    assert before.ime_composition == "ni"

    coordinator.dispatch(CollapseConversationIntent())
    QApplication.processEvents()
    assert sink.host is host
    assert not host.isVisible()
    assert coordinator.draft_snapshot == before

    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    QApplication.processEvents()
    assert sink.host is host
    assert host.isVisible()

    after_restore = coordinator.draft_snapshot
    assert after_restore == before
    assert after_restore.text == "hello"
    assert after_restore.ime_composition == "ni"
    assert after_restore.revision == 5
    assert after_restore.submitted_snapshot_identity is None
    assert host.input_edit.toPlainText() == "hello"

    # Restore must not accidentally commit/discard the composition; submit
    # while the composition remains active is still refused.
    QTest.keyClick(host.input_edit, Qt.Key.Key_Return)
    QApplication.processEvents()
    final = coordinator.draft_snapshot
    assert final.text == "hello"
    assert final.ime_composition == "ni"
    assert final.revision == 5
    assert final.submitted_snapshot_identity is None
    _dispose(host)


# --- Review-fix: Close is visibility-only; active IME survives Close ---

def test_qt_ime_composition_survives_close_without_commit(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "hello")
    QApplication.processEvents()
    assert coordinator.draft_snapshot.text == "hello"

    preedit_event = QInputMethodEvent("ni", [])
    QApplication.sendEvent(host.input_edit, preedit_event)
    QApplication.processEvents()
    before = coordinator.draft_snapshot
    assert before.ime_composition == "ni"

    # Close is a visibility-only transition (05 2.1.3, 06 2.1.4): the host is
    # hidden but never destroyed, and the active IME composition must not be
    # submitted or destroyed by a Surface transition (06 8.1).
    coordinator.dispatch(CloseConversationIntent())
    QApplication.processEvents()
    assert sink.host is host
    assert not host.isVisible()
    assert coordinator.snapshot.conversation_context is not None
    assert coordinator.draft_snapshot == before
    assert coordinator.draft_snapshot.text == "hello"
    assert coordinator.draft_snapshot.ime_composition == "ni"

    # Restore the same host: the composition is still authoritative and
    # submit remains refused until the composition resolves.
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    QApplication.processEvents()
    assert sink.host is host
    assert host.isVisible()
    after_restore = coordinator.draft_snapshot
    assert after_restore == before
    assert after_restore.ime_composition == "ni"

    QTest.keyClick(host.input_edit, Qt.Key.Key_Return)
    QApplication.processEvents()
    final = coordinator.draft_snapshot
    assert final.text == "hello"
    assert final.ime_composition == "ni"
    assert final.revision == before.revision
    assert final.submitted_snapshot_identity is None
    _dispose(host)

