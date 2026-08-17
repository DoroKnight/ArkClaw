"""Qt-free authoritative Conversation draft state (Slice 4 Draft Safety).

The model owns the one authoritative unsent draft per logical Conversation
context (06 8.1, 07 17).  Widgets render snapshots and emit edit intents; they
never own draft truth.  The draft is immutable-by-value and destroyed only by
exact correlated acceptance, explicit discard, or an explicit safe Quit flow
(06 8.3).

Contract highlights:

- committed non-empty edit creates the draft and advances the revision;
- submit captures an exact immutable snapshot and never clears the draft;
- acceptance clears the draft only when the accepted revision still matches
  the current revision (exact snapshot); a newer edit survives stale
  acceptance;
- rejection/cancel never discard the draft;
- in-progress IME composition is never committed or submitted;
- collapse/restore/Palette/Drag/Interact/focus-loss are presentation
  transitions only and never reach this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ConversationDraftSnapshot:
    """Immutable projection of the authoritative draft state."""

    text: str
    has_draft: bool
    revision: int
    caret: int
    selection: tuple[int, int] | None
    submitted_snapshot_identity: str | None
    ime_composition: str | None = None


@dataclass(frozen=True, slots=True)
class SubmittedDraftSnapshot:
    """Exact immutable snapshot captured at submit time."""

    identity: str
    revision: int
    text: str


@dataclass(frozen=True, slots=True)
class DraftEditIntent:
    """Committed (or in-progress composition) edit request from a host."""

    text: str
    caret: int
    selection: tuple[int, int] | None = None
    ime_composition: str | None = None


class DraftAcceptancePort(Protocol):
    """Narrow application/test port for correlated acceptance.

    Production submit remains inert until a port can prove exact
    snapshot-to-acceptance correlation (08 13, 09 17).  This protocol only
    describes the seam; no backend is invoked by the model.
    """

    def accept(self, snapshot: SubmittedDraftSnapshot) -> None: ...

    def reject(self, snapshot: SubmittedDraftSnapshot) -> None: ...

    def cancel(self, snapshot: SubmittedDraftSnapshot) -> None: ...


class ConversationDraftModel:
    """Single owner of the unsent draft state for one Conversation context."""

    def __init__(self) -> None:
        self._text = ""
        self._revision = 0
        self._caret = 0
        self._selection: tuple[int, int] | None = None
        self._ime_composition: str | None = None
        self._submitted_identity: str | None = None
        self._submitted_snapshots: dict[str, SubmittedDraftSnapshot] = {}

    @property
    def snapshot(self) -> ConversationDraftSnapshot:
        return ConversationDraftSnapshot(
            text=self._text,
            has_draft=self._text != "",
            revision=self._revision,
            caret=self._caret,
            selection=self._selection,
            submitted_snapshot_identity=self._submitted_identity,
            ime_composition=self._ime_composition,
        )

    def edit(self, intent: DraftEditIntent) -> ConversationDraftSnapshot:
        """Apply one committed edit or an in-progress composition update.

        An in-progress IME composition is distinct semantic state (07 17): it
        updates caret/selection/composition only and never creates a draft,
        advances the revision, or becomes a submission.  A committed edit
        (``ime_composition is None``) clears the composition and advances the
        revision only when the committed text actually changed, so a
        composition commit advances exactly once and a composition cancel
        leaves the committed text unchanged.
        """
        if intent.ime_composition is not None:
            self._caret = intent.caret
            self._selection = intent.selection
            self._ime_composition = intent.ime_composition
            return self.snapshot

        self._caret = intent.caret
        self._selection = intent.selection
        self._ime_composition = None
        if intent.text != self._text:
            self._text = intent.text
            self._revision += 1
        return self.snapshot

    def submit(self) -> SubmittedDraftSnapshot | None:
        """Capture an exact immutable submit snapshot.

        Never clears the draft.  Returns None when there is no committed
        draft, when an in-progress IME composition must not be submitted
        (06 8.1, 07 17), or when a submitted snapshot is already in flight
        (singular ``submitted_snapshot_identity``, 07 17).  The in-flight
        identity is cleared only by correlated acceptance/rejection/cancel.
        """
        if self._text == "":
            return None
        if self._ime_composition is not None:
            return None
        if self._submitted_identity is not None:
            return None
        snapshot = SubmittedDraftSnapshot(
            identity=str(uuid4()),
            revision=self._revision,
            text=self._text,
        )
        self._submitted_identity = snapshot.identity
        self._submitted_snapshots[snapshot.identity] = snapshot
        return snapshot

    def accept(self, identity: str) -> ConversationDraftSnapshot:
        """Clear the draft only when the accepted snapshot is still current.

        A stale acceptance (newer revision) preserves the newer draft.
        Duplicate acceptance is idempotent.
        """
        snapshot = self._submitted_snapshots.pop(identity, None)
        if snapshot is None:
            return self.snapshot
        if (
            self._submitted_identity == identity
            and self._revision == snapshot.revision
        ):
            self._clear_draft()
        if self._submitted_identity == identity:
            self._submitted_identity = None
        return self.snapshot

    def reject(self, identity: str) -> ConversationDraftSnapshot:
        """Failure/rejection never discards the draft."""
        self._submitted_snapshots.pop(identity, None)
        if self._submitted_identity == identity:
            self._submitted_identity = None
        return self.snapshot

    def cancel(self, identity: str) -> ConversationDraftSnapshot:
        """User/Agent cancel never discards the draft."""
        self._submitted_snapshots.pop(identity, None)
        if self._submitted_identity == identity:
            self._submitted_identity = None
        return self.snapshot

    def discard(self) -> ConversationDraftSnapshot:
        """Explicit user Clear/Discard destroys the draft."""
        self._clear_draft()
        self._submitted_identity = None
        return self.snapshot

    def _clear_draft(self) -> None:
        self._text = ""
        self._caret = 0
        self._selection = None
        self._ime_composition = None


__all__ = [
    "ConversationDraftModel",
    "ConversationDraftSnapshot",
    "DraftAcceptancePort",
    "DraftEditIntent",
    "SubmittedDraftSnapshot",
]
