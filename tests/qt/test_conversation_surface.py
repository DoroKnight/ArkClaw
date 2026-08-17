from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from arkclaw.presentation.conversation_anchor import (
    AnchorRect,
    place_conversation_capsule,
)
from arkclaw.presentation.frontend_presentation import (
    CloseConversationIntent,
    ConversationOpenOrRestoreIntent,
    PresentationEffectKind,
    PrimaryPresentation,
)
from arkclaw.presentation.qt.conversation_surface_effect_sink import (
    ConversationSurfaceEffectSink,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.ui.conversation_capsule import ConversationCapsule


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


def _capsule_widgets() -> list[ConversationCapsule]:
    return [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, ConversationCapsule)
    ]


def test_sink_starts_without_host(qt_application: QApplication) -> None:
    del qt_application

    sink = ConversationSurfaceEffectSink()

    assert sink.host is None
    assert _capsule_widgets() == []


def test_create_effect_lazily_creates_one_host(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)

    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    assert isinstance(sink.host, ConversationCapsule)
    assert len(_capsule_widgets()) == 1


def test_restore_reuses_same_host_without_duplicate(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)

    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    first_host = sink.host
    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    assert sink.host is first_host
    assert len(_capsule_widgets()) == 1


def test_close_with_unsent_draft_hides_host_and_preserves_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    QTest.keyClicks(host.input_edit, "hello")
    QApplication.processEvents()
    assert coordinator.draft_snapshot.text == "hello"

    coordinator.dispatch(CloseConversationIntent())
    QApplication.processEvents()

    # Close is a visibility-only transition (05 2.1.3, 06 2.1.4), never a
    # draft-discard authority (06 8.3): the host is hidden but stays alive
    # with its authoritative draft and logical context.
    assert sink.host is host
    assert not host.isVisible()
    assert coordinator.snapshot.conversation_context is not None
    assert coordinator.draft_snapshot.text == "hello"

    from PySide6.QtCore import QCoreApplication, QEvent

    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_open_emits_no_agent_or_backend_effect(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)

    result = coordinator.dispatch(ConversationOpenOrRestoreIntent())

    assert [effect.kind for effect in result.effects] == [
        PresentationEffectKind.CREATE_CONVERSATION,
        PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert len(_capsule_widgets()) == 1


def test_close_hides_host_without_destroy(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    host = sink.host
    assert host is not None

    coordinator.dispatch(CloseConversationIntent())
    QApplication.processEvents()

    # Close only changes UI visibility (05 2.1.3): the lazy host is hidden,
    # never destroyed, and remains the same instance with its context.
    assert sink.host is host
    assert not host.isVisible()
    assert len(_capsule_widgets()) == 1
    assert coordinator.snapshot.conversation_context is not None

    from PySide6.QtCore import QCoreApplication, QEvent

    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_focus_effect_resolves_to_conversation_input(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)

    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    assert sink.host is not None
    assert sink.host.input_edit.hasFocus()


def test_render_does_not_steal_external_focus(
    qt_application: QApplication,
) -> None:
    del qt_application
    capsule = ConversationCapsule("test-conversation")
    external = QLineEdit()
    external.show()
    external.setFocus()
    QApplication.processEvents()

    capsule.render_snapshot(None)
    QApplication.processEvents()

    assert QApplication.focusWidget() is external
    capsule.close()


def test_input_widget_is_ime_capable(
    qt_application: QApplication,
) -> None:
    del qt_application
    capsule = ConversationCapsule("test-conversation")

    assert capsule.input_edit.testAttribute(
        Qt.WidgetAttribute.WA_InputMethodEnabled
    )
    capsule.close()


def test_enter_emits_inert_submit_signal(
    qt_application: QApplication,
) -> None:
    del qt_application
    capsule = ConversationCapsule("test-conversation")
    submit_spy = QSignalSpy(capsule.submit_requested)

    QTest.keyClicks(capsule.input_edit, "hello")
    QTest.keyClick(capsule.input_edit, Qt.Key.Key_Return)

    assert submit_spy.count() == 1
    capsule.close()


def test_shift_enter_preserves_multiline_edit(
    qt_application: QApplication,
) -> None:
    del qt_application
    capsule = ConversationCapsule("test-conversation")
    submit_spy = QSignalSpy(capsule.submit_requested)

    QTest.keyClicks(capsule.input_edit, "line")
    QTest.keyClick(
        capsule.input_edit,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )

    assert submit_spy.count() == 0
    assert "\n" in capsule.input_edit.toPlainText()
    capsule.close()


def test_escape_emits_collapse_signal(
    qt_application: QApplication,
) -> None:
    del qt_application
    capsule = ConversationCapsule("test-conversation")
    collapse_spy = QSignalSpy(capsule.collapse_requested)

    QTest.keyClick(capsule.input_edit, Qt.Key.Key_Escape)

    assert collapse_spy.count() == 1
    capsule.close()

def test_escape_collapse_hides_same_host_and_restore_shows_it(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ConversationSurfaceEffectSink()
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(coordinator.dispatch)

    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    first_host = sink.host
    assert first_host is not None
    original_context = coordinator.snapshot.conversation_context
    assert original_context is not None

    QTest.keyClick(first_host.input_edit, Qt.Key.Key_Escape)
    QApplication.processEvents()

    assert sink.host is first_host
    assert not first_host.isVisible()
    assert coordinator.snapshot.primary_presentation is PrimaryPresentation.CHARACTER
    assert coordinator.snapshot.conversation_context is original_context

    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    assert sink.host is first_host
    assert first_host.isVisible()
    assert coordinator.snapshot.conversation_context is original_context
    assert len(_capsule_widgets()) == 1


def test_host_geometry_uses_computed_anchor_placement(
    qt_application: QApplication,
) -> None:
    del qt_application
    anchor = AnchorRect(100, 200, 200, 200)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (220, 300), work_area)
    capsule = ConversationCapsule("anchor-test-conversation")
    capsule.apply_anchor_placement(placement)

    assert capsule.x() == placement.rect.x
    assert capsule.y() == placement.rect.y
    assert capsule.width() == placement.rect.width
    assert capsule.height() == placement.rect.height
    capsule.close()
