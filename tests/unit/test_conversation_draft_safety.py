"""Slice 4 Draft Safety — Qt-free authoritative draft model contract.

Freezes the 06/08/07/09 draft contract:
- model owns authoritative draft (text, revision, caret/selection, submitted identity)
- ordinary transitions (collapse/restore/palette) never discard
- submit captures an exact immutable snapshot; acceptance clears only the
  accepted revision; newer edits survive stale acceptance; failure/cancel
  preserve the draft; duplicate completion is idempotent
- in-progress IME composition is never committed/submitted by a transition
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftModel,
    DraftEditIntent,
    SubmittedDraftSnapshot,
)
from arkclaw.presentation.frontend_presentation import (
    CloseConversationIntent,
    CollapseConversationIntent,
    ConversationOpenOrRestoreIntent,
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
    FrontendPresentationModel,
    PresentationEffectKind,
    PrimaryPresentation,
    ShowForegroundOverlayIntent,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)


class _RecordingAcceptancePort:
    """Narrow test port: records the exact submitted snapshot identity."""

    def __init__(self) -> None:
        self.accepted: list[SubmittedDraftSnapshot] = []
        self.rejected: list[SubmittedDraftSnapshot] = []
        self.cancelled: list[SubmittedDraftSnapshot] = []

    def accept(self, snapshot: SubmittedDraftSnapshot) -> None:
        self.accepted.append(snapshot)

    def reject(self, snapshot: SubmittedDraftSnapshot) -> None:
        self.rejected.append(snapshot)

    def cancel(self, snapshot: SubmittedDraftSnapshot) -> None:
        self.cancelled.append(snapshot)


def test_initial_empty_draft_is_deterministic() -> None:
    first = ConversationDraftModel().snapshot
    second = ConversationDraftModel().snapshot

    assert first == second
    assert first.text == ""
    assert first.has_draft is False
    assert first.revision == 0
    assert first.caret == 0
    assert first.selection is None
    assert first.submitted_snapshot_identity is None


def test_committed_non_empty_edit_creates_authoritative_draft() -> None:
    model = ConversationDraftModel()

    snapshot = model.edit(DraftEditIntent(text="hello", caret=5))

    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    assert snapshot.revision == 1
    assert snapshot.caret == 5


def test_edit_updates_authoritative_draft_and_revision_advances() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    snapshot = model.edit(DraftEditIntent(text="hello!", caret=6))

    assert snapshot.text == "hello!"
    assert snapshot.has_draft is True
    assert snapshot.revision == 2


def test_caret_only_edit_does_not_advance_revision() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    snapshot = model.edit(DraftEditIntent(text="hello", caret=2, selection=(1, 3)))

    assert snapshot.text == "hello"
    assert snapshot.revision == 1
    assert snapshot.caret == 2
    assert snapshot.selection == (1, 3)


def test_editing_to_empty_removes_draft() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    snapshot = model.edit(DraftEditIntent(text="", caret=0))

    assert snapshot.text == ""
    assert snapshot.has_draft is False
    assert snapshot.revision == 2


def test_submit_captures_exact_immutable_snapshot() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    submitted = model.submit()

    assert submitted is not None
    assert submitted.text == "hello"
    assert submitted.revision == 1
    assert submitted.identity
    with pytest.raises(FrozenInstanceError):
        submitted.text = "mutated"  # type: ignore[misc]
    assert model.snapshot.submitted_snapshot_identity == submitted.identity


def test_submit_with_empty_draft_is_noop() -> None:
    model = ConversationDraftModel()

    submitted = model.submit()

    assert submitted is None
    assert model.snapshot.submitted_snapshot_identity is None


def test_submit_with_in_progress_composition_is_refused() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="ni", caret=2, ime_composition="ni"))

    submitted = model.submit()

    assert submitted is None
    assert model.snapshot.submitted_snapshot_identity is None
    assert model.snapshot.has_draft is False


def test_acceptance_clears_only_matching_current_revision() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None

    snapshot = model.accept(submitted.identity)

    assert snapshot.text == ""
    assert snapshot.has_draft is False
    assert snapshot.submitted_snapshot_identity is None


def test_newer_edit_survives_stale_acceptance() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None
    model.edit(DraftEditIntent(text="hello!", caret=6))

    snapshot = model.accept(submitted.identity)

    assert snapshot.text == "hello!"
    assert snapshot.has_draft is True
    assert snapshot.revision == 2
    assert snapshot.submitted_snapshot_identity is None


def test_duplicate_acceptance_is_idempotent() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None
    model.accept(submitted.identity)

    snapshot = model.accept(submitted.identity)

    assert snapshot.text == ""
    assert snapshot.has_draft is False
    assert snapshot.submitted_snapshot_identity is None


def test_rejection_preserves_draft() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None

    snapshot = model.reject(submitted.identity)

    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    assert snapshot.revision == 1
    assert snapshot.submitted_snapshot_identity is None


def test_cancel_preserves_draft() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None

    snapshot = model.cancel(submitted.identity)

    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    assert snapshot.revision == 1
    assert snapshot.submitted_snapshot_identity is None


def test_failure_after_newer_edit_preserves_newer_draft() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None
    model.edit(DraftEditIntent(text="hello!", caret=6))

    snapshot = model.reject(submitted.identity)

    assert snapshot.text == "hello!"
    assert snapshot.revision == 2
    assert snapshot.submitted_snapshot_identity is None


def test_explicit_discard_destroys_draft() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    snapshot = model.discard()

    assert snapshot.text == ""
    assert snapshot.has_draft is False
    assert snapshot.submitted_snapshot_identity is None


def test_acceptance_port_receives_exact_submitted_identity() -> None:
    port = _RecordingAcceptancePort()
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit()
    assert submitted is not None

    port.accept(submitted)
    port.reject(submitted)
    port.cancel(submitted)

    assert [s.identity for s in port.accepted] == [submitted.identity]
    assert [s.identity for s in port.rejected] == [submitted.identity]
    assert [s.identity for s in port.cancelled] == [submitted.identity]
    assert model.snapshot.text == "hello"


def test_collapse_preserves_authoritative_draft() -> None:
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    before = coordinator.draft_snapshot

    coordinator.dispatch(CollapseConversationIntent())

    assert coordinator.draft_snapshot == before
    assert coordinator.draft_snapshot.text == "hello"


def test_restore_presents_same_draft() -> None:
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    coordinator.dispatch(CollapseConversationIntent())

    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    snapshot = coordinator.draft_snapshot
    assert snapshot.text == "hello"
    assert snapshot.has_draft is True
    assert snapshot.revision == 1


def test_palette_roundtrip_preserves_draft() -> None:
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    before = coordinator.draft_snapshot

    coordinator.dispatch(
        ShowForegroundOverlayIntent(ForegroundOverlay.PALETTE)
    )
    coordinator.dispatch(DismissForegroundOverlayIntent())

    assert coordinator.draft_snapshot == before


def test_presentation_dispatch_never_mutates_draft() -> None:
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    before = coordinator.draft_snapshot

    coordinator.dispatch(CollapseConversationIntent())
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.dispatch(
        ShowForegroundOverlayIntent(ForegroundOverlay.PALETTE)
    )
    coordinator.dispatch(DismissForegroundOverlayIntent())

    assert coordinator.draft_snapshot == before


def test_snapshot_is_immutable() -> None:
    snapshot = ConversationDraftModel().snapshot

    with pytest.raises(FrozenInstanceError):
        snapshot.text = "mutated"  # type: ignore[misc]


# --- Review-fix: draft truth lives in the Presentation Model, not Coordinator ---

def test_draft_truth_is_reachable_through_frontend_presentation_model() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())

    snapshot = model.apply_draft_edit(DraftEditIntent(text="hello", caret=5))

    assert snapshot.text == "hello"
    assert model.draft_snapshot.text == "hello"
    assert model.draft_snapshot.has_draft is True
    assert model.draft_snapshot.revision == 1


def test_coordinator_does_not_own_second_draft_state() -> None:
    model = FrontendPresentationModel()
    coordinator = FrontendPresentationCoordinator(model=model)
    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    coordinator.apply_draft_edit(DraftEditIntent(text="hi", caret=2))

    assert model.draft_snapshot.text == "hi"
    assert coordinator.draft_snapshot == model.draft_snapshot


def test_close_preserves_unsent_draft_while_explicit_discard_destroys_draft() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    model.apply_draft_edit(DraftEditIntent(text="hello", caret=5))

    # Ordinary collapse preserves the authoritative draft (06 8.3).
    model.dispatch(CollapseConversationIntent())
    assert model.draft_snapshot.text == "hello"
    model.dispatch(ConversationOpenOrRestoreIntent())

    # Close is a visibility-only transition (05 2.1.3, 06 2.1.4), never a
    # draft-discard authority (06 8.3): the context and draft are preserved
    # and the surface is hidden via HIDE_CONVERSATION.
    closed = model.dispatch(CloseConversationIntent())
    assert [effect.kind for effect in closed.effects] == [
        PresentationEffectKind.HIDE_CONVERSATION,
        PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert model.snapshot.conversation_context is not None
    assert model.draft_snapshot.text == "hello"

    # Explicit Clear/Discard is the authorized draft-destruction path
    # (06 8.3).  Close still never destroys the logical context.
    model.discard_draft()
    model.dispatch(CloseConversationIntent())
    assert model.snapshot.conversation_context is not None
    assert model.draft_snapshot.has_draft is False
    assert model.draft_snapshot.text == ""


# --- Review-fix: IME active composition is separate semantic state ---

def test_active_composition_is_observable_in_snapshot() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    snapshot = model.edit(
        DraftEditIntent(text="hello", caret=6, ime_composition="ni")
    )

    assert snapshot.ime_composition == "ni"
    assert snapshot.text == "hello"
    assert snapshot.revision == 1


def test_composition_updates_do_not_advance_revision() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    model.edit(
        DraftEditIntent(text="hello", caret=6, ime_composition="ni")
    )
    snapshot = model.edit(
        DraftEditIntent(text="hello", caret=7, ime_composition="nihao")
    )

    assert snapshot.text == "hello"
    assert snapshot.revision == 1
    assert snapshot.ime_composition == "nihao"


def test_composition_commit_advances_revision_exactly_once() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    model.edit(DraftEditIntent(text="hello", caret=6, ime_composition="ni"))

    snapshot = model.edit(DraftEditIntent(text="hello\u4f60", caret=7))

    assert snapshot.text == "hello\u4f60"
    assert snapshot.revision == 2
    assert snapshot.ime_composition is None


def test_composition_cancel_keeps_committed_text_unchanged() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    model.edit(DraftEditIntent(text="hello", caret=6, ime_composition="ni"))

    snapshot = model.edit(DraftEditIntent(text="hello", caret=5))

    assert snapshot.text == "hello"
    assert snapshot.revision == 1
    assert snapshot.ime_composition is None


def test_submit_refused_while_composition_active_with_existing_draft() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    model.edit(DraftEditIntent(text="hello", caret=6, ime_composition="ni"))

    submitted = model.submit()

    assert submitted is None
    assert model.snapshot.text == "hello"
    assert model.snapshot.revision == 1
    assert model.snapshot.ime_composition == "ni"


def test_composition_survives_collapse_restore_and_palette_roundtrip() -> None:
    coordinator = FrontendPresentationCoordinator()
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    coordinator.apply_draft_edit(
        DraftEditIntent(text="hello", caret=6, ime_composition="ni")
    )
    before = coordinator.draft_snapshot

    coordinator.dispatch(CollapseConversationIntent())
    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.dispatch(
        ShowForegroundOverlayIntent(ForegroundOverlay.PALETTE)
    )
    coordinator.dispatch(DismissForegroundOverlayIntent())

    assert coordinator.draft_snapshot == before
    assert coordinator.draft_snapshot.ime_composition == "ni"


# --- Review-fix: singular submitted snapshot identity ---

def test_duplicate_submit_same_revision_is_refused() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))

    first = model.submit()
    assert first is not None
    second = model.submit()

    assert second is None
    assert model.snapshot.submitted_snapshot_identity == first.identity


def test_submit_allowed_again_after_stale_acceptance_resolution() -> None:
    model = ConversationDraftModel()
    model.edit(DraftEditIntent(text="hello", caret=5))
    first = model.submit()
    assert first is not None
    model.edit(DraftEditIntent(text="hello!", caret=6))

    model.accept(first.identity)

    second = model.submit()
    assert second is not None
    assert second.revision == 2
    assert second.identity != first.identity
# --- Review-fix: context-lifetime coupling (draft belongs to a logical context) ---

def test_draft_edit_without_conversation_context_is_noop() -> None:
    model = FrontendPresentationModel()

    snapshot = model.apply_draft_edit(DraftEditIntent(text="hello", caret=5))

    assert snapshot.has_draft is False
    assert snapshot.text == ""
    assert model.snapshot.conversation_context is None


def test_submit_without_conversation_context_creates_no_detached_snapshot() -> None:
    draft = ConversationDraftModel()
    draft.edit(DraftEditIntent(text="hello", caret=5))
    model = FrontendPresentationModel(draft_model=draft)
    assert model.snapshot.conversation_context is None

    submitted = model.submit_draft()

    assert submitted is None
    assert model.draft_snapshot.submitted_snapshot_identity is None
    assert model.draft_snapshot.text == "hello"


def test_stale_edit_after_close_targets_preserved_context_never_orphan() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    model.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    model.discard_draft()
    model.dispatch(CloseConversationIntent())
    # Close is visibility-only (05 2.1.3, 06 2.1.4): the logical context
    # survives, so a late host edit is owned by that context and is never an
    # orphan draft detached from a context (06 8.1).
    assert model.snapshot.conversation_context is not None
    assert model.draft_snapshot.has_draft is False

    snapshot = model.apply_draft_edit(DraftEditIntent(text="stale", caret=5))

    assert snapshot.has_draft is True
    assert snapshot.text == "stale"
    assert model.snapshot.conversation_context is not None


# --- Review-fix: Close is not a draft-discard authority (06 8.3) ---

def test_close_with_unsent_draft_hides_and_preserves_context() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    model.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    before = model.draft_snapshot

    result = model.dispatch(CloseConversationIntent())

    assert [effect.kind for effect in result.effects] == [
        PresentationEffectKind.HIDE_CONVERSATION,
        PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert model.snapshot.conversation_context is not None
    assert model.snapshot.primary_presentation is PrimaryPresentation.CHARACTER
    assert model.draft_snapshot == before


def test_close_with_inflight_submitted_snapshot_preserves_correlation() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    model.apply_draft_edit(DraftEditIntent(text="hello", caret=5))
    submitted = model.submit_draft()
    assert submitted is not None

    result = model.dispatch(CloseConversationIntent())

    assert [effect.kind for effect in result.effects] == [
        PresentationEffectKind.HIDE_CONVERSATION,
        PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert model.snapshot.conversation_context is not None
    assert model.draft_snapshot.submitted_snapshot_identity == submitted.identity


def test_close_without_draft_preserves_empty_context() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())

    result = model.dispatch(CloseConversationIntent())

    assert model.snapshot.conversation_context is not None
    assert model.draft_snapshot.has_draft is False
    assert [effect.kind for effect in result.effects] == [
        PresentationEffectKind.HIDE_CONVERSATION,
        PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert not any(
        effect.kind is PresentationEffectKind.CLOSE_CONVERSATION
        for effect in result.effects
    )


def test_active_composition_survives_close() -> None:
    model = FrontendPresentationModel()
    model.dispatch(ConversationOpenOrRestoreIntent())
    before = model.draft_snapshot

    # Activate an in-progress IME composition with no committed text yet
    # (07 17): active composition is distinct semantic state, independent of
    # whether committed draft text is empty.
    model.apply_draft_edit(
        DraftEditIntent(text="", caret=0, ime_composition="ni")
    )
    composed = model.draft_snapshot
    assert composed.ime_composition == "ni"
    assert composed.has_draft is False

    result = model.dispatch(CloseConversationIntent())

    # 06 8.1: an active IME composition must not be destroyed by a Surface
    # transition.  Close is visibility-only (05 2.1.3, 06 2.1.4), so the
    # logical context, revision and composition are all preserved.
    assert model.snapshot.conversation_context is not None
    snapshot = model.draft_snapshot
    assert snapshot.ime_composition == "ni"
    assert snapshot.revision == before.revision
    assert snapshot.text == ""
    assert not any(
        effect.kind is PresentationEffectKind.CLOSE_CONVERSATION
        for effect in result.effects
    )
