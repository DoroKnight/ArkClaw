"""Qt theme application over the frozen Visual Freeze v1 tokens (Slice 7A).

The stylesheet is generated exclusively from
:class:`~arkclaw.presentation.qt.theme.design_tokens.DesignTokens` so Qt
components never scatter raw hex / dimension literals.  Light and Dark use
the identical semantic contract; :focus rules are explicit and reference the
frozen focus color so the stylesheet can never swallow keyboard focus.

Object-name conventions consumed by dashboard components (7B+):
    appRoot, topShell, navigationPane, navRow, pageArea, surfaceCard,
    composerCard, homeAsk, textPrimary, textSecondary, textTertiary,
    textCaption, pageTitle, sectionTitle, agentStatus, primaryButton,
    secondaryButton, ghostButton, attachChip, attachChipFailed, tooltip.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from enum import StrEnum

from PySide6.QtWidgets import QWidget

from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    ThemeColors,
    ThemeVariant,
    load_design_tokens,
)


class QtTheme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


def build_theme_stylesheet(
    theme: QtTheme,
    tokens: DesignTokens | None = None,
) -> str:
    source = tokens if tokens is not None else load_design_tokens()
    colors = source.theme(ThemeVariant(theme.value))
    navigation = source.component["dashboard"]["navigation"]
    return _compose(
        colors=colors,
        tokens=source,
        nav_row_height=int(navigation["row_height"]),
        nav_leading_inset=int(navigation["leading_inset"]),
        nav_icon_size=int(navigation["icon_size"]),
    )


def apply_theme(
    widget: QWidget,
    theme: QtTheme,
    tokens: DesignTokens | None = None,
) -> None:
    """Apply the theme stylesheet to a widget subtree (idempotent)."""
    widget.setStyleSheet(build_theme_stylesheet(theme, tokens))


def build_menu_stylesheet(
    theme: QtTheme,
    tokens: DesignTokens | None = None,
) -> str:
    """Generate one compact native-menu stylesheet from the frozen tokens.

    Shared by the system tray and pet context menus (Slice 6B).  The menu
    keeps the frozen dark-surface language and switches only the accent to
    the token accent so the new Visual Freeze v1 identity is visible without
    a visual break on the desktop.
    """
    source = tokens if tokens is not None else load_design_tokens()
    colors = source.theme(ThemeVariant(theme.value))
    font_family = ", ".join(f'"{family}"' for family in source.font_family)
    rules: list[str] = []
    rule = _add_rule(rules)
    selected_text = (
        "#FFFFFF"
        if theme is QtTheme.LIGHT
        else colors.surface.background
    )
    rule(
        "QMenu",
        {
            "background": colors.surface.surface,
            "color": colors.text.primary,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{source.radius['button']}px",
            "padding": "4px",
            "font-family": font_family,
            "font-size": "12px",
        },
    )
    rule(
        "QMenu::item",
        {
            "min-width": "180px",
            "min-height": "24px",
            "padding": "3px 20px 3px 10px",
            "margin": "1px 0",
            "border-radius": f"{source.radius['navigation_row'] // 2}px",
            "color": colors.text.primary,
            "font-size": "12px",
        },
    )
    rule(
        "QMenu::item:selected",
        {
            "background": colors.accent.default,
            "color": selected_text,
        },
    )
    rule(
        "QMenu::item:disabled",
        {"color": colors.text.disabled},
    )
    rule(
        "QMenu::separator",
        {
            "height": "1px",
            "background": colors.border.divider,
            "margin": "4px 6px",
        },
    )
    rule(
        "QMenu::indicator",
        {
            "width": "8px",
            "height": "8px",
            "margin-left": "6px",
            "background": "transparent",
        },
    )
    rule(
        "QMenu::indicator:checked",
        {
            "background": colors.accent.default,
            "border": "none",
            "border-radius": "4px",
            "width": "8px",
            "height": "8px",
        },
    )
    rule(
        "QMenu::indicator:unchecked",
        {
            "background": "transparent",
            "border": "none",
            "width": "8px",
            "height": "8px",
        },
    )
    rule(
        "QMenu::right-arrow",
        {
            "width": "6px",
            "height": "10px",
            "margin-right": "6px",
        },
    )
    return "\n".join(rules)


def motion_enabled() -> bool:
    """Whether UI motion is active (Slice 7G reduced-motion gate).

    Defaults to enabled to match the V1 "Follow Windows" default; set
    ``ARKCLAW_REDUCED_MOTION`` (1/true/yes/on) to opt out.  Motion is always
    non-semantic, cancelable, and state-driven per the visual freeze.
    """
    value = os.environ.get("ARKCLAW_REDUCED_MOTION", "").strip().lower()
    """Whether UI motion is active (Slice 7G reduced-motion gate).

    Defaults to enabled to match the V1 "Follow Windows" default; set
    ``ARKCLAW_REDUCED_MOTION`` (1/true/yes/on) to opt out.  Motion is always
    non-semantic, cancelable, and state-driven per the visual freeze.
    """
    value = os.environ.get("ARKCLAW_REDUCED_MOTION", "").strip().lower()
    return value not in ("1", "true", "yes", "on")


def _compose(
    *,
    colors: ThemeColors,
    tokens: DesignTokens,
    nav_row_height: int,
    nav_leading_inset: int,
    nav_icon_size: int,
) -> str:
    radius = tokens.radius
    navigation = tokens.typography["navigation"]
    body = tokens.typography["body"]
    caption = tokens.typography["caption"]
    section = tokens.typography["section"]
    page_title = tokens.typography["page_title"]
    agent_status = tokens.typography["agent_status"]
    composer = tokens.typography["composer"]
    home = tokens.component["dashboard"]["home"]
    ask_radius = int(home["ask_radius"])
    display = tokens.typography["display"]
    spacing = tokens.spacing
    font_family = ", ".join(f'"{family}"' for family in tokens.font_family)

    rules: list[str] = []
    rule = _add_rule(rules)

    rule(
        "QMainWindow, QWidget#appRoot, QWidget#dashboardWindow, "
        "QStackedWidget#pageArea, QWidget#homePage, "
        "QWidget#homeScrollContent, QScrollArea#homeScrollArea",
        {
            "background": colors.surface.background,
            "color": colors.text.primary,
            "font-family": font_family,
            "font-size": f"{body[0]}px",
        },
    )
    rule(
        "QWidget#topShell",
        {
            "background": colors.surface.surface,
            "border-bottom": f"1px solid {colors.border.divider}",
        },
    )
    rule(
        "QLabel#topShellTitle",
        {
            "color": colors.text.primary,
            "font-size": f"{navigation[0]}px",
            "font-weight": "600",
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QFrame#navIndicator",
        {
            "background": colors.accent.default,
            "border": "none",
            "border-radius": "1px",
        },
    )
    rule(
        "QPushButton#navToggle",
        {
            "background": "transparent",
            "border": "1px solid transparent",
            "border-radius": f"{radius['button']}px",
            "color": colors.text.secondary,
            "font-size": f"{navigation[0]}px",
        },
    )
    rule(
        "QPushButton#navToggle:hover",
        {
            "background": colors.surface.surface_hover,
            "color": colors.text.primary,
        },
    )
    rule(
        "QPushButton#navToggle:focus",
        {
            "border": f"2px solid {colors.focus}",
        },
    )
    rule(
        "QWidget#navigationPane",
        {
            "background": colors.surface.surface_nav,
            "border-right": f"1px solid {colors.border.divider}",
        },
    )
    rule(
        "QWidget#navRow",
        {
            "background": "transparent",
            "border": "2px solid transparent",
            "border-radius": f"{radius['navigation_row']}px",
            "min-height": f"{nav_row_height - 4}px",
            "padding": "0px",
            "color": colors.text.secondary,
            "text-align": "left",
            "font-size": f"{navigation[0]}px",
            "font-weight": str(navigation[2]),
        },
    )
    rule(
        "QWidget#navRow QLabel",
        {
            "color": colors.text.secondary,
            "font-size": f"{navigation[0]}px",
            "font-weight": str(navigation[2]),
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QWidget#navRow:hover",
        {
            "background": colors.surface.surface_hover,
            "color": colors.text.primary,
        },
    )
    rule(
        "QWidget#navRow:hover QLabel",
        {
            "color": colors.text.primary,
        },
    )
    rule(
        "QWidget#navRow:pressed",
        {
            "background": colors.surface.surface_active,
        },
    )
    rule(
        "QWidget#navRow:focus",
        {
            "border": f"2px solid {colors.focus}",
        },
    )
    rule(
        'QWidget#navRow[selected="true"]',
        {
            "background": colors.surface.surface_selected,
            "color": colors.text.primary,
        },
    )
    rule(
        'QWidget#navRow[selected="true"] QLabel',
        {
            "color": colors.text.primary,
            "font-weight": "600",
        },
    )
    rule(
        'QWidget#navRow[selected="true"]:hover',
        {
            "background": colors.surface.surface_selected,
        },
    )
    rule(
        "QWidget#navRow:disabled",
        {
            "color": colors.text.disabled,
        },
    )
    rule(
        "QWidget#navRow:disabled QLabel",
        {
            "color": colors.text.disabled,
        },
    )
    rule(
        "QWidget#pageArea",
        {
            "background": colors.surface.background,
        },
    )
    rule(
        "QWidget#surfaceCard",
        {
            "background": colors.surface.surface_card,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['card']}px",
        },
    )
    rule(
        "QWidget#composerCard",
        {
            "background": colors.surface.surface,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['composer']}px",
        },
    )
    rule(
        "QFrame#previewFrame, QFrame#stageFrame, QWidget#stageBackgroundWidget",
        {
            "background": colors.surface.surface_card,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['card']}px",
        },
    )
    rule(
        "QScrollArea#animationScrollArea, QScrollArea#animationScrollArea > QWidget > QWidget",
        {
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QWidget#characterCard, QWidget#animationCard",
        {
            "background": colors.surface.surface_card,
            "border": f"1px solid {colors.border.default}",
            "border-radius": "8px",
        },
    )
    rule(
        "QWidget#characterCard:hover, QWidget#animationCard:hover",
        {"background": colors.surface.surface_hover},
    )
    rule(
        "QWidget#characterCard:focus, QWidget#animationCard:focus",
        {"border": f"2px solid {colors.focus}"},
    )
    rule(
        'QWidget#characterCard[selected="true"], '
        'QWidget#animationCard[selected="true"]',
        {
            "border": f"1px solid {colors.accent.default}",
            "background": colors.accent.soft,
        },
    )
    rule(
        'QWidget#animationCard[selected="true"] QLabel#textPrimary',
        {
            "color": colors.accent.default,
            "font-weight": "700",
        },
    )
    rule(
        'QWidget#animationCard[selected="true"] QLabel#animIndicator',
        {
            "color": colors.accent.default,
            "font-weight": "700",
        },
    )
    rule(
        'QWidget#animationCard[selected="true"] QLabel#animSubtitle',
        {
            "color": colors.text.secondary,
        },
    )
    rule(
        "QFrame#animIconBadge",
        {
            "background": colors.surface.surface_hover,
            "border": f"1px solid {colors.border.default}",
            "border-radius": "6px",
        },
    )
    rule(
        'QWidget#animationCard[selected="true"] QFrame#animIconBadge',
        {
            "background": colors.surface.surface_card,
            "border": f"1px solid {colors.accent.default}",
        },
    )
    rule(
        "QLabel#animSubtitle",
        {
            "color": colors.text.secondary,
            "font-size": "11px",
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QLabel#animIndicator",
        {
            "color": colors.text.tertiary,
            "font-size": "11px",
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QLabel#animIconLabel",
        {
            "font-size": "15px",
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QLabel#homeGreeting",
        {
            "color": colors.text.primary,
            "font-size": f"{display[0]}px",
            "font-weight": str(display[2]),
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QLabel#homeIntro",
        {
            "color": colors.text.secondary,
            "font-size": f"{body[0]}px",
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QFrame#homeTaskState",
        {
            "background": colors.surface.surface_card,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['card']}px",
        },
    )
    rule(
        "QPushButton#homeAsk",
        {
            "background": colors.surface.surface_input,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{ask_radius}px",
            "color": colors.text.secondary,
            "text-align": "left",
            "padding-left": f"{int(spacing['composer_padding'])}px",
            "font-size": f"{composer[0]}px",
        },
    )
    rule(
        "QPushButton#homeAsk:hover",
        {
            "background": colors.surface.surface_hover,
            "border": f"1px solid {colors.accent.default}",
        },
    )
    rule(
        "QPushButton#homeAsk:focus",
        {
            "border": f"2px solid {colors.focus}",
        },
    )
    for name, type_spec in (
        ("pageTitle", page_title),
        ("sectionTitle", section),
        ("textPrimary", body),
        ("textSecondary", body),
        ("textTertiary", body),
        ("textCaption", caption),
        ("agentStatus", agent_status),
    ):
        rule(
            f"QLabel#{name}",
            {
                "background": "transparent",
                "border": "none",
                "color": _text_color(colors, name),
                "font-size": f"{type_spec[0]}px",
                "font-weight": str(type_spec[2]),
            },
        )
    rule(
        "QLabel#pageTitle",
        {
            "font-size": f"{page_title[0]}px",
            "font-weight": str(page_title[2]),
        },
    )
    rule(
        "QPushButton#primaryButton",
        {
            "background": colors.accent.default,
            "color": "#FFFFFF",
            "border": "none",
            "border-radius": f"{radius['button']}px",
            "min-height": "36px",
            "padding": "0 16px",
            "font-size": f"{body[0]}px",
            "font-weight": str(body[2]),
        },
    )
    rule(
        "QPushButton#primaryButton:hover",
        {"background": colors.accent.hover},
    )
    rule(
        "QPushButton#primaryButton:focus",
        {"border": f"2px solid {colors.focus}"},
    )
    rule(
        "QPushButton#primaryButton:disabled",
        {"background": colors.surface.surface_hover, "color": colors.text.disabled},
    )
    rule(
        "QPushButton#secondaryButton",
        {
            "background": colors.surface.surface,
            "color": colors.text.primary,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['button']}px",
            "min-height": "36px",
            "padding": "0 16px",
            "font-size": f"{body[0]}px",
        },
    )
    rule(
        "QPushButton#secondaryButton:hover",
        {"background": colors.surface.surface_hover},
    )
    rule(
        "QPushButton#secondaryButton:focus",
        {"border": f"2px solid {colors.focus}"},
    )
    rule(
        "QPushButton#secondaryButton:disabled",
        {"color": colors.text.disabled},
    )
    rule(
        "QTextEdit#composerInput",
        {
            "background": "transparent",
            "border": "none",
            "color": colors.text.primary,
            "selection-background-color": colors.accent.soft,
            "font-size": f"{composer[0]}px",
            "font-weight": str(composer[2]),
        },
    )
    rule(
        "QTextEdit#composerInput:focus",
        {"border": "none", "outline": "none"},
    )
    rule(
        "QPushButton#ghostButton",
        {
            "background": "transparent",
            "border": "1px solid transparent",
            "color": colors.text.secondary,
            "font-size": f"{caption[0]}px",
        },
    )
    rule(
        "QPushButton#ghostButton:hover",
        {"color": colors.text.primary},
    )
    rule(
        "QPushButton#ghostButton:focus",
        {"border": f"1px solid {colors.focus}"},
    )
    rule(
        "QWidget#attachChip",
        {
            "background": colors.surface.surface_subtle,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['pill']}px",
            "color": colors.text.primary,
        },
    )
    rule(
        "QWidget#attachChipFailed",
        {
            "background": colors.state.danger_soft,
            "border": f"1px solid {colors.state.danger}",
            "color": colors.state.danger,
        },
    )
    rule(
        "QToolTip",
        {
            "background": colors.surface.surface,
            "color": colors.text.primary,
            "border": f"1px solid {colors.border.default}",
            "padding": "6px",
        },
    )
    rule(
        "QDialog#settingsDialog",
        {
            "background": colors.surface.surface,
            "color": colors.text.primary,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['card']}px",
        },
    )
    rule(
        "QLabel#dialogTitle",
        {
            "color": colors.text.primary,
            "font-size": f"{section[0]}px",
            "font-weight": str(section[2]),
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QLabel#sectionHeading",
        {
            "color": colors.text.primary,
            "font-size": f"{body[0]}px",
            "font-weight": "600",
            "background": "transparent",
            "border": "none",
        },
    )
    rule(
        "QCheckBox#autostartCheckbox",
        {
            "color": colors.text.primary,
            "font-size": f"{body[0]}px",
            "spacing": "8px",
        },
    )
    rule(
        "QComboBox#themeCombo, QComboBox#providerCombo",
        {
            "background": colors.surface.surface_input,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['button']}px",
            "padding": "4px 12px",
            "color": colors.text.primary,
            "font-size": f"{body[0]}px",
            "min-width": "100px",
        },
    )
    rule(
        "QLineEdit#baseUrlEdit, QLineEdit#modelEdit, QLineEdit#apiKeyEdit",
        {
            "background": colors.surface.surface_input,
            "border": f"1px solid {colors.border.default}",
            "border-radius": f"{radius['button']}px",
            "padding": "4px 10px",
            "color": colors.text.primary,
            "font-size": f"{body[0]}px",
        },
    )
    rule(
        "QFrame#divider",
        {
            "background": colors.border.divider,
            "border": "none",
            "max-height": "1px",
        },
    )
    palette = tokens.component["desktop_companion"]["action_palette"]
    palette_row_height = int(palette["row_height"])
    palette_row_h_padding = int(palette["row_horizontal_padding"])
    palette_border_width = int(palette["border_width"])
    palette_focus_width = int(palette["focus_width"])
    rule(
        "QWidget#ActionPaletteHost, QWidget#ActionPaletteSubHost",
        {
            "background": colors.surface.surface,
            "color": colors.text.primary,
            "border": (
                f"{palette_border_width}px solid {colors.border.default}"
            ),
            "border-radius": f"{radius['palette']}px",
            "font-family": font_family,
            "font-size": f"{body[0]}px",
        },
    )
    rule(
        "QWidget#ActionPaletteHost QPushButton, QWidget#ActionPaletteSubHost QPushButton",
        {
            "background": "transparent",
            "border": "1px solid transparent",
            "border-radius": f"{radius['button']}px",
            "min-height": f"{palette_row_height - 4}px",
            "padding-left": f"{palette_row_h_padding}px",
            "padding-right": f"{palette_row_h_padding}px",
            "text-align": "left",
            "color": colors.text.primary,
            "font-size": f"{body[0]}px",
        },
    )
    rule(
        (
            "QWidget#ActionPaletteHost QPushButton:hover,\n"
            "QWidget#ActionPaletteSubHost QPushButton:hover"
        ),
        {
            "background": colors.surface.surface_hover,
            "color": colors.text.primary,
        },
    )
    rule(
        (
            "QWidget#ActionPaletteHost QPushButton:pressed,\n"
            "QWidget#ActionPaletteSubHost QPushButton:pressed"
        ),
        {"background": colors.surface.surface_active},
    )
    rule(
        (
            "QWidget#ActionPaletteHost QPushButton:focus,\n"
            "QWidget#ActionPaletteSubHost QPushButton:focus"
        ),
        {"border": f"{palette_focus_width}px solid {colors.focus}"},
    )
    rule(
        (
            "QWidget#ActionPaletteHost QPushButton:disabled,\n"
            "QWidget#ActionPaletteSubHost QPushButton:disabled"
        ),
        {"color": colors.text.disabled},
    )
    return "\n".join(rules)


def _text_color(colors: ThemeColors, name: str) -> str:
    if name == "pageTitle" or name == "sectionTitle" or name == "textPrimary":
        return colors.text.primary
    if name == "textSecondary":
        return colors.text.secondary
    if name == "textTertiary":
        return colors.text.tertiary
    if name == "textCaption":
        return colors.text.tertiary
    if name == "agentStatus":
        return colors.text.secondary
    return colors.text.primary


def _add_rule(
    rules: list[str],
) -> Callable[[str, dict[str, str]], None]:
    def rule(selector: str, declarations: dict[str, str]) -> None:
        body = ";\n    ".join(f"{key}: {value}" for key, value in declarations.items())
        rules.append(f"{selector} {{\n    {body};\n}}")

    return rule
