"""Qt effect consumer that materializes the Conversation Capsule host.

The sink consumes ordered effects produced by FrontendPresentationModel and
coordinates only local Qt surface mechanics.  It never owns presentation
truth, draft truth, or create-vs-restore decisions.  It establishes the real
host binding once per host: the authoritative draft is rendered from the
model-owned draft and host edit/submit signals are routed back to it
(07 17, 08 13).  Production submit remains inert: the submit handler only
captures a snapshot; it never invokes a backend.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftSnapshot,
    DraftEditIntent,
    SubmittedDraftSnapshot,
)
from arkclaw.presentation.frontend_presentation import (
    CollapseConversationIntent,
    FrontendPresentationIntent,
    PresentationEffect,
    PresentationEffectKind,
    SemanticFocusTarget,
)
from arkclaw.presentation.qt.ui.conversation_capsule import ConversationCapsule


class ConversationSurfaceEffectSink:
    def __init__(
        self,
        intent_handler: Callable[[FrontendPresentationIntent], None] | None = None,
    ) -> None:
        self._host: ConversationCapsule | None = None
        self._intent_handler = intent_handler
        self._draft_edit_handler: (
            Callable[[DraftEditIntent], None] | None
        ) = None
        self._submit_handler: (
            Callable[[], SubmittedDraftSnapshot | None] | None
        ) = None
        self._draft_snapshot_provider: (
            Callable[[], ConversationDraftSnapshot] | None
        ) = None

    def attach_draft_ports(
        self,
        draft_edit_handler: Callable[[DraftEditIntent], None],
        submit_handler: Callable[[], SubmittedDraftSnapshot | None],
        draft_snapshot_provider: Callable[[], ConversationDraftSnapshot],
    ) -> None:
        """Attach the narrow model-owned draft ports (wired by Coordinator)."""
        self._draft_edit_handler = draft_edit_handler
        self._submit_handler = submit_handler
        self._draft_snapshot_provider = draft_snapshot_provider

    @property
    def host(self) -> ConversationCapsule | None:
        return self._host

    def attach_intent_handler(
        self,
        handler: Callable[[FrontendPresentationIntent], None],
    ) -> None:
        self._intent_handler = handler

    def apply(self, effect: PresentationEffect) -> None:
        if effect.kind in {
            PresentationEffectKind.CREATE_CONVERSATION,
            PresentationEffectKind.RESTORE_CONVERSATION,
        }:
            self._ensure_host(effect.conversation_id)
        elif effect.kind is PresentationEffectKind.HIDE_CONVERSATION:
            self._hide_host()
        elif effect.kind is PresentationEffectKind.CLOSE_CONVERSATION:
            self._destroy_host()
        elif effect.kind is PresentationEffectKind.SET_SEMANTIC_FOCUS:
            self._apply_focus(effect.focus_target)

    def _ensure_host(self, conversation_id: str | None) -> None:
        if self._host is not None:
            if not self._host.isVisible():
                self._host.show()
            # Restore path: re-render the authoritative draft automatically.
            self._render_draft()
            return

        host = ConversationCapsule(
            conversation_id or "arkclaw-conversation"
        )
        # Bind exactly once at host creation; repeated RESTORE never
        # re-connects, so no duplicate edit/submit/caret signal wiring.
        host.collapse_requested.connect(self._on_collapse_requested)
        host.edit_requested.connect(self._on_edit_requested)
        host.submit_requested.connect(self._on_submit_requested)
        self._host = host
        host.show()
        # Create path: render the authoritative draft automatically.
        self._render_draft()

    def _hide_host(self) -> None:
        host = self._host
        if host is not None and host.isVisible():
            host.hide()

    def _destroy_host(self) -> None:
        host = self._host
        self._host = None
        if host is not None:
            host.close()
            host.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _on_collapse_requested(self) -> None:
        handler = self._intent_handler
        if handler is not None:
            handler(CollapseConversationIntent())

    def _on_edit_requested(self, intent: DraftEditIntent) -> None:
        handler = self._draft_edit_handler
        if handler is not None:
            handler(intent)

    def _on_submit_requested(self) -> None:
        handler = self._submit_handler
        if handler is not None:
            handler()

    def _render_draft(self) -> None:
        provider = self._draft_snapshot_provider
        host = self._host
        if provider is None or host is None:
            return
        host.render_draft(provider())

    def _apply_focus(
        self,
        focus_target: SemanticFocusTarget | None,
    ) -> None:
        if focus_target is not SemanticFocusTarget.CONVERSATION_INPUT:
            return

        host = self._host
        if host is None:
            return

        QApplication.processEvents()
        host.activateWindow()
        QApplication.processEvents()
        host.input_edit.setFocus()


__all__ = ["ConversationSurfaceEffectSink"]