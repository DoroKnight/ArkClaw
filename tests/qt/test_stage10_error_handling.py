"""Stage 10 E - V1 explicit failure behavior.

Authority: Stage 10 section 8 - failures must render an error state with a
recovery action, never a blank screen; Agent failure must preserve the
authoritative context and draft; unsupported capabilities stay readable and
disabled instead of faking availability.

Contracts proven here:
- Agent Error renders on Chat / Work while the conversation context and
  draft survive and the composer stays usable for follow-up;
- a failed Result artifact renders "Failed" plus its capability-driven
  recovery actions;
- a missing Spine resource renders Unavailable + reason + Retry recovery on
  the Character Animation page while the rest of the Dashboard stays usable;
- unsupported / too-large attachments are readable and offer no fake retry.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from arkclaw.presentation.dashboard_presentation import (
    ActiveCharacterSummary,
    AgentState,
    AttachmentItem,
    AttachmentState,
    CharacterAnimationSnapshot,
    ChatWorkSnapshot,
    ResultArtifact,
    ResultArtifactKind,
    ResultArtifactState,
)
from arkclaw.presentation.qt.dashboard.dashboard_integration import (
    DashboardIntegration,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.dashboard.pages.character_animation_page import (
    CharacterAnimationPage,
)
from arkclaw.presentation.qt.dashboard.pages.chat_work_page import ChatWorkPage
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
    yield application


def _flush(application: QApplication) -> None:
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_agent_error_preserves_context_and_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    try:
        window = integration.open(DashboardPage.CHAT_WORK)
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        assert isinstance(chat, ChatWorkPage)
        QTest.keyClicks(chat.composer(), "draft before error")
        context_id = presentation.snapshot.conversation_context.context_id
        revision = presentation.draft_snapshot.revision

        chat.apply_snapshot(
            ChatWorkSnapshot(
                conversation_id=context_id,
                agent_state=AgentState.ERROR,
                agent_task_title="Task failed",
            )
        )
        assert chat.task_state_block().isVisible()
        assert "Error" in chat.task_state_block().text()

        # Context and draft survive the failure.
        assert presentation.snapshot.conversation_context.context_id == context_id
        assert presentation.draft_snapshot.revision == revision
        assert presentation.draft_snapshot.text == "draft before error"

        # Composer stays usable for follow-up.
        QTest.keyClicks(chat.composer(), " and retry")
        assert presentation.draft_snapshot.text == "draft before error and retry"
    finally:
        integration.dispose()
        _flush(application)


def test_failed_result_renders_with_recovery_actions(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    try:
        window = integration.open(DashboardPage.CHAT_WORK)
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        assert isinstance(chat, ChatWorkPage)
        chat.apply_snapshot(
            ChatWorkSnapshot(
                agent_state=AgentState.COMPLETED,
                result=ResultArtifact(
                    kind=ResultArtifactKind.DOCUMENT,
                    title="Broken Export",
                    summary="Export failed mid-write.",
                    state=ResultArtifactState.FAILED,
                    actions=("open", "export_or_save"),
                ),
            )
        )
        assert chat.result_card().isVisible()
        assert chat.result_state_label().isVisible()
        assert chat.result_state_label().text() == "Failed"
        labels = [button.text() for button in chat.result_actions()]
        assert "Open" in labels
        assert "Export / Save" in labels
    finally:
        integration.dispose()
        _flush(application)


def test_missing_character_resource_shows_unavailable_and_retry(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    try:
        window = integration.open(DashboardPage.CHARACTER_ANIMATION)
        page = window.page_widget(DashboardPage.CHARACTER_ANIMATION)
        assert isinstance(page, CharacterAnimationPage)
        page.apply_snapshot(
            CharacterAnimationSnapshot(
                active_character=ActiveCharacterSummary(
                    available=False,
                    display_name="",
                    unavailable_reason="Spine pack missing",
                ),
                preview_error="Spine renderer failed to start",
            )
        )
        assert "renderer" in page.preview_status_label().text().lower()
        retry = page.preview_retry_button()
        assert retry.isVisible()
        spy = QSignalSpy(page.preview_retry_requested)
        retry.click()
        assert spy.count() == 1
        # The rest of the Dashboard stays usable after the failure.
        window.select_page(DashboardPage.HOME)
        assert window.current_page is DashboardPage.HOME
    finally:
        integration.dispose()
        _flush(application)


def test_unsupported_and_too_large_attachments_are_readable_without_retry(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    try:
        window = integration.open(DashboardPage.CHAT_WORK)
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        assert isinstance(chat, ChatWorkPage)
        chat.apply_snapshot(
            ChatWorkSnapshot(
                attachments=(
                    AttachmentItem(
                        "x.xyz",
                        "file",
                        AttachmentState.UNSUPPORTED,
                    ),
                    AttachmentItem(
                        "big.bin",
                        "file",
                        AttachmentState.TOO_LARGE,
                    ),
                )
            )
        )
        chips = chat.attachment_chips()
        assert len(chips) == 2
        assert chips[0].state_text() == "Unsupported"
        assert chips[1].state_text() == "Too large"
        # No fake retry for non-retryable states.
        assert not chips[0].retry_button().isVisible()
        assert not chips[1].retry_button().isVisible()
    finally:
        integration.dispose()
        _flush(application)
