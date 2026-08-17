"""Slice 7D - Dashboard Chat / Work page (frozen geometry + state authority).

Authority: 07 section 9 and tokens component.dashboard.chat_work/composer/
attachment/artifact: page max 920, conversation column 720, Composer max 800
/ 104-240 / radius 24 / padding 16, Activity row min 36, Result max 720 /
radius 16 / padding 20, optional Context Pane 320 default closed.  The
Composer binds the authoritative ConversationDraftModel through the same
DraftHostSink convention as the Capsule; it never owns draft truth.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftSnapshot,
    DraftEditIntent,
)
from arkclaw.presentation.dashboard_presentation import (
    ActivityItem,
    ActivityState,
    AgentState,
    AttachmentItem,
    AttachmentState,
    ChatWorkSnapshot,
    ResultArtifact,
    ResultArtifactKind,
    ResultArtifactState,
)
from arkclaw.presentation.qt.dashboard.pages.chat_work_page import ChatWorkPage
from arkclaw.presentation.qt.theme.design_tokens import load_design_tokens
from arkclaw.presentation.qt.theme.icons import IconKind
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, apply_theme


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
    yield application


@pytest.fixture(scope="module")
def tokens():
    return load_design_tokens()


def _flush(application: QApplication) -> None:
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _show(page: QWidget, application: QApplication) -> None:
    page.show()
    application.processEvents()


def test_chat_work_frozen_geometry(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    assert page.content_max_width() == 920
    assert page.conversation_column_width() == 720
    composer_card = page.composer_card()
    assert composer_card.maximumWidth() == 800
    assert composer_card.minimumHeight() == 104
    assert composer_card.maximumHeight() == 240
    page.dispose()
    _flush(QApplication.instance())


def test_composer_multiline_and_submit(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    page.show()
    QApplication.instance().processEvents()
    composer = page.composer()
    composer.setFocus()
    spy = QSignalSpy(page.submit_requested)
    QTest.keyClicks(composer, "hello")
    assert composer.toPlainText() == "hello"
    QTest.keyClick(composer, Qt.Key.Key_Return)
    assert spy.count() == 1
    QTest.keyClick(
        composer,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert spy.count() == 1
    page.dispose()
    _flush(QApplication.instance())


def test_composer_emits_draft_edit_intents(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    page.show()
    QApplication.instance().processEvents()
    composer = page.composer()
    composer.setFocus()
    spy = QSignalSpy(page.edit_requested)
    QTest.keyClicks(composer, "abc")
    assert spy.count() >= 1
    last = spy.at(spy.count() - 1)
    intent = last[0]
    assert isinstance(intent, DraftEditIntent)
    assert intent.text == "abc"
    page.dispose()
    _flush(QApplication.instance())


def test_committed_edit_emits_conversation_requested(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    _show(page, QApplication.instance())
    composer = page.composer()
    spy = QSignalSpy(page.conversation_requested)
    QTest.keyClicks(composer, "ab")
    assert spy.count() == 2
    page.dispose()
    _flush(QApplication.instance())


def test_draft_ports_render_without_feedback_loop(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    page.show()
    QApplication.instance().processEvents()
    edits: list[DraftEditIntent] = []

    def edit_handler(intent: DraftEditIntent) -> None:
        edits.append(intent)

    page.attach_draft_ports(
        draft_edit_handler=edit_handler,
        submit_handler=lambda: None,
        draft_snapshot_provider=lambda: ConversationDraftSnapshot(
            text="", has_draft=False, revision=0, caret=0,
            selection=None, submitted_snapshot_identity=None,
        ),
    )
    page.render_draft(
        ConversationDraftSnapshot(
            text="authoritative",
            has_draft=True,
            revision=1,
            caret=12,
            selection=None,
            submitted_snapshot_identity=None,
        )
    )
    assert page.composer().toPlainText() == "authoritative"
    assert edits == []
    page.dispose()
    _flush(QApplication.instance())


def test_attachment_states_render_chips(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(
        ChatWorkSnapshot(
            attachments=(
                AttachmentItem("a.png", "image", AttachmentState.UPLOADING),
                AttachmentItem("b.txt", "file", AttachmentState.UPLOADED),
                AttachmentItem("c.pdf", "file", AttachmentState.FAILED),
            )
        )
    )
    chips = page.attachment_chips()
    assert len(chips) == 3
    failed = next(chip for chip in chips if chip.name() == "c.pdf")
    assert "Retry" in failed.state_text()
    retry = failed.retry_button()
    assert retry is not None and retry.isVisible()
    spy = QSignalSpy(page.retry_attachment_requested)
    retry.click()
    assert spy.count() == 1
    page.dispose()
    _flush(QApplication.instance())


def test_agent_states_drive_task_block(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    _show(page, QApplication.instance())
    assert not page.task_state_block().isVisible()
    page.apply_snapshot(
        ChatWorkSnapshot(
            agent_state=AgentState.WORKING,
            agent_task_title="Running palette tests",
        )
    )
    assert page.task_state_block().isVisible()
    assert "Running palette tests" in page.task_state_block().text()
    page.apply_snapshot(ChatWorkSnapshot())
    assert not page.task_state_block().isVisible()
    page.dispose()
    _flush(QApplication.instance())


def test_activity_rows_are_icon_plus_text(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    page.apply_snapshot(
        ChatWorkSnapshot(
            activity=(
                ActivityItem("Reading files", ActivityState.COMPLETED),
                ActivityItem("Running tests", ActivityState.CURRENT),
                ActivityItem("Deploy", ActivityState.FUTURE),
            )
        )
    )
    rows = page.activity_rows()
    assert len(rows) == 3
    assert rows[0].state() is ActivityState.COMPLETED
    assert rows[1].state() is ActivityState.CURRENT
    assert "Reading files" in rows[0].text()
    assert rows[0].icon_kind() is IconKind.ACTIVITY_COMPLETED
    assert rows[1].icon_kind() is IconKind.ACTIVITY_CURRENT
    page.dispose()
    _flush(QApplication.instance())


def test_result_artifact_card_and_actions(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    _show(page, QApplication.instance())
    assert not page.result_card().isVisible()
    page.apply_snapshot(
        ChatWorkSnapshot(
            result=ResultArtifact(
                kind=ResultArtifactKind.DOCUMENT,
                title="Palette Cutover Summary",
                summary="Right click now opens the Action Palette.",
                state=ResultArtifactState.AVAILABLE,
                actions=("preview", "open", "export_or_save"),
            )
        )
    )
    assert page.result_card().isVisible()
    assert page.result_card().maximumWidth() == 720
    assert page.result_title_label().text() == "Palette Cutover Summary"
    buttons = page.result_actions()
    assert [b.text() for b in buttons] == ["Preview", "Open", "Export / Save"]
    spy = QSignalSpy(page.artifact_action_requested)
    buttons[0].click()
    assert spy.count() == 1
    assert spy.at(0)[0] == "preview"
    page.dispose()
    _flush(QApplication.instance())


def test_optional_context_pane_default_closed_and_320(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    _show(page, QApplication.instance())
    assert not page.context_pane().isVisible()
    page.open_context_pane()
    assert page.context_pane().isVisible()
    assert page.context_pane().width() == 320
    assert page.context_pane().minimumWidth() == 320
    page.close_context_pane()
    assert not page.context_pane().isVisible()
    page.dispose()
    _flush(QApplication.instance())


def test_conversation_id_is_presented(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    page.apply_snapshot(ChatWorkSnapshot(conversation_id="arkclaw-conversation"))
    assert page.conversation_caption().text() == "arkclaw-conversation"
    page.dispose()
    _flush(QApplication.instance())


def test_chat_work_accessible_names_and_focus(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    assert page.composer().accessibleName()
    assert page.attach_button().accessibleName()
    assert page.send_button().accessibleName()
    assert page.composer().focusPolicy() is not Qt.FocusPolicy.NoFocus
    page.dispose()
    _flush(QApplication.instance())


def test_chat_work_theme_application(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage()
    apply_theme(page, QtTheme.LIGHT)
    assert "composerCard" in page.styleSheet()
    apply_theme(page, QtTheme.DARK)
    assert "composerCard" in page.styleSheet()
    page.dispose()
    _flush(QApplication.instance())
