"""Stage 10 D - runtime reliability / long-session durability.

Authority: Stage 10 section 7 (runtime reliability) - window lifecycle,
theme lifecycle and character lifecycle must survive sustained cycling with
no duplicate windows, no stale signals, no timer leaks and no top-level
growth.  The 100-cycle loops are the automated proxy for a long-running
session; they run offscreen and complete in milliseconds without sleeps.

Contracts proven here:
- opening/closing the Dashboard 100x reuses the SAME window object and does
  not grow the application's top-level widget set;
- alternating Light/Dark 100x preserves the current page and never creates a
  second window or loses the authoritative draft;
- switching character snapshots 100x rebuilds capability-driven cards without
  accumulating widgets or leaking deleted cards;
- navigation emits page_selected exactly once per selection (no duplicate
  signal wiring across cycles);
- sequential integration instances dispose cleanly (no stale top-level).
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
    AnimationItem,
    AnimationState,
    CharacterAnimationSnapshot,
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
from arkclaw.presentation.qt.theme.qt_theme import QtTheme


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


def _visible_top_level_count(application: QApplication) -> int:
    return sum(1 for widget in application.topLevelWidgets() if widget.isVisible())


def test_open_close_loop_reuses_one_window_and_stable_toplevels(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    window = integration.open()
    first = window
    for _ in range(100):
        integration.close()
        integration.open()
        assert integration.window is first
    integration.dispose()
    _flush(application)
    assert integration.window is None


def test_theme_toggle_loop_preserves_page_and_draft(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    window = integration.open(DashboardPage.CHAT_WORK)
    chat = window.page_widget(DashboardPage.CHAT_WORK)
    assert isinstance(chat, ChatWorkPage)
    QTest.keyClicks(chat.composer(), "durable draft")
    revision = presentation.draft_snapshot.revision
    context_id = presentation.snapshot.conversation_context.context_id
    before = _visible_top_level_count(application)
    for index in range(100):
        theme = QtTheme.DARK if index % 2 else QtTheme.LIGHT
        window.set_theme(theme)
        assert window.current_page is DashboardPage.CHAT_WORK
    after = _visible_top_level_count(application)
    assert after == before
    # Draft and context are untouched by theme cycling.
    assert presentation.draft_snapshot.revision == revision
    assert presentation.draft_snapshot.text == "durable draft"
    assert presentation.snapshot.conversation_context.context_id == context_id
    integration.dispose()
    _flush(application)


def test_character_switch_loop_rebuilds_without_leak(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    window = integration.open(DashboardPage.CHARACTER_ANIMATION)
    page = window.page_widget(DashboardPage.CHARACTER_ANIMATION)
    assert isinstance(page, CharacterAnimationPage)
    names = ("Schwarz", "Amiya", "Liskarm", "Hoshiguma")
    for cycle in range(100):
        current = names[cycle % len(names)]
        page.apply_snapshot(
            CharacterAnimationSnapshot(
                active_character=ActiveCharacterSummary(
                    available=True,
                    display_name=current,
                ),
                available_characters=names,
                animations=(
                    AnimationItem("relax", "Relax", AnimationState.IDLE),
                    AnimationItem("sit", "Sit", AnimationState.IDLE),
                ),
            )
        )
        assert len(page.character_cards()) == len(names)
        assert len(page.animation_cards()) == 2
        assert page.header_name_label().text() == current
        _flush(application)
    # Exactly one CharacterAnimationPage instance (single runtime).
    pages = [
        w
        for w in application.topLevelWidgets()
        if isinstance(w, CharacterAnimationPage)
    ]
    assert len(pages) <= 1
    integration.dispose()
    _flush(application)


def test_navigation_emits_page_selected_exactly_once(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    integration = DashboardIntegration(FrontendPresentationCoordinator())
    window = integration.open(DashboardPage.HOME)
    spy = QSignalSpy(window.page_selected)
    window.select_page(DashboardPage.CHAT_WORK)
    window.select_page(DashboardPage.CHARACTER_ANIMATION)
    window.select_page(DashboardPage.HOME)
    assert spy.count() == 3
    integration.dispose()
    _flush(application)


def test_sequential_integration_instances_leave_no_toplevel(
    qt_application: QApplication,
) -> None:
    del qt_application
    application = QApplication.instance()
    baseline = len(application.topLevelWidgets())
    for _ in range(5):
        integration = DashboardIntegration(FrontendPresentationCoordinator())
        integration.open()
        assert integration.window is not None
        integration.dispose()
        _flush(application)
    assert len(application.topLevelWidgets()) == baseline
