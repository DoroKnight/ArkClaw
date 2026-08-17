"""Slice 7C - Dashboard Home page (frozen geometry + states).

Authority: docs/design/07-visual-design-freeze-v1.md section 8 and
visual-freeze-v1.tokens.json component.dashboard.home: content max 1040,
top pad 40, gutter 40/32, greeting 28/36/600, Ask max 720 x 64 / radius 24,
section gap 32, card padding 20, recent card min 280 x 112 (max 3),
Active Character Summary 320 x 220, Explore -> Chat / Work and Character
Animation.  No metrics, charts, CPU/RAM, KPI, or fake data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from arkclaw.presentation.dashboard_presentation import (
    ActiveCharacterSummary,
    AgentState,
    HomeSnapshot,
    RecentWorkItem,
)
from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage
from arkclaw.presentation.qt.theme.design_tokens import load_design_tokens
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


def _visible_cards(page: HomePage) -> list:
    return [card for card in page.recent_cards() if card.isVisible()]


def test_home_content_max_width_and_gutter(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    assert page.content_max_width() == 1040
    assert page.gutter() == 40
    page.set_compact_gutter(True)
    assert page.gutter() == 32
    page.set_compact_gutter(False)
    assert page.gutter() == 40
    page.dispose()
    _flush(QApplication.instance())


def test_ask_entry_geometry_matches_freeze(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    ask = page.ask_button()
    assert ask.maximumWidth() == 720
    assert ask.minimumHeight() == 64
    page.dispose()
    _flush(QApplication.instance())


def test_recent_card_geometry_and_max_three(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    page.apply_snapshot(
        HomeSnapshot(
            recent_work=(
                RecentWorkItem("One"),
                RecentWorkItem("Two"),
                RecentWorkItem("Three"),
                RecentWorkItem("Four"),
            )
        )
    )
    cards = page.recent_cards()
    assert len(cards) == 3
    for card in cards:
        assert card.minimumWidth() >= 280
        assert card.minimumHeight() >= 112
    page.dispose()
    _flush(QApplication.instance())


def test_first_launch_shows_welcome_and_explore(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    _show(page, QApplication.instance())
    page.apply_snapshot(HomeSnapshot(first_launch=True, greeting="Welcome to ArkClaw"))
    assert page.greeting_label().text() == "Welcome to ArkClaw"
    assert page.greeting_label().isVisible()
    assert page.ask_button().isVisible()
    assert page.explore_chat_work_button().isVisible()
    assert page.explore_character_animation_button().isVisible()
    assert _visible_cards(page) == []
    assert not page.no_recent_block().isVisible()
    page.dispose()
    _flush(QApplication.instance())


def test_no_recent_work_shows_explanation_and_start(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    _show(page, QApplication.instance())
    page.apply_snapshot(HomeSnapshot())
    assert page.no_recent_block().isVisible()
    assert page.start_chat_work_button().isVisible()
    assert _visible_cards(page) == []
    page.dispose()
    _flush(QApplication.instance())


def test_recent_work_renders_titles(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    _show(page, QApplication.instance())
    page.apply_snapshot(
        HomeSnapshot(
            recent_work=(RecentWorkItem("Palette cutover", "Chat / Work"),)
        )
    )
    visible = _visible_cards(page)
    assert len(visible) == 1
    assert visible[0].text() == "Palette cutover"
    assert not page.no_recent_block().isVisible()
    page.dispose()
    _flush(QApplication.instance())


def test_agent_working_shows_light_task_state(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    _show(page, QApplication.instance())
    assert not page.task_state_block().isVisible()
    page.apply_snapshot(
        HomeSnapshot(
            agent_state=AgentState.WORKING,
            agent_task_title="Running palette tests",
        )
    )
    assert page.task_state_block().isVisible()
    assert "Running palette tests" in page.task_state_block().text()
    page.dispose()
    _flush(QApplication.instance())


def test_character_unavailable_is_inline_and_page_survives(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    _show(page, QApplication.instance())
    page.apply_snapshot(
        HomeSnapshot(
            greeting="Hello",
            active_character=ActiveCharacterSummary(
                available=False,
                unavailable_reason="Spine assets are missing",
            ),
        )
    )
    assert page.greeting_label().isVisible()
    assert page.character_card().isVisible()
    assert "Spine assets are missing" in page.character_reason_label().text()
    assert page.restore_character_button().isVisible()
    page.dispose()
    _flush(QApplication.instance())


def test_character_summary_uses_frozen_product_term(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    page.apply_snapshot(
        HomeSnapshot(
            active_character=ActiveCharacterSummary(
                display_name="Schwarz",
                is_reference=True,
                reference_name="Schwarz",
            )
        )
    )
    assert tokens.product_term in page.character_title_label().text()
    assert "Schwarz" in page.character_name_label().text()
    assert "Reference Character: Schwarz" in page.character_caption_label().text()
    page.dispose()
    _flush(QApplication.instance())


def test_home_signals(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    page.show()
    QApplication.instance().processEvents()
    spies = {
        name: QSignalSpy(getattr(page, name))
        for name in (
            "ask_requested",
            "start_chat_work_requested",
            "explore_chat_work_requested",
            "explore_character_animation_requested",
            "restore_character_requested",
        )
    }
    page.ask_button().click()
    page.start_chat_work_button().click()
    page.explore_chat_work_button().click()
    page.explore_character_animation_button().click()
    page.restore_character_button().click()
    for name, spy in spies.items():
        assert spy.count() == 1, name
    page.dispose()
    _flush(QApplication.instance())


def test_home_accessible_names_and_focus(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    assert page.ask_button().accessibleName()
    assert page.start_chat_work_button().accessibleName()
    assert page.explore_chat_work_button().accessibleName()
    assert page.explore_character_animation_button().accessibleName()
    assert page.ask_button().focusPolicy() is not Qt.FocusPolicy.NoFocus
    page.dispose()
    _flush(QApplication.instance())


def test_home_theme_applies_and_keeps_greeting_rule(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = HomePage()
    apply_theme(page, QtTheme.LIGHT)
    stylesheet = page.styleSheet()
    assert "homeGreeting" in stylesheet
    assert "homeAsk" in stylesheet
    apply_theme(page, QtTheme.DARK)
    assert "homeGreeting" in page.styleSheet()
    page.dispose()
    _flush(QApplication.instance())
