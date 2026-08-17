"""Dashboard primary navigation page identity (frozen IA).

Authority: docs/design/visual-freeze-v1.tokens.json product_model /
component.dashboard.navigation.items and 07 section 7.  The V1 primary
navigation is exactly Home / Chat / Work / Character Animation; Settings is
a top-shell auxiliary entry and is never a fourth primary page.
"""

from __future__ import annotations

from enum import StrEnum


class DashboardPage(StrEnum):
    HOME = "home"
    CHAT_WORK = "chat_work"
    CHARACTER_ANIMATION = "character_animation"


PAGE_LABELS: dict[DashboardPage, str] = {
    DashboardPage.HOME: "Home",
    DashboardPage.CHAT_WORK: "Chat / Work",
    DashboardPage.CHARACTER_ANIMATION: "Character Animation",
}



def page_label(page: DashboardPage) -> str:
    return PAGE_LABELS[page]
