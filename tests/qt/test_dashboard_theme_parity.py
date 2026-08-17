"""Slice 7G - Dashboard Light/Dark parity, min-window and keyboard gates.

Authority: 07 sections 12-14 (Light / Dark / Accessibility / Motion) and
tokens: Light and Dark share one semantic token contract, every major
component must render in both, theme switching is state-driven and preserves
page + draft, the Dashboard minimum is 1024x680, and focus must never be
swallowed by the stylesheet.  All frozen dimensions are logical px.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from arkclaw.presentation.qt.dashboard.dashboard_integration import (
    DashboardIntegration,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.dashboard.dashboard_window import DashboardWindow
from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    ThemeVariant,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import (
    QtTheme,
    build_theme_stylesheet,
)


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


def test_light_and_dark_use_same_semantic_contract(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    light = build_theme_stylesheet(QtTheme.LIGHT, tokens)
    dark = build_theme_stylesheet(QtTheme.DARK, tokens)
    # Identical semantic selectors in both themes.
    for selector in (
        "QWidget#appRoot",
        "QWidget#topShell",
        "QWidget#navigationPane",
        "QLabel#pageTitle",
        "QPushButton#primaryButton",
        "QPushButton#secondaryButton",
        "QTextEdit#composerInput",
        "QWidget#attachChip",
    ):
        assert selector in light
        assert selector in dark
    light_bg = tokens.theme(ThemeVariant.LIGHT).surface.background
    dark_bg = tokens.theme(ThemeVariant.DARK).surface.background
    assert light_bg != dark_bg
    assert light_bg in light
    assert dark_bg in dark
    # Dark must not be a neon/glow theme: it reuses the frozen semantic tokens.
    assert "glow" not in dark.lower()


def test_dashboard_window_switches_dark_and_back(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow(tokens)
    light_bg = tokens.theme(ThemeVariant.LIGHT).surface.background
    dark_bg = tokens.theme(ThemeVariant.DARK).surface.background
    assert light_bg in window.styleSheet()
    window.set_theme(QtTheme.DARK)
    assert dark_bg in window.styleSheet()
    assert light_bg not in window.styleSheet()
    # State-driven switch preserves the current page.
    window.select_page(DashboardPage.CHARACTER_ANIMATION)
    window.set_theme(QtTheme.LIGHT)
    assert light_bg in window.styleSheet()
    assert window.current_page is DashboardPage.CHARACTER_ANIMATION
    window.dispose()
    _flush(QApplication.instance())


def test_dark_parity_all_pages_visible(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow(tokens)
    window.show()
    QApplication.instance().processEvents()
    window.set_theme(QtTheme.DARK)
    for page in DashboardPage:
        window.select_page(page)
        _flush(QApplication.instance())
        assert window.page_widget(page).isVisible()
    window.dispose()
    _flush(QApplication.instance())


def test_theme_switch_preserves_draft_and_composer(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation, tokens=tokens)
    window = integration.open(DashboardPage.CHAT_WORK)
    from arkclaw.presentation.qt.dashboard.pages.chat_work_page import (
        ChatWorkPage,
    )

    chat = window.page_widget(DashboardPage.CHAT_WORK)
    assert isinstance(chat, ChatWorkPage)
    composer = chat.composer()
    composer.setFocus()
    QTest.keyClicks(composer, "theme keeps draft")
    assert presentation.draft_snapshot.text == "theme keeps draft"
    window.set_theme(QtTheme.DARK)
    window.set_theme(QtTheme.LIGHT)
    assert composer.toPlainText() == "theme keeps draft"
    assert presentation.draft_snapshot.text == "theme keeps draft"
    assert window.current_page is DashboardPage.CHAT_WORK
    integration.dispose()
    _flush(QApplication.instance())


def test_minimum_window_geometry_holds(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow(tokens)
    window.show()
    QApplication.instance().processEvents()
    window.resize(
        int(tokens.component["dashboard"]["window"]["minimum_width"]),
        int(tokens.component["dashboard"]["window"]["minimum_height"]),
    )
    _flush(QApplication.instance())
    assert window.width() == 1024
    assert window.height() == 680
    assert window.top_shell.height() == 56
    assert window.navigation.width() == 208
    # Expanded navigation leaves a usable page area; no overflow crash.
    page_area_width = window.width() - window.navigation.width()
    assert page_area_width > 0
    for page in DashboardPage:
        window.select_page(page)
        widget = window.page_widget(page)
        _flush(QApplication.instance())
        assert widget.isVisible()
        assert widget.width() <= page_area_width
    # Collapsed navigation still leaves more room at the minimum width.
    window.navigation.set_collapsed(True)
    _flush(QApplication.instance())
    assert window.navigation.width() == 72
    assert window.width() - window.navigation.width() > page_area_width
    window.dispose()
    _flush(QApplication.instance())


def test_keyboard_space_activates_home_ask(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    integration = DashboardIntegration(
        FrontendPresentationCoordinator(), tokens=tokens
    )
    window = integration.open(DashboardPage.HOME)
    home = window.page_widget(DashboardPage.HOME)
    assert isinstance(home, HomePage)
    ask = home.ask_button()
    assert isinstance(ask, QPushButton)
    ask.setFocus()
    QApplication.instance().processEvents()
    assert QApplication.focusWidget() is ask
    QTest.keyClick(ask, Qt.Key.Key_Space)
    assert window.current_page is DashboardPage.CHAT_WORK
    integration.dispose()
    _flush(QApplication.instance())


def test_frozen_dimensions_are_logical_px(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    # The frozen token contract declares logical px; Qt applies widget sizes
    # in logical px, so devicePixelRatio never multiplies them.
    assert tokens.units == "qt_logical_px"
    window = DashboardWindow(tokens)
    assert window.size().width() == int(
        tokens.component["dashboard"]["window"]["default_width"]
    )
    assert window.size().height() == int(
        tokens.component["dashboard"]["window"]["default_height"]
    )
    assert window.minimumSize().width() == int(
        tokens.component["dashboard"]["window"]["minimum_width"]
    )
    assert window.minimumSize().height() == int(
        tokens.component["dashboard"]["window"]["minimum_height"]
    )
    window.dispose()
    _flush(QApplication.instance())
