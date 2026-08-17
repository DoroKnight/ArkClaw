from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import arkclaw.presentation.frontend_presentation as frontend


def test_initial_snapshot_is_deterministic_and_character_only() -> None:
    first = frontend.FrontendPresentationModel().snapshot
    second = frontend.FrontendPresentationModel().snapshot

    assert first == second
    assert first.primary_presentation is frontend.PrimaryPresentation.CHARACTER
    assert first.foreground_overlay is frontend.ForegroundOverlay.NONE
    assert first.conversation_context is None
    assert first.semantic_focus_target is frontend.SemanticFocusTarget.NONE


def test_open_conversation_creates_one_context_and_orders_effects() -> None:
    model = frontend.FrontendPresentationModel()

    result = model.dispatch(
        frontend.ConversationOpenOrRestoreIntent()
    )

    assert result.snapshot.primary_presentation is frontend.PrimaryPresentation.CAPSULE
    assert result.snapshot.conversation_context is not None
    assert (
        result.snapshot.semantic_focus_target
        is frontend.SemanticFocusTarget.CONVERSATION_INPUT
    )
    assert [effect.kind for effect in result.effects] == [
        frontend.PresentationEffectKind.CREATE_CONVERSATION,
        frontend.PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]


def test_repeated_open_same_conversation_restores_without_duplicate() -> None:
    model = frontend.FrontendPresentationModel()
    first = model.dispatch(frontend.ConversationOpenOrRestoreIntent())

    result = model.dispatch(frontend.ConversationOpenOrRestoreIntent())

    assert result.snapshot.conversation_context is not None
    assert result.snapshot.conversation_context is first.snapshot.conversation_context
    assert [effect.kind for effect in result.effects] == [
        frontend.PresentationEffectKind.RESTORE_CONVERSATION,
        frontend.PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert frontend.PresentationEffectKind.CREATE_CONVERSATION not in {
        effect.kind for effect in result.effects
    }


def test_palette_dismisses_before_conversation_opens() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE))

    result = model.dispatch(frontend.ConversationOpenOrRestoreIntent())

    assert result.snapshot.foreground_overlay is frontend.ForegroundOverlay.NONE
    assert [effect.kind for effect in result.effects] == [
        frontend.PresentationEffectKind.DISMISS_FOREGROUND_OVERLAY,
        frontend.PresentationEffectKind.CREATE_CONVERSATION,
        frontend.PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]


def test_palette_roundtrip_preserves_one_logical_conversation_context() -> None:
    model = frontend.FrontendPresentationModel()
    opened = model.dispatch(frontend.ConversationOpenOrRestoreIntent())
    original_context = opened.snapshot.conversation_context

    shown = model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    assert shown.snapshot.foreground_overlay is frontend.ForegroundOverlay.PALETTE
    assert shown.snapshot.primary_presentation is frontend.PrimaryPresentation.CAPSULE
    assert shown.snapshot.conversation_context is original_context
    assert shown.snapshot.semantic_focus_target is frontend.SemanticFocusTarget.PALETTE
    assert (
        shown.snapshot.semantic_focus_return_target
        is frontend.SemanticFocusTarget.CONVERSATION_INPUT
    )
    assert frontend.PresentationEffectKind.SHOW_FOREGROUND_OVERLAY in {
        effect.kind for effect in shown.effects
    }

    dismissed = model.dispatch(frontend.DismissForegroundOverlayIntent())

    assert dismissed.snapshot.foreground_overlay is frontend.ForegroundOverlay.NONE
    assert dismissed.snapshot.primary_presentation is frontend.PrimaryPresentation.CAPSULE
    assert dismissed.snapshot.conversation_context is original_context
    assert (
        dismissed.snapshot.semantic_focus_target
        is frontend.SemanticFocusTarget.CONVERSATION_INPUT
    )
    assert dismissed.snapshot.semantic_focus_return_target is None


def test_character_palette_roundtrip_restores_previous_semantic_focus() -> None:
    model = frontend.FrontendPresentationModel()

    shown = model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    assert shown.snapshot.semantic_focus_target is frontend.SemanticFocusTarget.PALETTE
    assert shown.snapshot.semantic_focus_return_target is (
        frontend.SemanticFocusTarget.NONE
    )

    dismissed = model.dispatch(frontend.DismissForegroundOverlayIntent())

    assert dismissed.snapshot.foreground_overlay is frontend.ForegroundOverlay.NONE
    assert dismissed.snapshot.semantic_focus_target is (
        frontend.SemanticFocusTarget.NONE
    )
    assert dismissed.snapshot.semantic_focus_return_target is None


def test_blocking_overlay_rejects_conversation_and_ordinary_dismiss() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(
        frontend.ShowForegroundOverlayIntent(
            frontend.ForegroundOverlay.CONFIRMATION
        )
    )

    blocked = model.dispatch(frontend.ConversationOpenOrRestoreIntent())
    dismissed = model.dispatch(frontend.DismissForegroundOverlayIntent())

    assert blocked.snapshot.foreground_overlay is frontend.ForegroundOverlay.CONFIRMATION
    assert blocked.effects == ()
    assert dismissed.snapshot.foreground_overlay is frontend.ForegroundOverlay.CONFIRMATION
    assert dismissed.effects == ()


def test_blocking_overlay_rejects_palette_override() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(
        frontend.ShowForegroundOverlayIntent(
            frontend.ForegroundOverlay.CONFIRMATION
        )
    )
    before = model.snapshot

    result = model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    assert result.snapshot == before
    assert result.effects == ()


