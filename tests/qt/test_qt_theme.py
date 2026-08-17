"""Slice 7A - Qt theme application over the frozen token source.

Authority: docs/design/visual-freeze-v1.tokens.json and
docs/design/07-visual-design-freeze-v1.md sections 12/13/17.  The QSS is
generated exclusively from semantic tokens; components must never scatter raw
hex/dimension literals, and focus must never be swallowed by the stylesheet.

Contracts proven here:
- applying a theme sets a QSS generated from tokens (no raw literals);
- light and dark produce distinct stylesheets over the SAME contract;
- switching themes preserves widget children and widget-owned state;
- :focus selectors are explicit and reference the frozen focus color;
- text/icon contrast meets WCAG AA for primary/secondary text and 3:1 for
  tertiary/icon (non-text) on both themes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from arkclaw.presentation.qt.theme.design_tokens import (
    ThemeVariant,
    contrast_ratio,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import (
    QtTheme,
    apply_theme,
    build_theme_stylesheet,
)


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


def test_apply_theme_sets_token_generated_stylesheet(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    widget = QWidget()
    widget.setObjectName("appRoot")
    apply_theme(widget, QtTheme.LIGHT)
    stylesheet = widget.styleSheet()
    assert stylesheet
    dark_style = build_theme_stylesheet(QtTheme.DARK)
    assert "surface_nav" not in stylesheet  # QSS is generated, never literal
    assert stylesheet != dark_style
    widget.deleteLater()


def test_stylesheet_references_frozen_semantic_colors(tokens) -> None:
    stylesheet = build_theme_stylesheet(QtTheme.LIGHT)
    light = tokens.theme(ThemeVariant.LIGHT)
    assert light.surface.background.upper() in stylesheet.upper()
    assert light.text.primary.upper() in stylesheet.upper()
    assert light.focus.upper() in stylesheet.upper()


def test_focus_is_not_swallowed(tokens) -> None:
    stylesheet = build_theme_stylesheet(QtTheme.LIGHT)
    assert "navRow:focus" in stylesheet
    assert 'navRow[selected="true"]' in stylesheet
    for variant in (QtTheme.LIGHT, QtTheme.DARK):
        sheet = build_theme_stylesheet(variant)
        assert "border: 2px solid" in sheet or "border:2px solid" in sheet


def test_theme_switch_preserves_children_and_state(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    widget = QWidget()
    widget.setObjectName("appRoot")
    layout = QVBoxLayout(widget)
    label = QLabel("draft text")
    label.setObjectName("textPrimary")
    button = QPushButton("Send")
    button.setObjectName("navRow")
    layout.addWidget(label)
    layout.addWidget(button)
    apply_theme(widget, QtTheme.LIGHT)
    apply_theme(widget, QtTheme.DARK)
    assert widget.styleSheet() == build_theme_stylesheet(QtTheme.DARK)
    assert label.text() == "draft text"
    assert widget.findChild(QLabel, "textPrimary") is label
    assert widget.findChild(QPushButton, "navRow") is button
    widget.deleteLater()


def test_theme_apply_is_idempotent(qt_application: QApplication, tokens) -> None:
    del qt_application
    widget = QWidget()
    widget.setObjectName("appRoot")
    apply_theme(widget, QtTheme.LIGHT)
    first = widget.styleSheet()
    apply_theme(widget, QtTheme.LIGHT)
    assert widget.styleSheet() == first
    widget.deleteLater()


def test_motion_enabled_respects_reduced_motion_env() -> None:
    from arkclaw.presentation.qt.theme.qt_theme import motion_enabled

    previous = os.environ.get("ARKCLAW_REDUCED_MOTION")
    try:
        os.environ.pop("ARKCLAW_REDUCED_MOTION", None)
        assert motion_enabled() is True
        os.environ["ARKCLAW_REDUCED_MOTION"] = "1"
        assert motion_enabled() is False
        os.environ["ARKCLAW_REDUCED_MOTION"] = "true"
        assert motion_enabled() is False
    finally:
        if previous is None:
            os.environ.pop("ARKCLAW_REDUCED_MOTION", None)
        else:
            os.environ["ARKCLAW_REDUCED_MOTION"] = previous


def test_light_text_contrast_aa(tokens) -> None:
    theme = tokens.theme(
        ThemeVariant.LIGHT
    )
    assert contrast_ratio(theme.text.primary, theme.surface.surface) >= 4.5
    assert contrast_ratio(theme.text.secondary, theme.surface.surface) >= 4.5
    assert contrast_ratio(theme.text.tertiary, theme.surface.surface) >= 3.0
    assert contrast_ratio(theme.icon, theme.surface.surface) >= 3.0


def test_dark_text_contrast_aa(tokens) -> None:
    theme = tokens.theme(
        ThemeVariant.DARK
    )
    assert contrast_ratio(theme.text.primary, theme.surface.surface) >= 4.5
    assert contrast_ratio(theme.text.secondary, theme.surface.surface) >= 4.5
    assert contrast_ratio(theme.text.tertiary, theme.surface.surface) >= 3.0
    assert contrast_ratio(theme.icon, theme.surface.surface) >= 3.0


def test_navigation_row_text_contrast_on_nav_surface(tokens) -> None:
    for variant in ("light", "dark"):
        theme = tokens.theme(
            ThemeVariant(variant)
        )
        assert (
            contrast_ratio(theme.text.secondary, theme.surface.surface_nav)
            >= 3.0
        )
        assert (
            contrast_ratio(theme.text.primary, theme.surface.surface_nav)
            >= 4.5
        )
