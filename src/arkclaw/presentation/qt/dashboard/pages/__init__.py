"""Dashboard pages package (7C-7E real pages, 7B shell fallback).

Home (7C), Chat / Work (7D) and Character Animation (7E) are real pages; the
placeholder builder remains only for unforeseen future pages.  No page owns
backend or conversation truth; pages render presentation snapshots and emit
narrow navigation intents.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from arkclaw.presentation.qt.dashboard.dashboard_page import (
    PAGE_LABELS,
    DashboardPage,
)
from arkclaw.presentation.qt.dashboard.pages.character_animation_page import (
    CharacterAnimationPage,
)
from arkclaw.presentation.qt.dashboard.pages.chat_work_page import ChatWorkPage
from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage
from arkclaw.presentation.qt.theme.design_tokens import DesignTokens


def build_page(
    page: DashboardPage,
    tokens: DesignTokens,
) -> QWidget:
    """Build the real page widget for ``page`` (7C-7E progressive)."""
    if page is DashboardPage.HOME:
        return HomePage(tokens)
    if page is DashboardPage.CHAT_WORK:
        return ChatWorkPage(tokens)
    if page is DashboardPage.CHARACTER_ANIMATION:
        return CharacterAnimationPage(tokens)
    return build_placeholder_page(page, tokens)


def build_placeholder_page(
    page: DashboardPage,
    tokens: DesignTokens,
) -> QWidget:
    """Placeholder page used by the 7B shell until the real pages land."""
    del tokens
    widget = QWidget()
    widget.setObjectName(f"page-{page.value}")
    layout = QVBoxLayout(widget)
    layout.addStretch(1)
    label = QLabel(PAGE_LABELS[page], widget)
    label.setObjectName("pageTitle")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(label)
    layout.addStretch(1)
    return widget