def test_dismiss_palette_clears_non_blocking_overlay() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE))

    result = model.dispatch(frontend.DismissForegroundOverlayIntent())

    assert result.snapshot.foreground_overlay is frontend.ForegroundOverlay.NONE
    assert result.snapshot.semantic_focus_target is frontend.SemanticFocusTarget.NONE
    assert [effect.kind for effect in result.effects] == [
        frontend.PresentationEffectKind.DISMISS_FOREGROUND_OVERLAY,
        frontend.PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]


def test_snapshot_and_result_are_immutable_values() -> None:
    snapshot = frontend.FrontendPresentationModel().snapshot

    with pytest.raises(FrozenInstanceError):
        snapshot.primary_presentation = (  # type: ignore[misc]
            frontend.PrimaryPresentation.CAPSULE
        )

    result = frontend.FrontendPresentationModel().dispatch(
        frontend.ConversationOpenOrRestoreIntent()
    )
    with pytest.raises(FrozenInstanceError):
        result.snapshot = snapshot  # type: ignore[misc]


def test_model_module_has_no_qt_dependency() -> None:
    source = Path(frontend.__file__).read_text(encoding="utf-8")

    assert "PySide6" not in source
    assert "QApplication" not in source

def test_collapse_preserves_context_and_restore_reuses_it() -> None:
    model = frontend.FrontendPresentationModel()
    opened = model.dispatch(frontend.ConversationOpenOrRestoreIntent())
    original_context = opened.snapshot.conversation_context
    assert original_context is not None

    collapsed = model.dispatch(frontend.CollapseConversationIntent())

    assert collapsed.snapshot.primary_presentation is frontend.PrimaryPresentation.CHARACTER
    assert collapsed.snapshot.conversation_context is original_context
    assert collapsed.snapshot.semantic_focus_target is frontend.SemanticFocusTarget.NONE
    assert [effect.kind for effect in collapsed.effects] == [
        frontend.PresentationEffectKind.HIDE_CONVERSATION,
        frontend.PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]

    restored = model.dispatch(frontend.ConversationOpenOrRestoreIntent())

    assert restored.snapshot.primary_presentation is frontend.PrimaryPresentation.CAPSULE
    assert restored.snapshot.conversation_context is original_context
    assert frontend.PresentationEffectKind.RESTORE_CONVERSATION in {
        effect.kind for effect in restored.effects
    }
    assert frontend.PresentationEffectKind.CREATE_CONVERSATION not in {
        effect.kind for effect in restored.effects
    }


# --- Slice 5B same-shell Palette layer: Qt-free model truth ---
#
# Authority: 06 9.4 ("Right Click -> Root"; "Secondary layer + Back/Escape ->
# Root"; "Root + Escape/Outside Click -> dismiss"), 07 21 ("One lazy host;
# Root, Character, System are the same shell"), 08 14.2 ("sublevel/back").


def test_palette_show_sets_layer_to_root_and_carries_it_on_the_effect() -> None:
    model = frontend.FrontendPresentationModel()

    result = model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    assert result.snapshot.foreground_overlay is frontend.ForegroundOverlay.PALETTE
    assert result.snapshot.palette_layer is frontend.ActionPaletteLayer.ROOT
    show = [
        effect
        for effect in result.effects
        if effect.kind is frontend.PresentationEffectKind.SHOW_FOREGROUND_OVERLAY
    ]
    assert len(show) == 1
    assert show[0].overlay is frontend.ForegroundOverlay.PALETTE
    assert show[0].layer is frontend.ActionPaletteLayer.ROOT


def test_set_palette_layer_intent_updates_model_and_emits_change_effect() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    result = model.dispatch(
        frontend.SetPaletteLayerIntent(frontend.ActionPaletteLayer.CHARACTER)
    )

    assert result.snapshot.palette_layer is frontend.ActionPaletteLayer.CHARACTER
    assert result.effects == (
        frontend.PresentationEffect(
            frontend.PresentationEffectKind.PALETTE_LAYER_CHANGED,
            layer=frontend.ActionPaletteLayer.CHARACTER,
        ),
    )


def test_set_palette_layer_while_palette_hidden_is_a_noop() -> None:
    model = frontend.FrontendPresentationModel()

    result = model.dispatch(
        frontend.SetPaletteLayerIntent(frontend.ActionPaletteLayer.SYSTEM)
    )

    assert result.snapshot.palette_layer is frontend.ActionPaletteLayer.ROOT
    assert result.effects == ()


def test_set_palette_layer_to_current_layer_is_a_noop() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    result = model.dispatch(
        frontend.SetPaletteLayerIntent(frontend.ActionPaletteLayer.ROOT)
    )

    assert result.snapshot.palette_layer is frontend.ActionPaletteLayer.ROOT
    assert result.effects == ()


def test_palette_dismiss_resets_layer_to_root() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )
    model.dispatch(
        frontend.SetPaletteLayerIntent(frontend.ActionPaletteLayer.SYSTEM)
    )

    dismissed = model.dispatch(frontend.DismissForegroundOverlayIntent())

    assert dismissed.snapshot.foreground_overlay is frontend.ForegroundOverlay.NONE
    assert dismissed.snapshot.palette_layer is frontend.ActionPaletteLayer.ROOT


def test_palette_reopen_always_returns_to_root_layer() -> None:
    model = frontend.FrontendPresentationModel()
    model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )
    model.dispatch(
        frontend.SetPaletteLayerIntent(frontend.ActionPaletteLayer.SYSTEM)
    )
    model.dispatch(frontend.DismissForegroundOverlayIntent())

    reopened = model.dispatch(
        frontend.ShowForegroundOverlayIntent(frontend.ForegroundOverlay.PALETTE)
    )

    assert reopened.snapshot.foreground_overlay is frontend.ForegroundOverlay.PALETTE
    assert reopened.snapshot.palette_layer is frontend.ActionPaletteLayer.ROOT
