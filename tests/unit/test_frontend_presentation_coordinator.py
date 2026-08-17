from __future__ import annotations

from arkclaw.presentation.frontend_presentation import (
    ConversationOpenOrRestoreIntent,
    FrontendPresentationModel,
    PresentationEffect,
    PresentationEffectKind,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)


class _RecordingEffectSink:
    def __init__(self) -> None:
        self.effects: list[PresentationEffect] = []

    def apply(self, effect: PresentationEffect) -> None:
        self.effects.append(effect)


def test_coordinator_delegates_to_model_and_executes_effects_in_order() -> None:
    model = FrontendPresentationModel()
    sink = _RecordingEffectSink()
    coordinator = FrontendPresentationCoordinator(model=model, effect_sink=sink)

    result = coordinator.dispatch(
        ConversationOpenOrRestoreIntent()
    )

    assert result.snapshot == model.snapshot
    assert sink.effects == list(result.effects)
    assert [effect.kind for effect in sink.effects] == [
        PresentationEffectKind.CREATE_CONVERSATION,
        PresentationEffectKind.SET_SEMANTIC_FOCUS,
    ]
    assert coordinator.snapshot == model.snapshot


def test_coordinator_is_not_a_second_state_owner() -> None:
    model = FrontendPresentationModel()
    sink = _RecordingEffectSink()
    coordinator = FrontendPresentationCoordinator(model=model, effect_sink=sink)

    coordinator.dispatch(ConversationOpenOrRestoreIntent())
    coordinator.dispatch(ConversationOpenOrRestoreIntent())

    assert coordinator.snapshot == model.snapshot
    assert sum(
        effect.kind is PresentationEffectKind.CREATE_CONVERSATION
        for effect in sink.effects
    ) == 1
    assert sum(
        effect.kind is PresentationEffectKind.RESTORE_CONVERSATION
        for effect in sink.effects
    ) == 1
