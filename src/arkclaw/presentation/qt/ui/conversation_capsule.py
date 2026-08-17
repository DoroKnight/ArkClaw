"""Independent, focusable top-level Qt surface skeleton for Conversation.

The host renders presentation snapshots and emits intents.  It deliberately
owns no global presentation truth, draft truth, or backend session state.
Draft text is rendered from the authoritative model and edited text is
reported as :class:`DraftEditIntent`; the widget never becomes the draft owner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from arkclaw.presentation.conversation_anchor import AnchorPlacement
from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftSnapshot,
    DraftEditIntent,
)

if TYPE_CHECKING:
    from arkclaw.presentation.frontend_presentation import (
        FrontendPresentationSnapshot,
    )


class _ConversationInput(QTextEdit):
    submit_requested = Signal()
    collapse_requested = Signal()
    preedit_changed = Signal(str)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        """Forward real Qt input-method events after native processing.

        Preedit text is never committed draft: it is reported through
        :attr:`preedit_changed` so the authoritative model can track the
        active composition.  Commit and reset events report an empty preedit,
        which the model treats as commit/cancel of the composition.
        """
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

        if event.key() == Qt.Key.Key_Escape:
            self.collapse_requested.emit()
            event.accept()
            return

        super().keyPressEvent(event)


class ConversationCapsule(QWidget):
    """Lazily created top-level Tool surface for the logical Conversation."""

    submit_requested = Signal()
    collapse_requested = Signal()
    edit_requested = Signal(object)

    def __init__(
        self,
        conversation_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conversation_id = conversation_id
        self._rendering_draft = False
        self.setObjectName("ConversationCapsule")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input_edit = _ConversationInput(self)
        self.input_edit.setPlaceholderText("Ask ArkClaw\u2026")
        self.input_edit.setAttribute(
            Qt.WidgetAttribute.WA_InputMethodEnabled, True
        )
        layout.addWidget(self.input_edit)

        self.input_edit.submit_requested.connect(self.submit_requested)
        self.input_edit.collapse_requested.connect(self.collapse_requested)
        self.input_edit.textChanged.connect(self._on_input_text_changed)
        self.input_edit.cursorPositionChanged.connect(
            self._on_cursor_position_changed
        )
        self.input_edit.selectionChanged.connect(self._on_selection_changed)
        self.input_edit.preedit_changed.connect(self._on_preedit_changed)
        self._composition_active = False

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    def apply_anchor_placement(self, placement: AnchorPlacement) -> None:
        rect = placement.rect
        self.setGeometry(rect.x, rect.y, rect.width, rect.height)

    def render_snapshot(
        self,
        snapshot: FrontendPresentationSnapshot | None,
    ) -> None:
        """Render skeleton content without requesting or stealing focus."""

        del snapshot

    def render_draft(
        self,
        snapshot: ConversationDraftSnapshot,
    ) -> None:
        """Render the authoritative draft snapshot into the editor.

        Rendering is guarded so the resulting ``textChanged`` never produces a
        new edit intent (no feedback loop, no duplicate revision).
        """

        if self._rendering_draft:
            return
        self._rendering_draft = True
        try:
            if self.input_edit.toPlainText() != snapshot.text:
                self.input_edit.setPlainText(snapshot.text)
            self._apply_editor_position(snapshot)
        finally:
            self._rendering_draft = False

    def _apply_editor_position(
        self,
        snapshot: ConversationDraftSnapshot,
    ) -> None:
        cursor = self.input_edit.textCursor()
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
        self.input_edit.setTextCursor(cursor)

    def _on_input_text_changed(self) -> None:
        if self._rendering_draft:
            return
        # Any committed text change ends the Qt composition (QTextEdit commits
        # on document change); the committed intent below clears the model
        # composition state exactly once.
        self._composition_active = False
        self._emit_edit_intent()

    def _on_cursor_position_changed(self) -> None:
        if self._rendering_draft or self._composition_active:
            return
        self._emit_edit_intent()

    def _on_selection_changed(self) -> None:
        if self._rendering_draft or self._composition_active:
            return
        self._emit_edit_intent()

    def _on_preedit_changed(self, preedit: str) -> None:
        if self._rendering_draft:
            return
        was_active = self._composition_active
        self._composition_active = bool(preedit)
        if preedit:
            self._emit_edit_intent(ime_composition=preedit)
        elif was_active:
            # Composition ended without a committed text change (cancel or
            # reset): report a committed intent so the model clears its
            # authoritative composition state without advancing the revision.
            self._emit_edit_intent(ime_composition=None)

    def _emit_edit_intent(self, ime_composition: str | None = None) -> None:
        cursor = self.input_edit.textCursor()
        selection = None
        if cursor.hasSelection():
            selection = (
                cursor.selectionStart(),
                cursor.selectionEnd(),
            )
        self.edit_requested.emit(
            DraftEditIntent(
                text=self.input_edit.toPlainText(),
                caret=cursor.position(),
                selection=selection,
                ime_composition=ime_composition,
            )
        )


__all__ = ["ConversationCapsule"]

