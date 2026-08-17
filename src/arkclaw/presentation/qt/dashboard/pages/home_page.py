"""Dashboard Home page (Slice 7C).

Authority: 07 section 8 and tokens component.dashboard.home.  The page is a
pure presentation surface: it renders a
:class:`~arkclaw.presentation.dashboard_presentation.HomeSnapshot` and emits
narrow navigation intents (Ask / Start Chat / Explore / Restore character).
It never owns backend truth; empty and unavailable states come from the
snapshot, never from fabricated data (no CPU/RAM/KPI/charts).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from arkclaw.presentation.dashboard_presentation import (
    AgentState,
    HomeSnapshot,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import (
    PAGE_LABELS,
    DashboardPage,
)
from arkclaw.presentation.qt.dashboard.pages._widgets import TaskStateBlock
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)


class _RecentCard(QFrame):
    """One Continue Recent Work card (frozen min 280 x 112)."""

    def __init__(
        self,
        tokens: DesignTokens,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("surfaceCard")
        home = tokens.component["dashboard"]["home"]
        self.setMinimumSize(
            int(home["recent_card_min_width"]),
            int(home["recent_card_min_height"]),
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            int(home["card_padding"]),
            int(home["card_padding"]),
            int(home["card_padding"]),
            int(home["card_padding"]),
        )
        layout.setSpacing(4)
        self._title = QLabel(self)
        self._title.setObjectName("textPrimary")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        self._subtitle = QLabel(self)
        self._subtitle.setObjectName("textCaption")
        layout.addWidget(self._subtitle)
        layout.addStretch(1)
        self.setVisible(False)

    def set_item(self, title: str, subtitle: str) -> None:
        self._title.setText(title)
        self._subtitle.setText(subtitle)

    def text(self) -> str:
        return self._title.text()


class HomePage(QWidget):
    """Frozen Home layout: greeting, Ask, recent work, character, Explore."""

    ask_requested = Signal()
    start_chat_work_requested = Signal()
    explore_chat_work_requested = Signal()
    explore_character_animation_requested = Signal()
    restore_character_requested = Signal()

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else load_design_tokens()
        self._disposed = False
        self._snapshot = HomeSnapshot()
        self.setObjectName("homePage")
        home = self._tokens.component["dashboard"]["home"]
        window = self._tokens.component["dashboard"]["window"]
        self._content_max_width = int(home["content_max_width"])
        self._page_gutter = int(window["page_gutter"])
        self._compact_gutter = int(window["compact_gutter"])
        self._gutter = self._page_gutter
        self._top_padding = int(home["top_padding"])
        self._section_gap = int(home["section_gap"])
        self._max_recent = int(home["recent_card_max_count"])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("homeScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        scroll_content = QWidget()
        scroll_content.setObjectName("homeScrollContent")
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._apply_margins(self._scroll_layout)
        self._scroll_layout.setSpacing(0)

        column = QWidget(scroll_content)
        column.setMaximumWidth(self._content_max_width)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(self._section_gap)
        self._scroll_layout.addWidget(
            column, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self._scroll_layout.addStretch(1)

        scroll.setWidget(scroll_content)
        outer.addWidget(scroll)

        self._greeting = QLabel(column)
        self._greeting.setObjectName("homeGreeting")
        self._greeting.setWordWrap(True)
        column_layout.addWidget(self._greeting)

        self._intro = QLabel(column)
        self._intro.setObjectName("homeIntro")
        self._intro.setWordWrap(True)
        column_layout.addWidget(self._intro)

        self._ask = QPushButton("Ask ArkClaw\u2026", column)
        self._ask.setObjectName("homeAsk")
        self._ask.setMinimumHeight(int(home["ask_height"]))
        self._ask.setMaximumWidth(int(home["ask_max_width"]))
        self._ask.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ask.setAccessibleName("Primary ask")
        self._ask.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._ask.clicked.connect(self.ask_requested)
        column_layout.addWidget(self._ask)

        self._task_state = TaskStateBlock(column)
        column_layout.addWidget(self._task_state)

        self._recent_title = QLabel(
            "Continue Recent Work", column
        )
        self._recent_title.setObjectName("sectionTitle")
        column_layout.addWidget(self._recent_title)

        self._recent_cards: list[_RecentCard] = []
        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(16)
        for _ in range(self._max_recent):
            card = _RecentCard(self._tokens, self)
            cards_row.addWidget(card, 1)
            self._recent_cards.append(card)
        column_layout.addLayout(cards_row)

        self._no_recent = QWidget(column)
        no_layout = QVBoxLayout(self._no_recent)
        no_layout.setContentsMargins(0, 0, 0, 0)
        no_layout.setSpacing(8)
        self._no_recent_text = QLabel(
            "No recent work yet. Start a chat or work session to see it here.",
            self._no_recent,
        )
        self._no_recent_text.setObjectName("textSecondary")
        self._no_recent_text.setWordWrap(True)
        no_layout.addWidget(self._no_recent_text)
        self._start_chat_work = QPushButton(
            "Start Chat / Work", self._no_recent
        )
        self._start_chat_work.setObjectName("primaryButton")
        self._start_chat_work.setAccessibleName("Start Chat / Work")
        self._start_chat_work.clicked.connect(self.start_chat_work_requested)
        no_layout.addWidget(self._start_chat_work, 0, Qt.AlignmentFlag.AlignLeft)
        column_layout.addWidget(self._no_recent)

        self._character_title = QLabel(
            self._tokens.product_term, column
        )
        self._character_title.setObjectName("sectionTitle")
        column_layout.addWidget(self._character_title)

        self._character_card = QFrame(column)
        self._character_card.setObjectName("surfaceCard")
        summary_w = int(home["active_character_summary_width"])
        summary_h = int(home["active_character_summary_height"])
        self._character_card.setMinimumSize(summary_w, summary_h)
        self._character_card.setMaximumWidth(summary_w)
        card_layout = QVBoxLayout(self._character_card)
        card_layout.setContentsMargins(
            int(home["card_padding"]),
            int(home["card_padding"]),
            int(home["card_padding"]),
            int(home["card_padding"]),
        )
        card_layout.setSpacing(4)
        self._character_name = QLabel(self._character_card)
        self._character_name.setObjectName("pageTitle")
        card_layout.addWidget(self._character_name)
        self._character_caption = QLabel(self._character_card)
        self._character_caption.setObjectName("textCaption")
        card_layout.addWidget(self._character_caption)
        self._character_reason = QLabel(self._character_card)
        self._character_reason.setObjectName("textSecondary")
        self._character_reason.setWordWrap(True)
        self._character_reason.setVisible(False)
        card_layout.addWidget(self._character_reason)
        self._restore_character = QPushButton("Restore", self._character_card)
        self._restore_character.setObjectName("secondaryButton")
        self._restore_character.setAccessibleName("Restore Active Character")
        self._restore_character.clicked.connect(
            self.restore_character_requested
        )
        self._restore_character.setVisible(False)
        card_layout.addWidget(
            self._restore_character, 0, Qt.AlignmentFlag.AlignLeft
        )
        card_layout.addStretch(1)
        column_layout.addWidget(self._character_card, 0, Qt.AlignmentFlag.AlignLeft)

        self._explore_title = QLabel("Explore", column)
        self._explore_title.setObjectName("sectionTitle")
        column_layout.addWidget(self._explore_title)
        explore_row = QHBoxLayout()
        explore_row.setContentsMargins(0, 0, 0, 0)
        explore_row.setSpacing(12)
        self._explore_chat_work = QPushButton(
            PAGE_LABELS[DashboardPage.CHAT_WORK], column
        )
        self._explore_chat_work.setObjectName("secondaryButton")
        self._explore_chat_work.setAccessibleName("Open Chat / Work")
        self._explore_chat_work.clicked.connect(
            self.explore_chat_work_requested
        )
        explore_row.addWidget(self._explore_chat_work)
        self._explore_character_animation = QPushButton(
            PAGE_LABELS[DashboardPage.CHARACTER_ANIMATION], column
        )
        self._explore_character_animation.setObjectName("secondaryButton")
        self._explore_character_animation.setAccessibleName(
            "Open Character Animation"
        )
        self._explore_character_animation.clicked.connect(
            self.explore_character_animation_requested
        )
        explore_row.addWidget(self._explore_character_animation)
        explore_row.addStretch(1)
        column_layout.addLayout(explore_row)

        self.apply_snapshot(self._snapshot)

    # -- public geometry ----------------------------------------------------
    def content_max_width(self) -> int:
        return self._content_max_width

    def gutter(self) -> int:
        return self._gutter

    def set_compact_gutter(self, compact: bool) -> None:
        self._gutter = self._compact_gutter if compact else self._page_gutter
        self._apply_margins(self._scroll_layout)

    def _apply_margins(self, layout: QVBoxLayout) -> None:
        layout.setContentsMargins(
            self._gutter,
            self._top_padding,
            self._gutter,
            self._gutter,
        )

    # -- accessors ----------------------------------------------------------
    def greeting_label(self) -> QLabel:
        return self._greeting

    def ask_button(self) -> QPushButton:
        return self._ask

    def task_state_block(self) -> TaskStateBlock:
        return self._task_state

    def recent_cards(self) -> list[_RecentCard]:
        return list(self._recent_cards)

    def no_recent_block(self) -> QWidget:
        return self._no_recent

    def start_chat_work_button(self) -> QPushButton:
        return self._start_chat_work

    def character_card(self) -> QFrame:
        return self._character_card

    def character_title_label(self) -> QLabel:
        return self._character_title

    def character_name_label(self) -> QLabel:
        return self._character_name

    def character_caption_label(self) -> QLabel:
        return self._character_caption

    def character_reason_label(self) -> QLabel:
        return self._character_reason

    def restore_character_button(self) -> QPushButton:
        return self._restore_character

    def explore_chat_work_button(self) -> QPushButton:
        return self._explore_chat_work

    def explore_character_animation_button(self) -> QPushButton:
        return self._explore_character_animation

    # -- state --------------------------------------------------------------
    def apply_snapshot(self, snapshot: HomeSnapshot) -> None:
        self._snapshot = snapshot
        self._greeting.setText(snapshot.greeting)
        self._intro.setText(snapshot.intro)

        working = (
            snapshot.agent_state is not AgentState.IDLE
            and bool(snapshot.agent_task_title)
        )
        self._task_state.setVisible(working)
        if working and snapshot.agent_task_title is not None:
            self._task_state.set_task(snapshot.agent_task_title)

        has_recent = bool(snapshot.recent_work)
        self._recent_title.setVisible(not snapshot.first_launch)
        for index, card in enumerate(self._recent_cards):
            visible = (
                not snapshot.first_launch
                and index < len(snapshot.recent_work)
            )
            card.setVisible(visible)
            if visible:
                item = snapshot.recent_work[index]
                card.set_item(item.title, item.subtitle)
        self._no_recent.setVisible(
            not snapshot.first_launch and not has_recent
        )

        character = snapshot.active_character
        self._character_name.setText(
            character.display_name or "\u2014"
        )
        if character.is_reference and character.reference_name:
            self._character_caption.setText(
                f"Reference Character: {character.reference_name}"
            )
            self._character_caption.setVisible(True)
        else:
            self._character_caption.setVisible(False)
        if not character.available:
            self._character_reason.setText(
                character.unavailable_reason or "Active Character unavailable"
            )
            self._character_reason.setVisible(True)
            self._restore_character.setVisible(True)
        else:
            self._character_reason.setVisible(False)
            self._restore_character.setVisible(False)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.hide()
        self.deleteLater()
