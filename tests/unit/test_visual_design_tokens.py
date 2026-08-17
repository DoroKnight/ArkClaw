"""Slice 7A - Visual Freeze v1 design token source (Qt-free).

Authority: docs/design/07-visual-design-freeze-v1.md section 5/17 and
docs/design/visual-freeze-v1.tokens.json (schema_version 2).  The tokens JSON
is the single machine-readable source; components must consume semantic
accessors instead of scattering raw color/dimension literals.

Contracts proven here:
- the frozen JSON loads and exposes the product/character model;
- light and dark expose the SAME semantic color contract
  (surface.*, text.*, border.*, focus.*, accent.*, state.*);
- frozen typography / spacing / radius / icon / motion values are exact;
- frozen component geometry (dashboard shell, navigation, home, chat_work,
  composer, attachment, artifact, character_animation) is exact;
- the frozen state and presentation maps are present.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    ThemeVariant,
    load_design_tokens,
)


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    return load_design_tokens()


def test_frozen_json_is_the_single_source(tokens: DesignTokens) -> None:
    assert tokens.schema_version == 2
    assert tokens.name == "ArkClaw Visual Design System v1"
    assert tokens.units == "qt_logical_px"


def test_character_agnostic_product_model(tokens: DesignTokens) -> None:
    assert tokens.product_term == "Active Character"
    assert tokens.reference_character == "Schwarz"
    assert tokens.primary_navigation == (
        "home",
        "chat_work",
        "character_animation",
    )
    assert "settings" not in tokens.primary_navigation


def test_font_family_contract(tokens: DesignTokens) -> None:
    assert tokens.font_family[:4] == (
        "Segoe UI Variable Text",
        "Microsoft YaHei UI",
        "Segoe UI",
        "sans-serif",
    )


def test_light_semantic_color_contract(tokens: DesignTokens) -> None:
    light = tokens.theme(ThemeVariant.LIGHT)
    assert light.surface.background == "#F6F8FC"
    assert light.surface.surface == "#FFFFFF"
    assert light.surface.surface_card == "#FFFFFF"
    assert light.surface.surface_nav == "#F2F5FA"
    assert light.surface.surface_input == "#F1F3F7"
    assert light.surface.surface_hover == "#EEF0FF"
    assert light.surface.surface_active == "#E3E7F8"
    assert light.surface.surface_selected == "#EEF0FF"
    assert light.text.primary == "#202124"
    assert light.text.secondary == "#5F6368"
    assert light.text.tertiary == "#6F747B"
    assert light.text.disabled == "#6B7077"
    assert light.border.default == "#DADCE0"
    assert light.border.divider == "#E4E7EB"
    assert light.focus == "#5066D6"
    assert light.accent.default == "#5B6FD8"
    assert light.accent.hover == "#4F61C6"
    assert light.accent.soft == "#EEF0FF"
    assert light.state.danger == "#B3261E"
    assert light.state.danger_soft == "#FCE8E6"
    assert light.state.warning == "#8A5A12"
    assert light.state.success == "#3C7A57"
    assert light.icon == "#5F6368"


def test_dark_semantic_color_contract(tokens: DesignTokens) -> None:
    dark = tokens.theme(ThemeVariant.DARK)
    assert dark.surface.background == "#17181B"
    assert dark.surface.surface == "#222327"
    assert dark.surface.surface_nav == "#1D1E22"
    assert dark.surface.surface_input == "#292A2F"
    assert dark.text.primary == "#F1F3F4"
    assert dark.text.secondary == "#BDC1C6"
    assert dark.text.tertiary == "#9AA0A6"
    assert dark.border.default == "#3C4043"
    assert dark.focus == "#C6CCFF"
    assert dark.accent.default == "#AEB7FF"
    assert dark.state.danger == "#FFB4AB"
    assert dark.state.success == "#8DD8A7"
    assert dark.icon == "#BDC1C6"


def test_light_and_dark_share_one_semantic_contract(tokens: DesignTokens) -> None:
    light = tokens.theme(ThemeVariant.LIGHT)
    dark = tokens.theme(ThemeVariant.DARK)
    assert _flatten(light) == _flatten(dark)
    assert light.surface.background != dark.surface.background


def test_typography_frozen_values(tokens: DesignTokens) -> None:
    typography = tokens.typography
    assert typography["display"] == (28, 36, 600)
    assert typography["page_title"] == (24, 32, 600)
    assert typography["title"] == (22, 30, 550)
    assert typography["section"] == (16, 24, 600)
    assert typography["composer"] == (15, 22, 400)
    assert typography["body"] == (14, 20, 400)
    assert typography["label"] == (14, 20, 500)
    assert typography["navigation"] == (14, 20, 500)
    assert typography["agent_status"] == (12, 18, 500)
    assert typography["caption"] == (12, 16, 400)


def test_spacing_frozen_values(tokens: DesignTokens) -> None:
    assert tokens.spacing_scale == (4, 8, 12, 16, 20, 24, 32, 40, 48)
    assert tokens.spacing["page_gutter"] == 40
    assert tokens.spacing["compact_gutter"] == 32
    assert tokens.spacing["app_shell_internal"] == 16
    assert tokens.spacing["composer_padding"] == 16
    assert tokens.spacing["conversation_block_gap"] == 24


def test_radius_frozen_values(tokens: DesignTokens) -> None:
    assert tokens.radius["navigation_row"] == 12
    assert tokens.radius["button"] == 12
    assert tokens.radius["card"] == 16
    assert tokens.radius["app_content"] == 16
    assert tokens.radius["palette"] == 16
    assert tokens.radius["composer"] == 24
    assert tokens.radius["capsule"] == 24
    assert tokens.radius["pill"] == 999


def test_icon_frozen_values(tokens: DesignTokens) -> None:
    assert tokens.icon["navigation"] == 20
    assert tokens.icon["action"] == 20
    assert tokens.icon["small"] == 16
    assert tokens.icon["file_image"] == 18
    assert tokens.icon["agent_thinking"] == 20
    assert tokens.icon["stroke"] == 1.75
    assert tokens.icon["default_hit_target"] == 40


def test_motion_frozen_values(tokens: DesignTokens) -> None:
    assert tokens.motion["hover"] == {"duration_ms": 100, "easing": "linear"}
    assert tokens.motion["press"] == {"duration_ms": 80, "easing": "linear"}
    assert tokens.motion["palette_open"] == {
        "duration_ms": 160,
        "translate_px": 4,
        "scale_from": 0.98,
    }
    assert tokens.motion["capsule_expand"] == {"duration_ms": 220}
    assert tokens.motion["navigation_toggle"] == {"duration_ms": 180}
    assert tokens.motion["dashboard_page_change"] == {
        "duration_ms": 160,
        "translate_px": 4,
    }
    assert tokens.motion["reduced_motion_crossfade_ms"] == 60
    assert "cancelable" in tokens.motion["requirements"]
    assert "not_semantic_truth" in tokens.motion["requirements"]


def test_dashboard_window_geometry_frozen(tokens: DesignTokens) -> None:
    window = tokens.component["dashboard"]["window"]
    assert window["default_width"] == 1280
    assert window["default_height"] == 800
    assert window["minimum_width"] == 1024
    assert window["minimum_height"] == 680
    assert window["top_app_shell_height"] == 56
    assert window["global_content_max_width"] == 1120
    assert window["page_gutter"] == 40
    assert window["compact_gutter"] == 32


def test_navigation_geometry_frozen(tokens: DesignTokens) -> None:
    navigation = tokens.component["dashboard"]["navigation"]
    assert navigation["expanded_width"] == 208
    assert navigation["collapsed_width"] == 72
    assert navigation["row_height"] == 44
    assert navigation["row_radius"] == 12
    assert navigation["leading_inset"] == 16
    assert navigation["icon_size"] == 20
    assert navigation["icon_text_gap"] == 12
    assert navigation["active_indicator_width"] == 3
    assert navigation["active_indicator_height"] == 24
    assert navigation["toggle_hit_target"] == 40
    assert tuple(navigation["items"]) == tokens.primary_navigation


def test_home_geometry_frozen(tokens: DesignTokens) -> None:
    home = tokens.component["dashboard"]["home"]
    assert home["content_max_width"] == 1040
    assert home["top_padding"] == 40
    assert home["ask_max_width"] == 720
    assert home["ask_height"] == 64
    assert home["ask_radius"] == 24
    assert home["section_gap"] == 32
    assert home["card_padding"] == 20
    assert home["recent_card_min_width"] == 280
    assert home["recent_card_min_height"] == 112
    assert home["recent_card_max_count"] == 3
    assert home["active_character_summary_width"] == 320
    assert home["active_character_summary_height"] == 220


def test_chat_work_geometry_frozen(tokens: DesignTokens) -> None:
    chat_work = tokens.component["dashboard"]["chat_work"]
    assert chat_work["page_content_max_width"] == 920
    assert chat_work["conversation_column_width"] == 720
    assert chat_work["bottom_clearance"] == 24
    assert chat_work["activity_row_min_height"] == 36
    assert chat_work["optional_context_pane_width"] == 320
    assert chat_work["optional_context_pane_default"] == "closed"


def test_composer_geometry_frozen(tokens: DesignTokens) -> None:
    composer = tokens.component["dashboard"]["composer"]
    assert composer["max_width"] == 800
    assert composer["min_height"] == 104
    assert composer["max_multiline_height"] == 240
    assert composer["radius"] == 24
    assert composer["padding"] == 16
    assert tuple(composer["actions"]) == ("attach", "optional_tools", "send")


def test_attachment_geometry_frozen(tokens: DesignTokens) -> None:
    attachment = tokens.component["dashboard"]["attachment"]
    assert attachment["chip_height"] == 32
    assert attachment["chip_max_width"] == 220
    assert attachment["file_image_icon"] == 18
    assert attachment["remove_hit_target"] == 32
    assert attachment["image_preview_width"] == 72
    assert attachment["image_preview_height"] == 72
    assert attachment["attach_hit_target"] == 40
    assert attachment["failure_copy"] == "Upload failed · Retry"


def test_artifact_geometry_frozen(tokens: DesignTokens) -> None:
    artifact = tokens.component["dashboard"]["artifact"]
    assert artifact["card_max_width"] == 720
    assert artifact["card_radius"] == 16
    assert artifact["card_padding"] == 20
    assert tuple(artifact["actions"]) == ("preview", "open", "export_or_save")


def test_character_animation_geometry_frozen(tokens: DesignTokens) -> None:
    animation = tokens.component["dashboard"]["character_animation"]
    assert animation["page_content_max_width"] == 1120
    assert animation["preview_preferred_width"] == 640
    assert animation["preview_preferred_height"] == 480
    assert animation["preview_min_width"] == 560
    assert animation["preview_min_height"] == 360
    assert animation["character_card_width"] == 144
    assert animation["character_card_height"] == 176
    assert animation["animation_card_width"] == 168
    assert animation["animation_card_height"] == 104
    assert animation["grid_gap"] == 16
    assert tuple(animation["actions"]) == (
        "preview",
        "play",
        "trigger_on_desktop",
    )
    assert animation["inventory_source"] == "active_character_capability_manifest"


def test_frozen_state_map_present(tokens: DesignTokens) -> None:
    states = tokens.states
    assert set(states["home"]) == {
        "first_launch",
        "normal",
        "no_recent_work",
        "recent_work",
        "agent_idle",
        "agent_working",
        "character_unavailable",
    }
    assert set(states["navigation"]) == {
        "expanded",
        "collapsed",
        "normal",
        "hover",
        "active",
        "focus",
    }
    assert set(states["attachment"]) == {
        "local",
        "uploading",
        "uploaded",
        "failed",
        "unsupported",
        "too_large",
        "removed",
    }
    assert set(states["agent"]) == {
        "idle",
        "submitted",
        "thinking",
        "working",
        "waiting",
        "needs_attention",
        "completed",
        "error",
    }


def test_presentation_map_contract(tokens: DesignTokens) -> None:
    mapping = tokens.presentation_map
    assert mapping["conversation_compact"] == (
        "desktop_companion.conversation_capsule"
    )
    assert mapping["conversation_expanded"] == (
        "dashboard.chat_work.expanded_conversation_complexity"
    )
    assert mapping["workspace"] == "dashboard.chat_work.work_mode"
    assert mapping["workspace_is_top_level_shell"] is False


def _flatten(theme_colors: object) -> frozenset[str]:
    return frozenset(field.name for field in fields(type(theme_colors)))


# Structural parity: every semantic group exposes the SAME attribute set in
# light and dark, so a component written against one theme never breaks the
# other.
def test_color_group_attributes_are_identical(tokens: DesignTokens) -> None:
    light = tokens.theme(ThemeVariant.LIGHT)
    dark = tokens.theme(ThemeVariant.DARK)
    for name in ("surface", "text", "border", "accent", "state"):
        assert _flatten(getattr(light, name)) == _flatten(
            getattr(dark, name)
        )
