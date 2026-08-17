"""Dashboard Chat / Work page (Slice 7D).

Authority: 07 section 9 and tokens component.dashboard.chat_work/composer/
attachment/artifact.  The page renders a
:class:`~arkclaw.presentation.dashboard_presentation.ChatWorkSnapshot` and
binds the one authoritative
:class:`~arkclaw.presentation.conversation_draft_safety.ConversationDraftModel`
through the same DraftHostSink convention as the Capsule (07 11, 07 17):
``attach_draft_ports`` routes host edit/submit intents to the model-owned
draft and ``render_draft`` renders its snapshot without a feedback loop.  The
page never owns draft truth, never predicts future activity, and never
fabricates attachments or results.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QInputMethodEvent, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftSnapshot,
    DraftEditIntent,
    SubmittedDraftSnapshot,
)
from arkclaw.presentation.dashboard_presentation import (
    ActivityItem,
    AgentState,
    AttachmentItem,
    ChatWorkSnapshot,
    ResultArtifact,
    ResultArtifactKind,
    ResultArtifactState,
)
from arkclaw.presentation.qt.dashboard.pages._widgets import (
    ActivityRow,
    AttachmentChip,
    TaskStateBlock,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.icons import (
    IconKind,
    icon_color_for_theme,
    icon_pixmap,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme

_RESULT_KIND_TEXT = {
    ResultArtifactKind.SUMMARY: "Summary",
    ResultArtifactKind.DOCUMENT: "Document",
    ResultArtifactKind.FILE: "File",
    ResultArtifactKind.GENERATED_ASSET: "Generated asset",
    ResultArtifactKind.CODE_ARTIFACT: "Code artifact",
    ResultArtifactKind.GENERIC: "Result",
}

_RESULT_ACTION_TEXT = {
    "preview": "Preview",
    "open": "Open",
    "export_or_save": "Export / Save",
}

_STATE_ACTION_TEXT = {
    AgentState.SUBMITTED: "Submitted",
    AgentState.THINKING: "Thinking",
    AgentState.WORKING: "Working",
    AgentState.WAITING: "Waiting",
    AgentState.NEEDS_ATTENTION: "Needs attention",
    AgentState.COMPLETED: "Completed",
    AgentState.ERROR: "Error",
}


class _ComposerInput(QTextEdit):
    """Composer input with IME-safe submit semantics (07 9 Composer)."""

    submit_requested = Signal()
    preedit_changed = Signal(str)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        preedit = event.preeditString()
        super().inputMethodEvent(event)
        self.preedit_changed.emit(preedit)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ChatWorkMode(StrEnum):
    """Segmented modes for Chat / Work presentation (Visual Amendment v1.1)."""

    CHAT = "chat"
    WORK = "work"


class ChatWorkPage(QWidget):
    """Frozen Chat / Work layout: Conversation, Task, Activity, Result, Composer."""

    submit_requested = Signal()
    edit_requested = Signal(object)
    conversation_requested = Signal()
    attach_requested = Signal()
    retry_attachment_requested = Signal(str)
    remove_attachment_requested = Signal(str)
    artifact_action_requested = Signal(str)
    mode_changed = Signal(object)

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else load_design_tokens()
        self._disposed = False
        self._mode = ChatWorkMode.CHAT
        self._snapshot = ChatWorkSnapshot()
        self._draft_edit_handler: (
            Callable[[DraftEditIntent], None] | None
        ) = None
        self._submit_handler: (
            Callable[[], SubmittedDraftSnapshot | None] | None
        ) = None
        self._draft_snapshot_provider: (
            Callable[[], ConversationDraftSnapshot] | None
        ) = None
        self._draft_ports_attached = False
        self._rendering_draft = False
        self._composition_active = False
        self.setObjectName("chatWorkPage")

        chat = self._tokens.component["dashboard"]["chat_work"]
        composer = self._tokens.component["dashboard"]["composer"]
        artifact = self._tokens.component["dashboard"]["artifact"]
        window_tokens = self._tokens.component["dashboard"]["window"]
        self._page_gutter = int(window_tokens["page_gutter"])
        self._compact_gutter = int(window_tokens["compact_gutter"])
        self._bottom_clearance = int(chat["bottom_clearance"])
        self._block_gap = int(self._tokens.spacing["conversation_block_gap"])
        self._content_max_width = int(chat["page_content_max_width"])
        self._conversation_column_width = int(
            chat["conversation_column_width"]
        )
        self._context_pane_width = int(chat["optional_context_pane_width"])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._page_gutter,
            self._compact_gutter,
            self._page_gutter,
            self._bottom_clearance,
        )
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(self._block_gap)
        outer.addLayout(body, 1)

        column = QWidget(self)
        column.setMaximumWidth(self._content_max_width)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(16)
        body.addWidget(column, 1)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        title = QLabel("Chat / Work", column)
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)

        mode_switcher = QWidget(column)
        mode_switcher.setObjectName("modeSwitcher")
        mode_layout = QHBoxLayout(mode_switcher)
        mode_layout.setContentsMargins(4, 4, 4, 4)
        mode_layout.setSpacing(4)

        self._chat_mode_btn = QPushButton("💬 Chat Mode", mode_switcher)
        self._chat_mode_btn.setObjectName("secondaryButton")
        self._chat_mode_btn.setCheckable(True)
        self._chat_mode_btn.setChecked(True)
        self._chat_mode_btn.setAccessibleName("Switch to Chat Mode")
        self._chat_mode_btn.clicked.connect(
            lambda: self.set_mode(ChatWorkMode.CHAT)
        )
        mode_layout.addWidget(self._chat_mode_btn)

        self._work_mode_btn = QPushButton("⚡ Work Mode", mode_switcher)
        self._work_mode_btn.setObjectName("secondaryButton")
        self._work_mode_btn.setCheckable(True)
        self._work_mode_btn.setChecked(False)
        self._work_mode_btn.setAccessibleName("Switch to Work Mode")
        self._work_mode_btn.clicked.connect(
            lambda: self.set_mode(ChatWorkMode.WORK)
        )
        mode_layout.addWidget(self._work_mode_btn)

        header_row.addWidget(mode_switcher)
        column_layout.addLayout(header_row)

        self._conversation_caption = QLabel(column)
        self._conversation_caption.setObjectName("textCaption")
        column_layout.addWidget(self._conversation_caption)

        self._transcript_empty = QLabel(
            "No conversation yet. Ask ArkClaw below.", column
        )
        self._transcript_empty.setObjectName("textSecondary")
        self._transcript_empty.setWordWrap(True)
        column_layout.addWidget(self._transcript_empty)

        self._work_gated_banner = QFrame(column)
        self._work_gated_banner.setObjectName("surfaceCard")
        gated_layout = QVBoxLayout(self._work_gated_banner)
        gated_layout.setContentsMargins(12, 10, 12, 10)
        gated_layout.setSpacing(4)
        self._work_gated_title = QLabel(
            "⚡ Work Mode (Structured Workflows)", self._work_gated_banner
        )
        self._work_gated_title.setObjectName("sectionTitle")
        gated_layout.addWidget(self._work_gated_title)
        self._work_gated_desc = QLabel(
            "Execute multi-step tasks, tools, and code automation. "
            "Work tool execution requires configured provider credentials in Settings.",
            self._work_gated_banner,
        )
        self._work_gated_desc.setObjectName("textSecondary")
        self._work_gated_desc.setWordWrap(True)
        gated_layout.addWidget(self._work_gated_desc)
        self._work_gated_banner.setVisible(False)
        self._available_tools: tuple[Any, ...] = ()
        column_layout.addWidget(self._work_gated_banner)

        self._task_state = TaskStateBlock(column)
        column_layout.addWidget(self._task_state)

        self._activity_title = QLabel("Activity", column)
        self._activity_title.setObjectName("sectionTitle")
        column_layout.addWidget(self._activity_title)

        self._activity_container = QWidget(column)
        self._activity_layout = QVBoxLayout(self._activity_container)
        self._activity_layout.setContentsMargins(0, 0, 0, 0)
        self._activity_layout.setSpacing(4)
        column_layout.addWidget(self._activity_container)
        self._activity_rows: list[ActivityRow] = []

        self._result_card = QFrame(column)
        self._result_card.setObjectName("surfaceCard")
        self._result_card.setMaximumWidth(int(artifact["card_max_width"]))
        result_layout = QVBoxLayout(self._result_card)
        result_layout.setContentsMargins(
            int(artifact["card_padding"]),
            int(artifact["card_padding"]),
            int(artifact["card_padding"]),
            int(artifact["card_padding"]),
        )
        result_layout.setSpacing(6)
        self._result_type = QLabel(self._result_card)
        self._result_type.setObjectName("textCaption")
        result_layout.addWidget(self._result_type)
        self._result_title = QLabel(self._result_card)
        self._result_title.setObjectName("sectionTitle")
        self._result_title.setWordWrap(True)
        result_layout.addWidget(self._result_title)
        self._result_state = QLabel(self._result_card)
        self._result_state.setObjectName("agentStatus")
        result_layout.addWidget(self._result_state)
        self._result_summary = QLabel(self._result_card)
        self._result_summary.setObjectName("textSecondary")
        self._result_summary.setWordWrap(True)
        result_layout.addWidget(self._result_summary)
        self._result_actions_row = QHBoxLayout()
        self._result_actions_row.setContentsMargins(0, 0, 0, 0)
        self._result_actions_row.setSpacing(8)
        result_layout.addLayout(self._result_actions_row)
        self._result_actions: list[QPushButton] = []
        self._result_card.setVisible(False)
        column_layout.addWidget(self._result_card)

        self._composer_card = QWidget(column)
        self._composer_card.setObjectName("composerCard")
        self._composer_card.setMaximumWidth(int(composer["max_width"]))
        self._composer_card.setMinimumHeight(int(composer["min_height"]))
        self._composer_card.setMaximumHeight(int(composer["max_multiline_height"]))
        composer_layout = QVBoxLayout(self._composer_card)
        composer_layout.setContentsMargins(
            int(composer["padding"]),
            int(composer["padding"]),
            int(composer["padding"]),
            int(composer["padding"]),
        )
        composer_layout.setSpacing(8)

        self._attachments_container = QWidget(self._composer_card)
        self._attachments_row = QHBoxLayout(self._attachments_container)
        self._attachments_row.setContentsMargins(0, 0, 0, 0)
        self._attachments_row.setSpacing(8)
        self._attachments_container.setVisible(False)
        composer_layout.addWidget(self._attachments_container)
        self._attachment_chips: list[AttachmentChip] = []

        self._composer = _ComposerInput(self._composer_card)
        self._composer.setObjectName("composerInput")
        self._composer.setPlaceholderText("Ask ArkClaw\u2026")
        self._composer.setAccessibleName("Chat / Work composer")
        self._composer.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        composer_layout.addWidget(self._composer, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        attach = self._tokens.component["dashboard"]["attachment"]
        self._theme = QtTheme.LIGHT
        self._attach_button = QPushButton(self._composer_card)
        self._attach_button.setObjectName("secondaryButton")
        self._attach_button.setFixedSize(
            int(attach["attach_hit_target"]),
            int(attach["attach_hit_target"]),
        )
        self._render_attach_icon()
        self._attach_button.setAccessibleName("Attach file or image")
        self._attach_button.setToolTip("Attach file or image")
        self._attach_button.clicked.connect(self.attach_requested)
        bottom.addWidget(self._attach_button)
        bottom.addStretch(1)
        self._send_button = QPushButton("Send", self._composer_card)
        self._send_button.setObjectName("primaryButton")
        self._send_button.setAccessibleName("Send")
        self._send_button.setEnabled(False)
        self._send_button.clicked.connect(self.submit_requested)
        bottom.addWidget(self._send_button)
        composer_layout.addLayout(bottom)
        column_layout.addWidget(self._composer_card)

        self._context_pane = QFrame(self)
        self._context_pane.setObjectName("surfaceCard")
        self._context_pane.setFixedWidth(self._context_pane_width)
        pane_layout = QVBoxLayout(self._context_pane)
        pane_layout.setContentsMargins(16, 16, 16, 16)
        pane_layout.setSpacing(8)
        pane_title = QLabel("Artifact", self._context_pane)
        pane_title.setObjectName("sectionTitle")
        pane_layout.addWidget(pane_title)
        pane_body = QLabel(
            "Select an artifact to inspect it here.", self._context_pane
        )
        pane_body.setObjectName("textSecondary")
        pane_body.setWordWrap(True)
        pane_layout.addWidget(pane_body)
        pane_layout.addStretch(1)
        self._context_pane.setVisible(False)
        body.addWidget(self._context_pane)

        self._composer.textChanged.connect(self._on_composer_text_changed)
        self._composer.cursorPositionChanged.connect(
            self._on_composer_cursor_changed
        )
        self._composer.selectionChanged.connect(self._on_composer_selection_changed)
        self._composer.preedit_changed.connect(self._on_composer_preedit_changed)
        self._composer.submit_requested.connect(self._on_composer_submit)

        self.apply_snapshot(self._snapshot)

    # -- geometry -----------------------------------------------------------
    def content_max_width(self) -> int:
        return self._content_max_width

    def conversation_column_width(self) -> int:
        return self._conversation_column_width

    # -- accessors ----------------------------------------------------------
    def conversation_caption(self) -> QLabel:
        return self._conversation_caption

    def task_state_block(self) -> TaskStateBlock:
        return self._task_state

    def activity_rows(self) -> list[ActivityRow]:
        return list(self._activity_rows)

    def attachment_chips(self) -> list[AttachmentChip]:
        return list(self._attachment_chips)

    def result_card(self) -> QFrame:
        return self._result_card

    def result_title_label(self) -> QLabel:
        return self._result_title

    def result_type_label(self) -> QLabel:
        return self._result_type

    def result_summary_label(self) -> QLabel:
        return self._result_summary

    def result_state_label(self) -> QLabel:
        return self._result_state

    def result_actions(self) -> list[QPushButton]:
        return list(self._result_actions)

    def composer_card(self) -> QWidget:
        return self._composer_card

    def composer(self) -> QTextEdit:
        return self._composer

    def attach_button(self) -> QPushButton:
        return self._attach_button

    def send_button(self) -> QPushButton:
        return self._send_button

    def mode(self) -> ChatWorkMode:
        return self._mode

    def chat_mode_button(self) -> QPushButton:
        return self._chat_mode_btn

    def work_mode_button(self) -> QPushButton:
        return self._work_mode_btn

    def work_gated_banner(self) -> QFrame:
        return self._work_gated_banner

    def set_mode(self, mode: ChatWorkMode) -> None:
        self._mode = mode
        is_chat = mode is ChatWorkMode.CHAT
        self._chat_mode_btn.setChecked(is_chat)
        self._work_mode_btn.setChecked(not is_chat)
        self._work_gated_banner.setVisible(not is_chat)
        self._activity_title.setVisible(not is_chat)
        self._activity_container.setVisible(not is_chat)
        self._composer.setPlaceholderText(
            "Ask ArkClaw anything\u2026"
            if is_chat
            else "Describe the task to execute with ArkClaw\u2026"
        )
        self.mode_changed.emit(mode)

    def set_available_tools(self, tools: Sequence[Any] | None) -> None:
        self._available_tools = tuple(tools or ())
        if self._available_tools:
            tool_names = ", ".join(
                getattr(t, "name", str(t)) for t in self._available_tools
            )
            self._work_gated_title.setText("⚡ Work Mode (Active)")
            self._work_gated_desc.setText(
                f"Multi-step agent workflows enabled. Registered tools: {tool_names}"
            )
        else:
            self._work_gated_title.setText("⚡ Work Mode (Structured Workflows)")
            self._work_gated_desc.setText(
                "Execute multi-step tasks, tools, and code automation. "
                "Work tool execution requires configured provider credentials in Settings."
            )

    def available_tools(self) -> tuple[Any, ...]:
        return self._available_tools

    def context_pane(self) -> QWidget:
        return self._context_pane

    def open_context_pane(self) -> None:
        self._context_pane.setVisible(True)

    def close_context_pane(self) -> None:
        self._context_pane.setVisible(False)

    # -- draft binding ------------------------------------------------------
    def attach_draft_ports(
        self,
        draft_edit_handler: Callable[[DraftEditIntent], None],
        submit_handler: Callable[[], SubmittedDraftSnapshot | None],
        draft_snapshot_provider: Callable[[], ConversationDraftSnapshot],
    ) -> None:
        """Bind the authoritative draft ports (Coordinator wires these)."""
        self._draft_edit_handler = draft_edit_handler
        self._submit_handler = submit_handler
        self._draft_snapshot_provider = draft_snapshot_provider
        if self._draft_ports_attached:
            return
        self._draft_ports_attached = True
        self.edit_requested.connect(draft_edit_handler)
        self.submit_requested.connect(submit_handler)

    def render_draft(self, snapshot: ConversationDraftSnapshot) -> None:
        """Render the authoritative draft snapshot without a feedback loop."""
        if self._rendering_draft:
            return
        self._rendering_draft = True
        try:
            if self._composer.toPlainText() != snapshot.text:
                self._composer.setPlainText(snapshot.text)
            self._apply_editor_position(snapshot)
            self._send_button.setEnabled(bool(snapshot.text))
        finally:
            self._rendering_draft = False

    def _apply_editor_position(
        self,
        snapshot: ConversationDraftSnapshot,
    ) -> None:
        cursor = self._composer.textCursor()
        text_length = len(snapshot.text)
        if snapshot.selection is not None:
            start, end = snapshot.selection
            cursor.setPosition(min(max(start, 0), text_length))
            cursor.setPosition(
                min(max(end, 0), text_length),
                QTextCursor.MoveMode.KeepAnchor,
            )
        else:
            cursor.setPosition(min(max(snapshot.caret, 0), text_length))
        self._composer.setTextCursor(cursor)

    # -- presentation -------------------------------------------------------
    def apply_snapshot(self, snapshot: ChatWorkSnapshot) -> None:
        self._snapshot = snapshot
        self._conversation_caption.setText(snapshot.conversation_id or "")

        working = (
            snapshot.agent_state is not AgentState.IDLE
            and bool(snapshot.agent_task_title)
        )
        self._task_state.setVisible(working)
        if working and snapshot.agent_task_title is not None:
            self._task_state.set_status(
                _STATE_ACTION_TEXT.get(
                    snapshot.agent_state, "Working"
                )
            )
            self._task_state.set_task(snapshot.agent_task_title)

        self._rebuild_activity(snapshot.activity)
        self._rebuild_attachments(snapshot.attachments)
        self._rebuild_result(snapshot.result)

    def _rebuild_activity(
        self, items: Sequence[ActivityItem]
    ) -> None:
        for row in self._activity_rows:
            row.deleteLater()
        self._activity_rows.clear()
        for item in items:
            row = ActivityRow(
                self._tokens,
                item,
                self._activity_container,
                theme=self._theme,
            )
            self._activity_layout.addWidget(row)
            self._activity_rows.append(row)
        self._activity_title.setVisible(bool(items))
        self._activity_container.setVisible(bool(items))

    def _rebuild_attachments(
        self, items: Sequence[AttachmentItem]
    ) -> None:
        for chip in self._attachment_chips:
            chip.deleteLater()
        self._attachment_chips.clear()
        for item in items:
            chip = AttachmentChip(self._tokens, item, self._composer_card)
            chip.retry_requested.connect(
                self.retry_attachment_requested
            )
            chip.remove_requested.connect(
                self.remove_attachment_requested
            )
            self._attachments_row.addWidget(chip)
            self._attachment_chips.append(chip)
        self._attachments_container.setVisible(bool(self._attachment_chips))

    def _rebuild_result(self, result: ResultArtifact | None) -> None:
        for button in self._result_actions:
            button.deleteLater()
        self._result_actions.clear()
        if result is None:
            self._result_card.setVisible(False)
            return
        self._result_card.setVisible(True)
        self._result_type.setText(
            _RESULT_KIND_TEXT.get(result.kind, "Result")
        )
        self._result_title.setText(result.title)
        self._result_summary.setText(result.summary)
        if result.state is ResultArtifactState.OPENING:
            self._result_state.setText("Opening\u2026")
            self._result_state.setVisible(True)
        elif result.state is ResultArtifactState.FAILED:
            self._result_state.setText("Failed")
            self._result_state.setVisible(True)
        else:
            self._result_state.setVisible(False)
        for action in result.actions:
            label = _RESULT_ACTION_TEXT.get(action, action)
            button = QPushButton(label, self._result_card)
            button.setObjectName("secondaryButton")
            button.setAccessibleName(label)
            button.clicked.connect(
                lambda _checked=False, a=action: self.artifact_action_requested.emit(a)
            )
            self._result_actions_row.addWidget(button)
            self._result_actions.append(button)

    # -- composer intents ---------------------------------------------------
    def _on_composer_submit(self) -> None:
        self.submit_requested.emit()

    def _on_composer_text_changed(self) -> None:
        if self._rendering_draft:
            return
        self._composition_active = False
        self._send_button.setEnabled(bool(self._composer.toPlainText()))
        # A committed user edit is deliberate engagement: the integration
        # opens/restores the ONE authoritative ConversationContext before the
        # edit is applied, so the first keystroke is never dropped (07 11,
        # Slice 6B Ask trace).  Dispatch is idempotent on later edits.
        self.conversation_requested.emit()
        self._emit_edit_intent()

    def _on_composer_cursor_changed(self) -> None:
        if self._rendering_draft or self._composition_active:
            return
        self._emit_edit_intent()

    def _on_composer_selection_changed(self) -> None:
        if self._rendering_draft or self._composition_active:
            return
        self._emit_edit_intent()

    def _on_composer_preedit_changed(self, preedit: str) -> None:
        if self._rendering_draft:
            return
        was_active = self._composition_active
        self._composition_active = bool(preedit)
        if preedit:
            self._emit_edit_intent(ime_composition=preedit)
        elif was_active:
            self._emit_edit_intent(ime_composition=None)

    def _emit_edit_intent(self, ime_composition: str | None = None) -> None:
        cursor = self._composer.textCursor()
        selection = None
        if cursor.hasSelection():
            selection = (cursor.selectionStart(), cursor.selectionEnd())
        self.edit_requested.emit(
            DraftEditIntent(
                text=self._composer.toPlainText(),
                caret=cursor.position(),
                selection=selection,
                ime_composition=ime_composition,
            )
        )

    def set_theme(self, theme: QtTheme) -> None:
        if self._theme is theme:
            return
        self._theme = theme
        self._render_attach_icon()
        for row in self._activity_rows:
            row.set_theme(theme)

    def _render_attach_icon(self) -> None:
        size = int(self._tokens.icon["action"])
        self._attach_button.setIcon(
            QIcon(
                icon_pixmap(
                    IconKind.ATTACH,
                    size,
                    icon_color_for_theme(self._tokens, self._theme),
                    dpr=self.devicePixelRatioF(),
                )
            )
        )
        self._attach_button.setIconSize(QSize(size, size))

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.hide()
        self.deleteLater()
