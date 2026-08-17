"""Application-lifetime coordinator seam for frontend presentation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftSnapshot,
    DraftEditIntent,
    SubmittedDraftSnapshot,
)
from arkclaw.presentation.frontend_presentation import (
    FrontendPresentationIntent,
    FrontendPresentationModel,
    FrontendPresentationResult,
    FrontendPresentationSnapshot,
    PresentationEffect,
)


@runtime_checkable
class DraftHostSink(Protocol):
    """Narrow host-seam port that can accept authoritative draft bindings.

    The Coordinator wires model-owned draft handlers into the host effect sink
    so the host never owns draft truth and the test/application never performs
    the wiring itself.
    """

    def attach_draft_ports(
        self,
        draft_edit_handler: object,
        submit_handler: object,
        draft_snapshot_provider: object,
    ) -> None: ...


class PresentationEffectSink(Protocol):
    def apply(self, effect: PresentationEffect) -> None:
        """Execute one semantic presentation effect."""


class _NoopEffectSink:
    def apply(self, effect: PresentationEffect) -> None:
        del effect


class FrontendPresentationCoordinator:
    """Coordinates intents through the model and applies ordered effects.

    The coordinator intentionally owns no presentation truth and no draft
    truth (07 17, 20, 26): the Frontend Presentation Model / logical
    Conversation context owns the one authoritative draft (07 20.3).  The
    coordinator only dispatches intents and routes host edit/submit requests
    to the model-owned draft.
    """

    def __init__(
        self,
        model: FrontendPresentationModel | None = None,
        effect_sink: PresentationEffectSink | None = None,
    ) -> None:
        self._model = model or FrontendPresentationModel()
        self._effect_sink: PresentationEffectSink = (
            effect_sink or _NoopEffectSink()
        )
        self._wire_draft_host_sink()

    def _wire_draft_host_sink(self) -> None:
        """Wire model-owned draft ports into a real host effect sink.

        This is the single production seam that binds the Capsule to the
        authoritative draft.  No test/application wiring is required for the
        real sink; no second draft store is created.
        """
        sink = self._effect_sink
        if not isinstance(sink, DraftHostSink):
            return
        sink.attach_draft_ports(
            draft_edit_handler=self._model.apply_draft_edit,
            submit_handler=self._model.submit_draft,
            draft_snapshot_provider=self._model.provide_draft_snapshot,
        )

    @property
    def snapshot(self) -> FrontendPresentationSnapshot:
        return self._model.snapshot

    @property
    def draft_snapshot(self) -> ConversationDraftSnapshot:
        return self._model.draft_snapshot

    def apply_draft_edit(
        self,
        intent: DraftEditIntent,
    ) -> ConversationDraftSnapshot:
        """Route one host edit intent to the model-owned authoritative draft."""
        return self._model.apply_draft_edit(intent)

    def submit_draft(self) -> SubmittedDraftSnapshot | None:
        """Capture an inert submit snapshot; never invokes a backend."""
        return self._model.submit_draft()

    def accept_draft(self, identity: str) -> ConversationDraftSnapshot:
        return self._model.accept_draft(identity)

    def reject_draft(self, identity: str) -> ConversationDraftSnapshot:
        return self._model.reject_draft(identity)

    def cancel_draft(self, identity: str) -> ConversationDraftSnapshot:
        return self._model.cancel_draft(identity)

    def discard_draft(self) -> ConversationDraftSnapshot:
        return self._model.discard_draft()

    def dispatch(
        self,
        intent: FrontendPresentationIntent,
    ) -> FrontendPresentationResult:
        result = self._model.dispatch(intent)
        for effect in result.effects:
            self._effect_sink.apply(effect)
        return result


__all__ = [
    "DraftHostSink",
    "FrontendPresentationCoordinator",
    "PresentationEffectSink",
]
