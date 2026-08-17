"""Qt-free frontend presentation state seam.

This module is intentionally independent of Qt widget visibility.  The model is
the owner of logical presentation state; host widgets will only render snapshots
and emit intents in later slices.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto

from arkclaw.presentation.conversation_draft_safety import (
    ConversationDraftModel,
    ConversationDraftSnapshot,
    DraftEditIntent,
    SubmittedDraftSnapshot,
)


class PrimaryPresentation(Enum):
    CHARACTER = auto()
    CAPSULE = auto()
    EXPANDED = auto()
    WORKSPACE = auto()


class ForegroundOverlay(Enum):
    NONE = auto()
    PALETTE = auto()
    CONFIRMATION = auto()
    CRITICAL_ERROR = auto()
    AMBIENT = auto()


class ActionPaletteLayer(Enum):
    """Qt-free same-shell layer of the one Action Palette (06 9.2/9.4).

    ROOT is the only entry layer: 06 9.4 "Right Click -> Root".  Character
    and System are same-shell secondary layers (07 21); Back/Escape from a
    secondary layer returns to ROOT (06 9.4 "Secondary layer + Back/Escape
    -> Root"; 06 7 "Character/System Palette layer | Return to Palette
    root").
    """

    ROOT = auto()
    CHARACTER = auto()
    SYSTEM = auto()


class SemanticFocusTarget(Enum):
    NONE = auto()
    PALETTE = auto()
    CONVERSATION_INPUT = auto()
    WORKSPACE_CONTROL = auto()
    EXTERNAL = auto()


class PresentationEffectKind(Enum):
    SHOW_FOREGROUND_OVERLAY = auto()
    DISMISS_FOREGROUND_OVERLAY = auto()
    CREATE_CONVERSATION = auto()
    RESTORE_CONVERSATION = auto()
    CLOSE_CONVERSATION = auto()
    HIDE_CONVERSATION = auto()
    SET_SEMANTIC_FOCUS = auto()
    PALETTE_LAYER_CHANGED = auto()


@dataclass(frozen=True, slots=True)
class ConversationContext:
    context_id: str


@dataclass(frozen=True, slots=True)
class FrontendPresentationSnapshot:
    primary_presentation: PrimaryPresentation = PrimaryPresentation.CHARACTER
    foreground_overlay: ForegroundOverlay = ForegroundOverlay.NONE
    conversation_context: ConversationContext | None = None
    semantic_focus_target: SemanticFocusTarget = SemanticFocusTarget.NONE
    semantic_focus_return_target: SemanticFocusTarget | None = None
    palette_layer: ActionPaletteLayer = ActionPaletteLayer.ROOT


@dataclass(frozen=True, slots=True)
class PresentationEffect:
    kind: PresentationEffectKind
    overlay: ForegroundOverlay | None = None
    conversation_id: str | None = None
    focus_target: SemanticFocusTarget | None = None
    layer: ActionPaletteLayer | None = None


@dataclass(frozen=True, slots=True)
class FrontendPresentationResult:
    snapshot: FrontendPresentationSnapshot
    effects: tuple[PresentationEffect, ...]


@dataclass(frozen=True, slots=True)
class ConversationOpenOrRestoreIntent:
    pass


@dataclass(frozen=True, slots=True)
class CloseConversationIntent:
    """Visibility-only close; never destroys the context, draft, or IME.

    Dismiss / Collapse / Close only change UI visibility (05 2.1.3) and are
    never Cancel (06 2.1.4).  Close hides the Conversation surface while
    preserving the logical ConversationContext and its one authoritative
    draft, submitted snapshot and active IME composition (06 8.1, 8.3).  The
    logical context is destroyed only by an explicitly authorized semantic
    (exact correlated acceptance, explicit Clear/Discard, or an explicit
    safe Quit flow).
    """

    pass


@dataclass(frozen=True, slots=True)
class CollapseConversationIntent:
    """Ordinary collapse preserve semantic; never logical destroy."""

    pass


@dataclass(frozen=True, slots=True)
class ShowForegroundOverlayIntent:
    overlay: ForegroundOverlay


@dataclass(frozen=True, slots=True)
class DismissForegroundOverlayIntent:
    pass


@dataclass(frozen=True, slots=True)
class SetPaletteLayerIntent:
    """One same-shell Palette navigation step (06 9.4, 07 21).

    Palette navigation (Root/Character/System, Back) is Palette presentation
    semantics, never a CommandId: it changes the Qt-free model layer and
    produces zero application command dispatch.
    """

    layer: ActionPaletteLayer


FrontendPresentationIntent = (
    ConversationOpenOrRestoreIntent
    | CloseConversationIntent
    | CollapseConversationIntent
    | ShowForegroundOverlayIntent
    | DismissForegroundOverlayIntent
    | SetPaletteLayerIntent
)

_CONVERSATION_CONTEXT_ID = "arkclaw-conversation"

_BLOCKING_OVERLAYS = {
    ForegroundOverlay.CONFIRMATION,
    ForegroundOverlay.CRITICAL_ERROR,
}


class FrontendPresentationModel:
    """Single owner of frontend presentation state and ordered effects."""

    def __init__(
        self,
        snapshot: FrontendPresentationSnapshot | None = None,
        draft_model: ConversationDraftModel | None = None,
    ) -> None:
        self._snapshot = snapshot or FrontendPresentationSnapshot()
        # The Frontend Presentation Model / logical Conversation owns the one
        # authoritative unsent draft (07 20.3, 06 8.1).  The Coordinator only
        # dispatches; the QWidget only renders and emits edit intents.
        self._draft_model = draft_model or ConversationDraftModel()

    @property
    def snapshot(self) -> FrontendPresentationSnapshot:
        return self._snapshot

    @property
    def draft_snapshot(self) -> ConversationDraftSnapshot:
        """Authoritative draft projection owned by this model."""
        return self._draft_model.snapshot

    def provide_draft_snapshot(self) -> ConversationDraftSnapshot:
        """Bound-method draft provider for the host seam.

        A plain method (not a lambda closing over the Coordinator) keeps the
        host binding free of coordinator-capturing reference cycles.
        """
        return self._draft_model.snapshot

    def apply_draft_edit(
        self,
        intent: DraftEditIntent,
    ) -> ConversationDraftSnapshot:
        """Apply one host edit intent to the authoritative draft.

        A draft exists only while one logical Conversation context owns it
        (06 8.1, 07 20.3): without a context a stale/late host edit is a
        no-op and can never recreate an orphan draft.
        """
        if self._snapshot.conversation_context is None:
            return self._draft_model.snapshot
        return self._draft_model.edit(intent)

    def submit_draft(self) -> SubmittedDraftSnapshot | None:
        """Capture an inert submit snapshot; never invokes a backend.

        A submitted snapshot is always correlated to a logical Conversation
        context; without a context no snapshot may be created.
        """
        if self._snapshot.conversation_context is None:
            return None
        return self._draft_model.submit()

    def accept_draft(self, identity: str) -> ConversationDraftSnapshot:
        if self._snapshot.conversation_context is None:
            return self._draft_model.snapshot
        return self._draft_model.accept(identity)

    def reject_draft(self, identity: str) -> ConversationDraftSnapshot:
        if self._snapshot.conversation_context is None:
            return self._draft_model.snapshot
        return self._draft_model.reject(identity)

    def cancel_draft(self, identity: str) -> ConversationDraftSnapshot:
        if self._snapshot.conversation_context is None:
            return self._draft_model.snapshot
        return self._draft_model.cancel(identity)

    def discard_draft(self) -> ConversationDraftSnapshot:
        return self._draft_model.discard()

    def dispatch(
        self,
        intent: FrontendPresentationIntent,
    ) -> FrontendPresentationResult:
        if isinstance(intent, ConversationOpenOrRestoreIntent):
            return self._open_conversation(intent)
        if isinstance(intent, CollapseConversationIntent):
            return self._collapse_conversation()
        if isinstance(intent, CloseConversationIntent):
            return self._close_conversation()
        if isinstance(intent, ShowForegroundOverlayIntent):
            return self._show_foreground_overlay(intent.overlay)
        if isinstance(intent, DismissForegroundOverlayIntent):
            return self._dismiss_foreground_overlay()
        if isinstance(intent, SetPaletteLayerIntent):
            return self._set_palette_layer(intent.layer)
        raise TypeError(f"unsupported frontend presentation intent: {intent!r}")

    def _open_conversation(
        self,
        intent: ConversationOpenOrRestoreIntent,
    ) -> FrontendPresentationResult:
        snapshot = self._snapshot
        if snapshot.foreground_overlay in _BLOCKING_OVERLAYS:
            return FrontendPresentationResult(snapshot, ())

        effects: list[PresentationEffect] = []
        if snapshot.foreground_overlay is not ForegroundOverlay.NONE:
            effects.append(
                PresentationEffect(
                    PresentationEffectKind.DISMISS_FOREGROUND_OVERLAY,
                    overlay=snapshot.foreground_overlay,
                )
            )

        existing = snapshot.conversation_context
        if existing is None:
            context = ConversationContext(_CONVERSATION_CONTEXT_ID)
            # A brand-new logical Conversation starts with a fresh draft; a
            # restore path below preserves the authoritative draft (06 8.3).
            self._draft_model.discard()
            effects.append(
                PresentationEffect(
                    PresentationEffectKind.CREATE_CONVERSATION,
                    conversation_id=context.context_id,
                )
            )
        else:
            context = existing
            effects.append(
                PresentationEffect(
                    PresentationEffectKind.RESTORE_CONVERSATION,
                    conversation_id=context.context_id,
                )
            )

        effects.append(
            PresentationEffect(
                PresentationEffectKind.SET_SEMANTIC_FOCUS,
                focus_target=SemanticFocusTarget.CONVERSATION_INPUT,
            )
        )
        next_snapshot = FrontendPresentationSnapshot(
            primary_presentation=PrimaryPresentation.CAPSULE,
            foreground_overlay=ForegroundOverlay.NONE,
            conversation_context=context,
            semantic_focus_target=SemanticFocusTarget.CONVERSATION_INPUT,
            semantic_focus_return_target=None,
        )
        self._snapshot = next_snapshot
        return FrontendPresentationResult(next_snapshot, tuple(effects))

    def _close_conversation(self) -> FrontendPresentationResult:
        """Close is visibility-only (05 2.1.3); it never destroys state.

        The logical ConversationContext, its one authoritative draft, any
        in-flight submitted snapshot and any active IME composition are all
        preserved (06 8.1, 8.3): Close mirrors an ordinary collapse and emits
        a hide effect so the host hides while the context remains.  Logical
        destruction is reserved for explicitly authorized semantics only.
        """
        snapshot = self._snapshot
        context = snapshot.conversation_context
        if (
            context is None
            or snapshot.primary_presentation is not PrimaryPresentation.CAPSULE
        ):
            return FrontendPresentationResult(snapshot, ())

        next_snapshot = replace(
            snapshot,
            primary_presentation=PrimaryPresentation.CHARACTER,
            semantic_focus_target=SemanticFocusTarget.NONE,
            semantic_focus_return_target=None,
        )
        self._snapshot = next_snapshot
        return FrontendPresentationResult(
            next_snapshot,
            (
                PresentationEffect(
                    PresentationEffectKind.HIDE_CONVERSATION,
                    conversation_id=context.context_id,
                ),
                PresentationEffect(
                    PresentationEffectKind.SET_SEMANTIC_FOCUS,
                    focus_target=SemanticFocusTarget.NONE,
                ),
            ),
        )

    def _collapse_conversation(self) -> FrontendPresentationResult:
        snapshot = self._snapshot
        context = snapshot.conversation_context
        if (
            context is None
            or snapshot.primary_presentation is not PrimaryPresentation.CAPSULE
        ):
            return FrontendPresentationResult(snapshot, ())

        next_snapshot = replace(
            snapshot,
            primary_presentation=PrimaryPresentation.CHARACTER,
            semantic_focus_target=SemanticFocusTarget.NONE,
            semantic_focus_return_target=None,
        )
        self._snapshot = next_snapshot
        return FrontendPresentationResult(
            next_snapshot,
            (
                PresentationEffect(
                    PresentationEffectKind.HIDE_CONVERSATION,
                    conversation_id=context.context_id,
                ),
                PresentationEffect(
                    PresentationEffectKind.SET_SEMANTIC_FOCUS,
                    focus_target=SemanticFocusTarget.NONE,
                ),
            ),
        )


    def _show_foreground_overlay(
        self,
        overlay: ForegroundOverlay,
    ) -> FrontendPresentationResult:
        if overlay is ForegroundOverlay.NONE:
            return self._dismiss_foreground_overlay()

        snapshot = self._snapshot
        if snapshot.foreground_overlay in _BLOCKING_OVERLAYS:
            return FrontendPresentationResult(snapshot, ())
        if snapshot.foreground_overlay is overlay:
            return FrontendPresentationResult(snapshot, ())

        effects: list[PresentationEffect] = []
        next_snapshot = replace(
            snapshot,
            foreground_overlay=overlay,
            semantic_focus_return_target=snapshot.semantic_focus_target,
        )
        if overlay is ForegroundOverlay.PALETTE:
            # 06 9.4: Right Click always opens the Palette at ROOT.  The
            # model, not host residue, decides the reopened layer.
            next_snapshot = replace(
                next_snapshot,
                semantic_focus_target=SemanticFocusTarget.PALETTE,
                palette_layer=ActionPaletteLayer.ROOT,
            )
            effects.append(
                PresentationEffect(
                    PresentationEffectKind.SHOW_FOREGROUND_OVERLAY,
                    overlay=overlay,
                    layer=ActionPaletteLayer.ROOT,
                )
            )
            effects.append(
                PresentationEffect(
                    PresentationEffectKind.SET_SEMANTIC_FOCUS,
                    focus_target=SemanticFocusTarget.PALETTE,
                )
            )
        else:
            effects.append(
                PresentationEffect(
                    PresentationEffectKind.SHOW_FOREGROUND_OVERLAY,
                    overlay=overlay,
                )
            )
        self._snapshot = next_snapshot
        return FrontendPresentationResult(next_snapshot, tuple(effects))

    def _dismiss_foreground_overlay(self) -> FrontendPresentationResult:
        snapshot = self._snapshot
        if snapshot.foreground_overlay is ForegroundOverlay.NONE:
            return FrontendPresentationResult(snapshot, ())
        if snapshot.foreground_overlay in _BLOCKING_OVERLAYS:
            return FrontendPresentationResult(snapshot, ())

        overlay = snapshot.foreground_overlay
        focus_target = (
            snapshot.semantic_focus_return_target
            if snapshot.semantic_focus_return_target is not None
            else snapshot.semantic_focus_target
        )
        next_snapshot = replace(
            snapshot,
            foreground_overlay=ForegroundOverlay.NONE,
            semantic_focus_target=focus_target,
            semantic_focus_return_target=None,
            palette_layer=ActionPaletteLayer.ROOT,
        )
        self._snapshot = next_snapshot
        return FrontendPresentationResult(
            next_snapshot,
            (
                PresentationEffect(
                    PresentationEffectKind.DISMISS_FOREGROUND_OVERLAY,
                    overlay=overlay,
                ),
                PresentationEffect(
                    PresentationEffectKind.SET_SEMANTIC_FOCUS,
                    focus_target=focus_target,
                ),
            ),
        )

    def _set_palette_layer(
        self,
        layer: ActionPaletteLayer,
    ) -> FrontendPresentationResult:
        """Apply one same-shell Palette navigation step.

        Palette navigation is only meaningful while the Palette overlay is
        active; otherwise it is a no-op.  A transition to the current layer
        is also a no-op so repeated/re-entrant navigation cannot emit extra
        rerender effects.
        """
        snapshot = self._snapshot
        if snapshot.foreground_overlay is not ForegroundOverlay.PALETTE:
            return FrontendPresentationResult(snapshot, ())
        if snapshot.palette_layer is layer:
            return FrontendPresentationResult(snapshot, ())

        next_snapshot = replace(snapshot, palette_layer=layer)
        self._snapshot = next_snapshot
        return FrontendPresentationResult(
            next_snapshot,
            (
                PresentationEffect(
                    PresentationEffectKind.PALETTE_LAYER_CHANGED,
                    layer=layer,
                ),
            ),
        )


__all__ = [
    "ActionPaletteLayer",
    "CloseConversationIntent",
    "CollapseConversationIntent",
    "ConversationContext",
    "ConversationOpenOrRestoreIntent",
    "DismissForegroundOverlayIntent",
    "ForegroundOverlay",
    "FrontendPresentationIntent",
    "FrontendPresentationModel",
    "FrontendPresentationResult",
    "FrontendPresentationSnapshot",
    "PresentationEffect",
    "PresentationEffectKind",
    "PrimaryPresentation",
    "SemanticFocusTarget",
    "SetPaletteLayerIntent",
    "ShowForegroundOverlayIntent",
]
