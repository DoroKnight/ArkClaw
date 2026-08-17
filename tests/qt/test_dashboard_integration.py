"""Slice 7F - Production Desktop <-> Dashboard integration.

Authority: 07 section 11 (Desktop <-> Dashboard Relationship) and 08 section
4: one product, two presentations.  The Dashboard is a second top-level that
shares the authoritative ConversationContext / draft; the Dashboard never
creates a second draft model, never reaches into PetWindow, and opening it is
a pure presentation transition (zero Conversation, zero backend, zero command).

Contracts proven here:
- the Dashboard window is created lazily and reused (same object on reopen);
- Home Ask / Start Chat / Explore route to the correct pages;
- the Chat / Work composer binds the ONE authoritative draft (edits land in
  the real FrontendPresentationCoordinator model, no feedback loop);
- opening the Dashboard performs zero Conversation / zero backend mutation;
- close hides; reopen reuses the same window; no duplicate signal wiring;
- dispose is idempotent and leaves no owned top-level;
- two integration instances stay isolated (no stale window across teardown).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from arkclaw.presentation.dashboard_presentation import (
    ActiveCharacterSummary,
    CharacterAnimationSnapshot,
    DashboardPresentationModel,
    HomeSnapshot,
)
from arkclaw.presentation.qt.dashboard.dashboard_integration import (
    DashboardIntegration,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.dashboard.dashboard_window import DashboardWindow
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


def test_window_created_lazily_and_reused(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    assert integration.window is None
    first = integration.open()
    assert isinstance(first, DashboardWindow)
    assert integration.window is first
    second = integration.open()
    assert second is first
    integration.dispose()
    _flush(QApplication.instance())


def test_open_is_pure_presentation_transition(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    assert presentation.snapshot.conversation_context is None
    integration.open()
    assert presentation.snapshot.conversation_context is None
    integration.dispose()
    _flush(QApplication.instance())


def test_open_shows_real_dashboard_window(
    qt_application: QApplication,
) -> None:
    del qt_application
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    window = integration.open(DashboardPage.HOME)
    assert window.isVisible()
    assert window.width() == 1280
    assert window.height() == 800
    assert window.current_page is DashboardPage.HOME
    integration.dispose()
    _flush(QApplication.instance())


def test_home_ask_routes_to_chat_work(
    qt_application: QApplication,
) -> None:
    del qt_application
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    window = integration.open(DashboardPage.HOME)
    from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage

    home = window.page_widget(DashboardPage.HOME)
    assert isinstance(home, HomePage)
    home.ask_button().click()
    assert window.current_page is DashboardPage.CHAT_WORK
    integration.dispose()
    _flush(QApplication.instance())


def test_home_explore_routes_to_pages(
    qt_application: QApplication,
) -> None:
    del qt_application
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    window = integration.open(DashboardPage.HOME)
    from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage

    home = window.page_widget(DashboardPage.HOME)
    assert isinstance(home, HomePage)
    home.explore_chat_work_button().click()
    assert window.current_page is DashboardPage.CHAT_WORK
    home.explore_character_animation_button().click()
    assert window.current_page is DashboardPage.CHARACTER_ANIMATION
    integration.dispose()
    _flush(QApplication.instance())


def test_draft_ports_reach_authoritative_model(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    window = integration.open(DashboardPage.CHAT_WORK)
    from arkclaw.presentation.qt.dashboard.pages.chat_work_page import (
        ChatWorkPage,
    )

    chat = window.page_widget(DashboardPage.CHAT_WORK)
    assert isinstance(chat, ChatWorkPage)
    composer = chat.composer()
    composer.setFocus()
    QTest.keyClicks(composer, "hello dashboard")
    # Deliberate composer engagement opens the ONE authoritative context; the
    # first committed edit then lands in the real model-owned draft.
    assert presentation.snapshot.conversation_context is not None
    assert presentation.draft_snapshot.text == "hello dashboard"
    assert composer.toPlainText() == "hello dashboard"
    integration.dispose()
    _flush(QApplication.instance())


def test_composer_engagement_opens_conversation_only_on_input(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    window = integration.open(DashboardPage.CHAT_WORK)
    # Pure page navigation stays a zero-Conversation presentation transition.
    assert presentation.snapshot.conversation_context is None
    from arkclaw.presentation.qt.dashboard.pages.chat_work_page import (
        ChatWorkPage,
    )

    chat = window.page_widget(DashboardPage.CHAT_WORK)
    assert isinstance(chat, ChatWorkPage)
    composer = chat.composer()
    composer.setFocus()
    # Focus alone is not engagement: no input yet, no Conversation.
    assert presentation.snapshot.conversation_context is None
    QTest.keyClicks(composer, "engaged")
    assert presentation.snapshot.conversation_context is not None
    context_id = presentation.snapshot.conversation_context.context_id
    assert presentation.draft_snapshot.text == "engaged"
    # Later edits restore the SAME context; they never recreate or duplicate.
    QTest.keyClicks(composer, "!")
    assert presentation.snapshot.conversation_context.context_id == context_id
    assert presentation.draft_snapshot.text == "engaged!"
    integration.dispose()
    _flush(QApplication.instance())


def test_no_duplicate_draft_wiring_after_reopen(
    qt_application: QApplication,
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    integration.open(DashboardPage.CHAT_WORK)
    integration.close()
    integration.open(DashboardPage.CHAT_WORK)
    from arkclaw.presentation.qt.dashboard.pages.chat_work_page import (
        ChatWorkPage,
    )

    chat = integration.window.page_widget(DashboardPage.CHAT_WORK)
    assert isinstance(chat, ChatWorkPage)
    composer = chat.composer()
    composer.setFocus()
    QTest.keyClicks(composer, "once")
    assert presentation.snapshot.conversation_context is not None
    assert presentation.draft_snapshot.text == "once"
    assert composer.toPlainText() == "once"
    integration.dispose()
    _flush(QApplication.instance())


def test_restore_character_handler_invoked(
    qt_application: QApplication,
) -> None:
    del qt_application
    calls: list[str] = []

    def restore() -> None:
        calls.append("restore")

    integration = DashboardIntegration(
        FrontendPresentationCoordinator(),
        restore_character_handler=restore,
    )
    window = integration.open(DashboardPage.HOME)
    from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage

    home = window.page_widget(DashboardPage.HOME)
    assert isinstance(home, HomePage)
    home.restore_character_button().click()
    assert calls == ["restore"]
    integration.dispose()
    _flush(QApplication.instance())


def test_snapshots_are_applied_to_pages(
    qt_application: QApplication,
) -> None:
    del qt_application
    model = DashboardPresentationModel(
        home=HomeSnapshot(greeting="Good evening"),
        character=CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Liskarm"),
        ),
    )
    integration = DashboardIntegration(
        FrontendPresentationCoordinator(), model
    )
    window = integration.open(DashboardPage.HOME)
    from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage

    home = window.page_widget(DashboardPage.HOME)
    assert isinstance(home, HomePage)
    assert home.greeting_label().text() == "Good evening"
    integration.dispose()
    _flush(QApplication.instance())


def test_close_hides_and_reopen_shows_same_window(
    qt_application: QApplication,
) -> None:
    del qt_application
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    window = integration.open()
    integration.close()
    assert not window.isVisible()
    again = integration.open()
    assert again is window
    assert window.isVisible()
    integration.dispose()
    _flush(QApplication.instance())


def test_dispose_is_idempotent_and_leaves_no_toplevel(
    qt_application: QApplication,
) -> None:
    del qt_application
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    integration.open()
    integration.dispose()
    integration.dispose()
    _flush(QApplication.instance())
    assert not any(
        isinstance(widget, DashboardWindow)
        for widget in QApplication.topLevelWidgets()
    )


def test_cross_instance_isolation(
    qt_application: QApplication,
) -> None:
    del qt_application
    first = DashboardIntegration(FrontendPresentationCoordinator())
    first_window = first.open()
    assert first_window.isVisible()
    first.dispose()
    _flush(QApplication.instance())
    assert first_window not in QApplication.topLevelWidgets()

    second = DashboardIntegration(FrontendPresentationCoordinator())
    second_window = second.open()
    assert second_window is not first_window
    assert second_window.isVisible()
    dashboards = [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, DashboardWindow)
    ]
    assert dashboards == [second_window]
    second.dispose()
    _flush(QApplication.instance())
    assert second_window not in QApplication.topLevelWidgets()



class _StubBridge(QObject):
    """Minimal coordinator bridge (shutdown signal only)."""

    shutdown_finished = Signal(bool, str)


class _StubMainWindow:
    """Duck-typed MainWindow surface for the production seam test."""

    def request_safe_close(self) -> None:
        pass

    def show(self) -> None:
        pass

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


def test_production_coordinator_open_dashboard_seam(
    qt_application: QApplication,
) -> None:
    del qt_application
    from arkclaw.presentation.qt.pet.pet_window import PetWindow
    from arkclaw.presentation.qt.pet_application import (
        PetApplicationCoordinator,
    )

    coordinator = PetApplicationCoordinator(
        _StubBridge(),
        _StubMainWindow(),
        PetWindow(),
    )
    try:
        assert coordinator.dashboard_integration is None
        assert (
            coordinator.frontend_presentation.snapshot.conversation_context
            is None
        )
        coordinator.open_dashboard()
        integration = coordinator.dashboard_integration
        assert integration is not None
        window = integration.window
        assert isinstance(window, DashboardWindow)
        assert window.isVisible()
        # Opening the Dashboard is a pure presentation transition.
        assert (
            coordinator.frontend_presentation.snapshot.conversation_context
            is None
        )
        # Reuse: the SAME window is raised again, never a duplicate instance.
        coordinator.open_dashboard()
        assert integration.window is window
    finally:
        coordinator.dispose()
        _flush(QApplication.instance())
    assert not any(
        isinstance(widget, DashboardWindow)
        for widget in QApplication.topLevelWidgets()
    )
    # dispose is idempotent.
    coordinator.dispose()
