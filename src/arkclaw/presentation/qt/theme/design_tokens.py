"""Visual Freeze v1 design tokens - single machine-readable source.

Authority: docs/design/visual-freeze-v1.tokens.json (schema_version 2) and
docs/design/07-visual-design-freeze-v1.md sections 5/17.  This module is
intentionally Qt-free: unit tests and Qt components both consume the same
semantic accessors, and no component may scatter raw color / dimension
literals.

Semantic color contract exposed per theme:
    theme.surface.*    background, surface, surface_card, surface_nav,
                       surface_subtle, surface_input, surface_hover,
                       surface_active, surface_selected
    theme.text.*       primary, secondary, tertiary, disabled
    theme.border.*     default, divider
    theme.focus.*      (single) focus
    theme.accent.*     default, hover, soft
    theme.state.*      danger, danger_soft, warning, success
Light and Dark share the exact same semantic contract (values differ only).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

_REPO_MARKERS = ("pyproject.toml", ".git")
_TOKEN_RELATIVE_PATH = Path("docs") / "design" / "visual-freeze-v1.tokens.json"
_DEFAULT_ENV = "ARKCLAW_VISUAL_TOKENS_JSON"


class ThemeVariant(StrEnum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True, slots=True)
class SurfaceColors:
    background: str
    surface: str
    surface_card: str
    surface_nav: str
    surface_subtle: str
    surface_input: str
    surface_hover: str
    surface_active: str
    surface_selected: str


@dataclass(frozen=True, slots=True)
class TextColors:
    primary: str
    secondary: str
    tertiary: str
    disabled: str


@dataclass(frozen=True, slots=True)
class BorderColors:
    default: str
    divider: str


@dataclass(frozen=True, slots=True)
class AccentColors:
    default: str
    hover: str
    soft: str


@dataclass(frozen=True, slots=True)
class StateColors:
    danger: str
    danger_soft: str
    warning: str
    success: str


@dataclass(frozen=True, slots=True)
class ShadowSpec:
    x: int
    y: int
    blur: int
    color: str


@dataclass(frozen=True, slots=True)
class ThemeColors:
    surface: SurfaceColors
    text: TextColors
    border: BorderColors
    focus: str
    accent: AccentColors
    state: StateColors
    icon: str
    shadows: dict[str, tuple[ShadowSpec, ...]]


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """Parsed Visual Freeze v1 tokens.

    ``typography`` values are ``(size, line_height, weight)`` triples;
    ``spacing`` / ``radius`` / ``icon`` are semantic name -> value maps;
    ``component`` and ``motion`` preserve the frozen JSON structure.
    """

    schema_version: int
    name: str
    status: str
    units: str
    product_term: str
    reference_character: str
    character_model: dict[str, Any]
    primary_navigation: tuple[str, ...]
    font_family: tuple[str, ...]
    themes: dict[ThemeVariant, ThemeColors]
    typography: dict[str, tuple[int, int, int]]
    spacing: dict[str, int]
    spacing_scale: tuple[int, ...]
    radius: dict[str, int]
    icon: dict[str, int | float]
    motion: dict[str, Any]
    component: dict[str, Any]
    states: dict[str, list[str]]
    presentation_map: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path | None = None) -> DesignTokens:
        resolved = _resolve_token_path(path)
        with resolved.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return _build(payload)

    def theme(self, variant: ThemeVariant) -> ThemeColors:
        return self.themes[variant]

    def component_section(self, section: str) -> dict[str, Any]:
        value = self.component[section]
        assert isinstance(value, dict)
        return value


def load_design_tokens(path: str | Path | None = None) -> DesignTokens:
    """Return the cached frozen token object (idempotent, single source)."""
    key = str(path) if path is not None else "default"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    tokens = DesignTokens.load(path)
    _CACHE[key] = tokens
    return tokens


_CACHE: dict[str, DesignTokens] = {}


def _resolve_token_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    override = os.environ.get(_DEFAULT_ENV)
    if override:
        return Path(override)
    return _repo_root() / _TOKEN_RELATIVE_PATH


def _repo_root() -> Path:
    module = Path(__file__).resolve()
    for parent in module.parents:
        if any((parent / marker).exists() for marker in _REPO_MARKERS):
            return parent
    raise FileNotFoundError(
        "Cannot locate the ArkClaw repository root from the theme module"
    )


def _build(payload: dict[str, Any]) -> DesignTokens:
    themes: dict[ThemeVariant, ThemeColors] = {}
    for variant in ThemeVariant:
        raw = payload["themes"][variant.value]
        themes[variant] = _build_theme_colors(raw)

    typography = {
        name: (
            int(spec["size"]),
            int(spec["line_height"]),
            int(spec["weight"]),
        )
        for name, spec in payload["typography"].items()
    }
    spacing_raw = payload["spacing"]
    spacing = {
        name: int(value)
        for name, value in spacing_raw.items()
        if name != "scale"
    }
    return DesignTokens(
        schema_version=int(payload["schema_version"]),
        name=str(payload["name"]),
        status=str(payload["status"]),
        units=str(payload["units"]),
        product_term=str(payload["character_model"]["product_term"]),
        reference_character=str(
            payload["character_model"]["reference_character"]
        ),
        character_model=dict(payload["character_model"]),
        primary_navigation=tuple(
            payload["product_model"]["dashboard_primary_navigation"]
        ),
        font_family=tuple(payload["font_family"]),
        themes=themes,
        typography=typography,
        spacing=spacing,
        spacing_scale=tuple(int(v) for v in spacing_raw["scale"]),
        radius={name: int(value) for name, value in payload["radius"].items()},
        icon={name: value for name, value in payload["icon"].items()},
        motion=payload["motion"],
        component=payload["component"],
        states=payload["states"],
        presentation_map=payload["presentation_map"],
    )


def _build_theme_colors(raw: dict[str, Any]) -> ThemeColors:
    colors = raw["color"]
    return ThemeColors(
        surface=SurfaceColors(
            background=str(colors["background"]),
            surface=str(colors["surface"]),
            surface_card=str(colors["surface_card"]),
            surface_nav=str(colors["surface_nav"]),
            surface_subtle=str(colors["surface_subtle"]),
            surface_input=str(colors["surface_input"]),
            surface_hover=str(colors["surface_hover"]),
            surface_active=str(colors["surface_active"]),
            surface_selected=str(colors["surface_selected"]),
        ),
        text=TextColors(
            primary=str(colors["text_primary"]),
            secondary=str(colors["text_secondary"]),
            tertiary=str(colors["text_tertiary"]),
            disabled=str(colors["text_disabled"]),
        ),
        border=BorderColors(
            default=str(colors["border"]),
            divider=str(colors["divider"]),
        ),
        focus=str(colors["focus"]),
        accent=AccentColors(
            default=str(colors["accent"]),
            hover=str(colors["accent_hover"]),
            soft=str(colors["accent_soft"]),
        ),
        state=StateColors(
            danger=str(colors["danger"]),
            danger_soft=str(colors["danger_soft"]),
            warning=str(colors["warning"]),
            success=str(colors["success"]),
        ),
        icon=str(colors["icon"]),
        shadows={
            name: tuple(
                ShadowSpec(
                    x=int(layer["x"]),
                    y=int(layer["y"]),
                    blur=int(layer["blur"]),
                    color=str(layer["color"]),
                )
                for layer in layers
            )
            for name, layers in raw["shadow"].items()
        },
    )


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio between two #RRGGBB colors (Qt-free)."""
    lighter = max(_luminance(foreground), _luminance(background))
    darker = min(_luminance(foreground), _luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {hex_color!r}")
    channels = [int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
