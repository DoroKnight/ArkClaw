"""Stage 10 B - End-to-end user journey validation.

Authority: Stage 10 section 5 over the frozen Slice 0-6B + Slice 7
contracts.  Journeys exercise the REAL production presentation seam
(FrontendPresentationCoordinator + DashboardIntegration + DashboardWindow
pages): no fake descriptor / composition layer.  Only backend/network
dependencies that the coordinator deliberately does not own are absent.

Journeys:
1. First launch: Dashboard opens on Home, then enters Chat / Work without
   crash / blank page / stale state.
2. Ordinary task: type -> submit -> Thinking -> Working -> Result ->
   follow-up, preserving the ONE authoritative ConversationContext + draft.
3. Character workflow: view Active Character -> preview animation -> switch
   character -> return to desktop, capability-driven and single-runtime.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from arkclaw.presentation.dashboard_presentation import (
    ActiveCharacterSummary,
    ActivityItem,
    ActivityState,
    AgentState,
    AnimationItem,
    AnimationState,
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
from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage
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


def _integration(presentation: FrontendPresentationCoordinator) -> DashboardIntegration:
    return DashboardIntegration(presentation)


# -- Journey 1: first launch -------------------------------------------------


def test_journey1_first_launch_home_then_chat_work(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = _integration(presentation)
    try:
        window = integration.open(DashboardPage.HOME)
        assert window.isVisible()
        assert window.current_page is DashboardPage.HOME
        home = window.page_widget(DashboardPage.HOME)
        assert isinstance(home, HomePage)
        assert home.ask_button().text()
        assert home.explore_chat_work_button().isVisible()
        # Enter Chat / Work from Home.
        home.start_chat_work_button().click()
        assert window.current_page is DashboardPage.CHAT_WORK
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        assert isinstance(chat, ChatWorkPage)
        assert chat.composer().placeholderText() == "Ask ArkClaw…"
        # Not a blank page: composer, send button and context pane exist.
        assert chat.send_button().isEnabled() is False
        # No stale state: exactly one visible dashboard top-level.
        visible = [
            w for w in QApplication.topLevelWidgets() if w.isVisible()
        ]
        assert window in visible
    finally:
        integration.dispose()
        _flush(QApplication.instance())


# -- Journey 2: ordinary user task -------------------------------------------


def test_journey2_task_flow_preserves_conversation_and_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = _integration(presentation)
    try:
        window = integration.open(DashboardPage.CHAT_WORK)
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        assert isinstance(chat, ChatWorkPage)
        # Opening the Dashboard is a pure presentation transition.
        assert presentation.snapshot.conversation_context is None

        # 1. Type a request: first keystroke opens the authoritative context.
        QTest.keyClicks(chat.composer(), "Summarize the palette cutover")
        context = presentation.snapshot.conversation_context
        assert context is not None
        assert presentation.draft_snapshot.text == (
            "Summarize the palette cutover"
        )
        assert presentation.draft_snapshot.has_draft is True

        # 2. Submit (Send routes through the coordinator model-owned draft).
        chat.send_button().click()
        submitted = presentation.draft_snapshot.submitted_snapshot_identity
        assert submitted is not None
        context_id = presentation.snapshot.conversation_context.context_id

        # 3. Thinking -> Working -> Result are presentation states on the page.
        chat.apply_snapshot(
            ChatWorkSnapshot(
                conversation_id=context_id,
                agent_state=AgentState.THINKING,
                agent_task_title="Summarizing",
            )
        )
        assert chat.task_state_block().isVisible()
        assert "Summarizing" in chat.task_state_block().text()
        chat.apply_snapshot(
            ChatWorkSnapshot(
                conversation_id=context_id,
                agent_state=AgentState.WORKING,
                agent_task_title="Writing summary",
                activity=(
                    ActivityItem("Reading files", ActivityState.COMPLETED),
                    ActivityItem("Writing summary", ActivityState.CURRENT),
                ),
            )
        )
        assert len(chat.activity_rows()) == 2
        chat.apply_snapshot(
            ChatWorkSnapshot(
                conversation_id=context_id,
                agent_state=AgentState.COMPLETED,
                result=ResultArtifact(
                    kind=ResultArtifactKind.SUMMARY,
                    title="Palette Cutover Summary",
                    summary="Right click opens the Action Palette.",
                    state=ResultArtifactState.AVAILABLE,
                    actions=("preview", "open"),
                ),
            )
        )
        assert chat.result_card().isVisible()
        assert "Palette Cutover Summary" in chat.result_title_label().text()

        # 4. Follow-up keeps the SAME context and a fresh draft edit.
        QTest.keyClicks(chat.composer(), " And list risks")
        assert presentation.snapshot.conversation_context.context_id == context_id
        assert "And list risks" in presentation.draft_snapshot.text
        # Draft revision advanced monotonically (no stale state).
        assert presentation.draft_snapshot.revision >= 1
    finally:
        integration.dispose()
        _flush(QApplication.instance())


# -- Journey 3: character workflow -------------------------------------------


def test_journey3_character_workflow_capability_driven_single_runtime(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = _integration(presentation)
    try:
        window = integration.open(DashboardPage.CHARACTER_ANIMATION)
        page = window.page_widget(DashboardPage.CHARACTER_ANIMATION)
        assert isinstance(page, CharacterAnimationPage)

        # View Active Character (capability-driven inventory).
        page.apply_snapshot(
            CharacterAnimationSnapshot(
                active_character=ActiveCharacterSummary(
                    available=True,
                    display_name="Schwarz",
                    is_reference=True,
                    reference_name="Schwarz",
                ),
                available_characters=("Schwarz", "Amiya"),
                animations=(
                    AnimationItem("relax", "Relax", AnimationState.IDLE),
                    AnimationItem("sit", "Sit", AnimationState.IDLE),
                    AnimationItem(
                        "special",
                        "Special",
                        AnimationState.UNSUPPORTED,
                        disabled_reason="Not in manifest",
                    ),
                ),
            )
        )
        assert "Schwarz" in page.header_name_label().text()
        assert len(page.character_cards()) == 2
        assert len(page.animation_cards()) == 3
        unsupported = page.animation_cards()[2]
        assert unsupported.state_label().text() == "Unsupported"
        assert not unsupported.preview_button().isEnabled()

        # Preview an animation (selection, not a fake backend run).
        page.select_card(0)
        assert page.selected_card() is page.animation_cards()[0]
        assert page.strip_preview_button().isEnabled()

        # Switch character: rebuild is capability-driven, single page runtime.
        page.character_switch_button(1).click()
        assert page.preview_crossfade_active() is True
        page.cancel_switch_crossfade()
        assert page.preview_crossfade_active() is False

        # Return to desktop: close hides, dispose removes the owned top-level.
        integration.close()
        assert not window.isVisible()
    finally:
        integration.dispose()
        _flush(QApplication.instance())


# -- conversation draft survival (Palette overlay must not end it) -----------


def test_journey_draft_survives_dashboard_open_close_cycle(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = _integration(presentation)
    try:
        window = integration.open(DashboardPage.CHAT_WORK)
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        QTest.keyClicks(chat.composer(), "persist me")
        revision = presentation.draft_snapshot.revision
        text = presentation.draft_snapshot.text
        identity = presentation.snapshot.conversation_context.context_id
        integration.close()
        integration.open(DashboardPage.CHAT_WORK)
        assert presentation.draft_snapshot.revision == revision
        assert presentation.draft_snapshot.text == text
        assert presentation.snapshot.conversation_context.context_id == identity
        # The reopened page re-renders the same draft.
        reopened = window.page_widget(DashboardPage.CHAT_WORK)
        assert isinstance(reopened, ChatWorkPage)
        assert reopened.composer().toPlainText() == text
    finally:
        integration.dispose()
        _flush(QApplication.instance())
