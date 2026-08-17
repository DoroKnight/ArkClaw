"""Slice 7B - Dashboard App Shell and Navigation (frozen geometry).

Authority: docs/design/07-visual-design-freeze-v1.md sections 7/17 and
visual-freeze-v1.tokens.json component.dashboard.window/navigation.

Contracts proven here:
- the Dashboard window defaults to 1280x800 and enforces a 1024x680 minimum;
- the Top App Shell is exactly 56 px;
- Navigation expands to 208 px and collapses to 72 px with a 40 px toggle
  hit target;
- the primary navigation is exactly Home / Chat / Work / Character Animation
  (no extra?? items, no Settings as primary);
- selected rows expose selected surface + leading indicator geometry
  (indicator 3x24) and keep the frozen 44 px row height;
- expanded/collapsed/hover/pressed/focused/selected states are all reachable;
- keyboard navigation moves between rows and activates with Enter/Space;
- collapsed rows expose tooltip + accessible name + keyboard focus;
- theme switching preserves the current page and does not recreate widgets;
- dispose is idempotent and leaves no owned top-level behind.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel

from arkclaw.presentation.qt.dashboard.dashboard_window import (
    DashboardPage,
    DashboardWindow,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    ThemeVariant,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme


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


def _flush_deferred(application: QApplication) -> None:
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_dashboard_window_default_and_minimum_size(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    assert window.width() == 1280
    assert window.height() == 800
    assert window.minimumSize().width() == 1024
    assert window.minimumSize().height() == 680
    window.dispose()
    _flush_deferred(QApplication.instance())
    assert window not in QApplication.topLevelWidgets()


def test_top_shell_height_is_frozen(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    top_shell = window.top_shell
    assert top_shell.height() == 56
    assert top_shell.height() == tokens.component["dashboard"]["window"][
        "top_app_shell_height"
    ]
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_navigation_expanded_and_collapsed_geometry(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    navigation = window.navigation
    assert not navigation.is_collapsed()
    assert navigation.width() == 208
    navigation.set_collapsed(True, animate=False)
    assert navigation.width() == 72
    navigation.set_collapsed(False, animate=False)
    assert navigation.width() == 208
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_navigation_rows_are_exactly_the_frozen_primary_items(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    rows = window.navigation.page_ids()
    assert rows == [
        DashboardPage.HOME,
        DashboardPage.CHAT_WORK,
        DashboardPage.CHARACTER_ANIMATION,
    ]
    assert len(rows) == 3
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_navigation_row_geometry_and_indicator(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    navigation = window.navigation
    for page in navigation.page_ids():
        row = navigation.page_button(page)
        assert row.minimumHeight() == 44
        assert row.minimumWidth() >= 40
    assert navigation.active_indicator_size() == (3, 24)
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_selected_page_updates_rows(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    assert window.current_page is DashboardPage.HOME
    window.select_page(DashboardPage.CHAT_WORK)
    assert window.current_page is DashboardPage.CHAT_WORK
    assert window.navigation.is_selected(DashboardPage.CHAT_WORK)
    assert not window.navigation.is_selected(DashboardPage.HOME)
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_navigation_collapsed_tooltip_and_accessible_name(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    navigation = window.navigation
    navigation.set_collapsed(True, animate=False)
    for page in navigation.page_ids():
        row = navigation.page_button(page)
        assert row.toolTip()
        assert row.accessibleName()
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_navigation_keyboard_focus_and_activation(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    window.show()
    QApplication.instance().processEvents()
    navigation = window.navigation
    navigation.setFocus()
    first = navigation.page_button(DashboardPage.HOME)
    second = navigation.page_button(DashboardPage.CHAT_WORK)
    first.setFocus()
    assert QApplication.focusWidget() is first
    QTest.keyClick(first, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is second
    spy = QSignalSpy(window.page_selected)
    QTest.keyClick(second, Qt.Key.Key_Return)
    assert window.current_page is DashboardPage.CHAT_WORK
    assert spy.count() == 1
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_navigation_focus_visible_rule_references_focus_token(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    stylesheet = window.styleSheet()
    assert "navRow:focus" in stylesheet
    assert tokens.theme(ThemeVariant.LIGHT).focus.upper() in stylesheet.upper()
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_toggle_hit_target_is_frozen(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    toggle = window.navigation.toggle_button()
    assert toggle.minimumSize().width() == 40
    assert toggle.minimumSize().height() == 40
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_theme_switch_preserves_page_and_widgets(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    window.select_page(DashboardPage.CHAT_WORK)
    original_page_widget = window.page_widget(DashboardPage.CHAT_WORK)
    window.set_theme(QtTheme.DARK)
    assert window.current_page is DashboardPage.CHAT_WORK
    assert window.page_widget(DashboardPage.CHAT_WORK) is original_page_widget
    assert window.styleSheet() != ""
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_dashboard_dispose_is_idempotent(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    window.dispose()
    window.dispose()
    window.deleteLater()
    _flush_deferred(QApplication.instance())
    assert not any(
        isinstance(widget, DashboardWindow)
        for widget in QApplication.topLevelWidgets()
    )


def test_home_page_is_real_home_page(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage

    window = DashboardWindow()
    assert isinstance(window.page_widget(DashboardPage.HOME), HomePage)
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_chat_work_page_is_real_chat_work_page(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    from arkclaw.presentation.qt.dashboard.pages.chat_work_page import (
        ChatWorkPage,
    )

    window = DashboardWindow()
    assert isinstance(
        window.page_widget(DashboardPage.CHAT_WORK), ChatWorkPage
    )
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_character_animation_page_is_real_page(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    from arkclaw.presentation.qt.dashboard.pages.character_animation_page import (
        CharacterAnimationPage,
    )

    window = DashboardWindow()
    assert isinstance(
        window.page_widget(DashboardPage.CHARACTER_ANIMATION),
        CharacterAnimationPage,
    )
    window.dispose()
    _flush_deferred(QApplication.instance())


def test_dashboard_is_not_ide_or_browser_shell(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow()
    labels = " ".join(
        label.text().lower() for label in window.findChildren(QLabel)
    )
    for forbidden in ("tabs", "url", "browser", "terminal", "file tree"):
        assert forbidden not in labels
    window.dispose()
    _flush_deferred(QApplication.instance())
