"""Slice 7E - Dashboard Character Animation page (frozen geometry + capability).

Authority: 07 section 10 and tokens component.dashboard.character_animation /
character_model.motion.character_switch: page max 1120, Preview preferred
640x480 / min 560x360, Character card 144x176, Animation card 168x104, grid
gap 16, preview/control gap 24, control height 44.  The page is a pure
presentation surface: it renders a
:class:`~arkclaw.presentation.dashboard_presentation.CharacterAnimationSnapshot`
and emits narrow selection intents.  The "Active Character" term comes from
the frozen character model tokens; "Schwarz" may only surface as the
reference character.  Animation inventory is capability-driven: only
capabilities the Active Character manifest provides are rendered, and
unsupported / trigger-unavailable cards show a readable disabled reason.
Switch uses a 180 ms cancelable preview crossfade (60 ms under reduced
motion) that is never semantic truth.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from arkclaw.presentation.dashboard_presentation import (
    ActiveCharacterSummary,
    AnimationItem,
    AnimationState,
    CharacterAnimationSnapshot,
)
from arkclaw.presentation.qt.dashboard.pages.character_animation_page import (
    CharacterAnimationPage,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, apply_theme


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
    yield application


@pytest.fixture(scope="module")
def tokens():
    return load_design_tokens()


def _flush(application: QApplication) -> None:
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _show(page: QWidget, application: QApplication) -> None:
    page.show()
    application.processEvents()


def _default_snapshot() -> CharacterAnimationSnapshot:
    return CharacterAnimationSnapshot(
        active_character=ActiveCharacterSummary(
            available=True,
            display_name="Schwarz",
            is_reference=True,
            reference_name="Schwarz",
        ),
        available_characters=("Schwarz", "Liskarm"),
        animations=(
            AnimationItem("relax", "Relax"),
            AnimationItem("sit", "Sit", AnimationState.PLAYING),
            AnimationItem(
                "special",
                "Special",
                AnimationState.UNSUPPORTED,
                disabled_reason="Not available for this character",
            ),
            AnimationItem(
                "sleep",
                "Sleep",
                AnimationState.TRIGGER_UNAVAILABLE,
                disabled_reason="Desktop trigger unavailable while working",
            ),
        ),
    )


def test_character_animation_frozen_geometry(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    assert page.content_max_width() == 1120
    preview = page.preview_frame()
    assert preview.minimumWidth() == 560
    assert preview.minimumHeight() == 360
    assert preview.sizeHint().width() == 640
    assert preview.sizeHint().height() == 480
    assert page.character_card_size() == (144, 176)
    assert page.animation_card_size() == (168, 104)
    assert page.grid_gap() == 16
    assert page.preview_controls_gap() == 24
    assert page.preview_control_height() == 44
    page.dispose()
    _flush(QApplication.instance())


def test_header_uses_active_character_and_reference_copy(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())
    assert "Active Character" in page.header_title().text()
    assert page.header_name_label().text() == "Schwarz"
    reference = page.header_reference_label()
    assert reference.isVisible()
    assert "Reference Character" in reference.text()
    assert "Schwarz" in reference.text()
    page.dispose()
    _flush(QApplication.instance())


def test_header_never_hardcodes_schwarz_as_product_label(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(
                display_name="Liskarm", is_reference=False
            ),
            available_characters=("Liskarm",),
        )
    )
    assert "Active Character" in page.header_title().text()
    assert page.header_name_label().text() == "Liskarm"
    assert not page.header_reference_label().isVisible()
    page.dispose()
    _flush(QApplication.instance())


def test_character_selector_one_character_does_not_fabricate(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Liskarm"),
            available_characters=("Liskarm",),
        )
    )
    cards = page.character_cards()
    assert len(cards) == 1
    assert "Liskarm" in cards[0].name_label().text()
    assert page.character_switch_button(0) is not None
    page.dispose()
    _flush(QApplication.instance())


def test_character_selector_empty_renders_no_candidates(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Schwarz"),
            available_characters=(),
        )
    )
    assert page.character_cards() == []
    empty_label = page.character_selector_empty_label()
    assert empty_label.isVisible()
    assert "No other characters" in empty_label.text()
    page.dispose()
    _flush(QApplication.instance())


def test_current_character_marker_is_non_color_only(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    cards = page.character_cards()
    assert len(cards) == 2
    current = next(
        card for card in cards if card.name_label().text() == "Schwarz"
    )
    assert current.is_current()
    assert current.current_marker().text().strip()
    page.dispose()
    _flush(QApplication.instance())


def test_switch_character_emits_narrow_signal(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    spy = QSignalSpy(page.character_selected)
    target = next(
        card for card in page.character_cards()
        if card.name_label().text() == "Liskarm"
    )
    target.switch_button().click()
    assert spy.count() == 1
    assert spy.at(0)[0] == "Liskarm"
    page.dispose()
    _flush(QApplication.instance())


def test_preview_placeholder_label_present(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())
    placeholder = page.preview_placeholder_label()
    assert placeholder.isVisible()
    assert placeholder.text().strip() == "Visual placeholder"
    page.dispose()
    _flush(QApplication.instance())


def test_preview_loading_switching_and_renderer_failure(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Schwarz"),
            preview_loading=True,
        )
    )
    assert page.preview_status_label().isVisible()
    assert "Loading" in page.preview_status_label().text()
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Schwarz"),
            preview_error="Spine renderer failed to start",
        )
    )
    assert page.preview_status_label().isVisible()
    assert "renderer" in page.preview_status_label().text().lower()
    assert page.preview_retry_button().isVisible()
    spy = QSignalSpy(page.preview_retry_requested)
    page.preview_retry_button().click()
    assert spy.count() == 1
    page.dispose()
    _flush(QApplication.instance())


def test_switch_crossfade_is_cancelable_and_motion_aware(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    assert page.switch_crossfade_duration_ms() == 180
    page.apply_snapshot(_default_snapshot())
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Liskarm"),
            available_characters=("Liskarm",),
        )
    )
    page.cancel_switch_crossfade()
    assert not page.preview_crossfade_active()
    page.dispose()
    _flush(QApplication.instance())


def test_switch_crossfade_respects_reduced_motion(
    qt_application: QApplication, monkeypatch
) -> None:
    monkeypatch.setenv("ARKCLAW_REDUCED_MOTION", "1")
    page = CharacterAnimationPage()
    assert page.switch_crossfade_duration_ms() == 60
    page.dispose()
    _flush(QApplication.instance())


def test_animation_inventory_is_capability_driven(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    cards = page.animation_cards()
    assert len(cards) == 4
    assert [card.name_label().text() for card in cards] == [
        "Relax", "Sit", "Special", "Sleep",
    ]
    page.dispose()
    _flush(QApplication.instance())


def test_animation_card_controls_and_signals(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    preview_spy = QSignalSpy(page.animation_preview_requested)
    play_spy = QSignalSpy(page.animation_play_requested)
    trigger_spy = QSignalSpy(page.animation_trigger_requested)
    card = page.animation_cards()[0]
    assert card.preview_button().text() == "Preview"
    assert card.play_button().text() == "Play"
    assert card.trigger_button().text() == "Trigger on Desktop"
    card.preview_button().click()
    card.play_button().click()
    card.trigger_button().click()
    assert preview_spy.count() == 1
    assert preview_spy.at(0)[0] == "relax"
    assert play_spy.count() == 1
    assert play_spy.at(0)[0] == "relax"
    assert trigger_spy.count() == 1
    assert trigger_spy.at(0)[0] == "relax"
    page.dispose()
    _flush(QApplication.instance())


def test_unsupported_animation_is_readable_and_disabled(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())
    card = page.animation_cards()[2]
    assert card.state_label().text() == "Unsupported"
    assert card.disabled_reason_label().isVisible()
    assert "Not available" in card.disabled_reason_label().text()
    assert not card.preview_button().isEnabled()
    assert not card.play_button().isEnabled()
    assert not card.trigger_button().isEnabled()
    page.dispose()
    _flush(QApplication.instance())


def test_trigger_unavailable_disables_only_trigger(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())
    card = page.animation_cards()[3]
    assert card.state_label().text() == "Trigger unavailable"
    assert card.disabled_reason_label().isVisible()
    assert "working" in card.disabled_reason_label().text()
    assert card.preview_button().isEnabled()
    assert card.play_button().isEnabled()
    assert not card.trigger_button().isEnabled()
    page.dispose()
    _flush(QApplication.instance())


def test_playing_state_is_rendered_as_text_not_color_only(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    card = page.animation_cards()[1]
    assert "Playing" in card.state_label().text()
    page.dispose()
    _flush(QApplication.instance())


def test_preview_control_strip_geometry_and_selection(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    strip = page.preview_control_strip()
    assert strip.minimumHeight() == 44
    assert page.preview_controls_gap() == 24
    assert not page.strip_preview_button().isEnabled()
    page.select_card(0)
    assert page.selected_card() is page.animation_cards()[0]
    assert page.animation_cards()[0].is_selected()
    assert page.strip_play_button().isEnabled()
    spy = QSignalSpy(page.animation_play_requested)
    page.strip_play_button().click()
    assert spy.count() == 1
    assert spy.at(0)[0] == "relax"
    page.dispose()
    _flush(QApplication.instance())


def test_theme_switch_preserves_page_state(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    apply_theme(page, QtTheme.LIGHT)
    apply_theme(page, QtTheme.DARK)
    assert page.styleSheet() != ""
    assert len(page.animation_cards()) == 4
    page.dispose()
    _flush(QApplication.instance())


def test_dispose_is_idempotent_and_leaves_no_toplevel(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.dispose()
    page.dispose()
    _flush(QApplication.instance())
    assert not any(
        isinstance(widget, CharacterAnimationPage)
        for widget in QApplication.topLevelWidgets()
    )


def test_character_animation_page_uses_two_column_workbench(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())
    sidebar = page.findChild(QWidget, "sidebarWidget")
    stage = page.findChild(QWidget, "stageFrame")
    assert sidebar is not None
    assert stage is not None
    assert sidebar.minimumWidth() >= 220
    assert stage.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    page.dispose()
    _flush(QApplication.instance())


def test_header_updates_when_active_character_changes(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Amiya"),
            available_characters=("Amiya", "Schwarz"),
        )
    )
    assert page.header_name_label().text() == "Amiya"
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Texas"),
            available_characters=("Texas",),
        )
    )
    assert page.header_name_label().text() == "Texas"
    page.dispose()
    _flush(QApplication.instance())


def test_animation_cards_are_generated_from_snapshot_only(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(
        CharacterAnimationSnapshot(
            active_character=ActiveCharacterSummary(display_name="Schwarz"),
            available_characters=("Schwarz",),
            animations=(
                AnimationItem(
                    action_id="custom_special_action",
                    name="Custom Special Action",
                ),
            ),
        )
    )
    cards = page.animation_cards()
    assert len(cards) == 1
    assert cards[0].action_id() == "custom_special_action"
    assert cards[0].name_label().text() == "Custom Special Action"
    page.dispose()
    _flush(QApplication.instance())


def test_click_animation_card_updates_exactly_one_selected_card_and_requests_preview(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())
    spy_preview = QSignalSpy(page.animation_preview_requested)
    spy_trigger = QSignalSpy(page.animation_trigger_requested)

    cards = page.animation_cards()
    assert len(cards) >= 2

    # Click the second card ("sit")
    cards[1].mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(cards[1].rect().center()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert page.selected_card() is cards[1]
    assert cards[1].is_selected()
    assert not cards[0].is_selected()
    assert spy_preview.count() == 1
    assert spy_preview.at(0)[0] == "sit"
    assert spy_trigger.count() == 0

    page.dispose()
    _flush(QApplication.instance())


def test_selection_is_preserved_when_animation_model_refreshes(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    page.apply_snapshot(_default_snapshot())
    page.select_card(1, emit_preview=False)
    assert page.selected_card() is page.animation_cards()[1]

    # Refresh snapshot with same animations
    page.apply_snapshot(_default_snapshot())
    assert page.selected_card() is not None
    assert page.selected_card().action_id() == "sit"
    page.dispose()
    _flush(QApplication.instance())


def test_preview_and_play_never_dispatch_desktop_trigger(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage()
    _show(page, QApplication.instance())
    page.apply_snapshot(_default_snapshot())

    spy_trigger = QSignalSpy(page.animation_trigger_requested)
    spy_preview = QSignalSpy(page.animation_preview_requested)
    spy_play = QSignalSpy(page.animation_play_requested)

    page.select_card(0, emit_preview=False)

    # Click Preview
    page.strip_preview_button().click()
    assert spy_preview.count() == 1
    assert spy_trigger.count() == 0

    # Click Play
    page.strip_play_button().click()
    assert spy_play.count() == 1
    assert spy_trigger.count() == 0

    # Only Trigger on Desktop emits trigger
    page.strip_trigger_button().click()
    assert spy_trigger.count() == 1
    assert spy_trigger.at(0)[0] == "relax"

    page.dispose()
    _flush(QApplication.instance())


def test_reopen_character_animation_page_does_not_duplicate_signal_connections(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    # First instance
    page1 = CharacterAnimationPage()
    page1.apply_snapshot(_default_snapshot())
    page1.dispose()
    _flush(QApplication.instance())

    # Second instance
    page2 = CharacterAnimationPage()
    page2.apply_snapshot(_default_snapshot())
    spy_play = QSignalSpy(page2.animation_play_requested)
    page2.select_card(0, emit_preview=False)
    page2.strip_play_button().click()
    assert spy_play.count() == 1
    page2.dispose()
    _flush(QApplication.instance())


def test_character_animation_page_live_preview_composition(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    from arkclaw.bootstrap.pet_production import (
        create_optional_production_pet_composition,
    )
    from arkclaw.presentation.qt.pet.spine38_renderer import Spine38RendererError

    try:
        composition = create_optional_production_pet_composition()
        if composition is None:
            return
        page = CharacterAnimationPage(
            tokens, enable_live_preview=True, composition=composition
        )
        page.apply_snapshot(_default_snapshot())
        _show(page, QApplication.instance())
        if page.spine_preview_widget() is not None:
            assert page.spine_preview_widget().isVisible()
            for action in (
                "relax",
                "move_left",
                "move_right",
                "sit",
                "sleep",
                "special",
                "interact",
            ):
                page.spine_preview_widget().play_action(action)
            page.select_card(0)
        page.dispose()
        _flush(QApplication.instance())
    except Spine38RendererError:
        pass


def test_animation_cards_support_light_and_dark_theme(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = CharacterAnimationPage(tokens)
    page.apply_snapshot(_default_snapshot())
    _show(page, QApplication.instance())

    # Switch to LIGHT theme and check cards
    page.set_theme(QtTheme.LIGHT)
    cards = page.animation_cards()
    assert len(cards) >= 4
    page.select_card(0)
    assert cards[0].is_selected()

    # Switch to DARK theme and check cards
    page.set_theme(QtTheme.DARK)
    assert cards[0].is_selected()
    page.dispose()
    _flush(QApplication.instance())


def test_spine_preview_widget_expands_to_stage_frame(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    from arkclaw.bootstrap.pet_production import (
        create_optional_production_pet_composition,
    )

    composition = create_optional_production_pet_composition()
    if composition is None:
        return
    page = CharacterAnimationPage(
        tokens, enable_live_preview=True, composition=composition
    )
    _show(page, QApplication.instance())
    spine_widget = page.spine_preview_widget()
    if spine_widget is not None:
        assert (
            spine_widget.sizePolicy().horizontalPolicy()
            == QSizePolicy.Policy.Expanding
        )
        assert (
            spine_widget.sizePolicy().verticalPolicy()
            == QSizePolicy.Policy.Expanding
        )
        assert spine_widget.minimumWidth() >= 320
        assert spine_widget.minimumHeight() >= 240
    page.dispose()
    _flush(QApplication.instance())


