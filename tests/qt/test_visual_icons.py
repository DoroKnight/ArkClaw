"""Slice 7G - frozen 1.75 px stroke vector icon system (Stage 10 visual polish).

Authority: docs/design/07-visual-design-freeze-v1.md "Icons" and
visual-freeze-v1.tokens.json icon map (stroke 1.75, navigation/action 20,
small 16, file/image 18, Thinking glyph 20, default hit target 40) plus the
Light/Dark semantic color contract in theme.icon / theme.accent.default /
theme.state.*.

Contracts proven here:
- the pen width is exactly the frozen 1.75 at the 20 px design size and
  scales linearly (1.4 at 16 px);
- every frozen inventory icon and every activity mark renders a non-empty
  pixmap at the correct logical size;
- icon pixmaps honor device pixel ratio (logical vs physical size);
- the three primary pages map to exactly three navigation icons;
- neutral icon and selected-accent colors come from the frozen theme tokens
  for both Light and Dark;
- navigation rows re-render their icon in accent when selected and switch
  colors on theme change;
- the Settings and Attach buttons render vector icons (no placeholder
  glyphs) and re-render on theme change;
- activity rows render semantic vector marks (icon + text, never color-only)
  using the frozen state colors.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from arkclaw.presentation.dashboard_presentation import (
    ActivityItem,
    ActivityState,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.dashboard.dashboard_window import DashboardWindow
from arkclaw.presentation.qt.dashboard.pages._widgets import ActivityRow
from arkclaw.presentation.qt.dashboard.pages.chat_work_page import ChatWorkPage
from arkclaw.presentation.qt.theme.design_tokens import (
    ThemeVariant,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.icons import (
    _INVENTORY_KINDS,
    IconKind,
    accent_color_for_theme,
    draw_icon,
    icon_color_for_theme,
    icon_kind_for_page,
    icon_pixmap,
    stroke_for_size,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme


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


def _contains_color(pixmap: QPixmap, hex_color: str) -> bool:
    target = QColor(hex_color)
    image = pixmap.toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y) == target:
                return True
    return False


# -- render contract ---------------------------------------------------------


def test_stroke_width_is_frozen_175_at_20px(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    assert stroke_for_size(20, tokens) == pytest.approx(1.75)
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_icon(
        painter,
        IconKind.HOME,
        QRectF(0.0, 0.0, 20.0, 20.0),
        "#000000",
    )
    pen_width = painter.pen().widthF()
    painter.end()
    assert pen_width == pytest.approx(tokens.icon["stroke"])


def test_stroke_scales_with_size(qt_application: QApplication, tokens) -> None:
    del qt_application
    assert stroke_for_size(16, tokens) == pytest.approx(1.4)
    assert stroke_for_size(18, tokens) == pytest.approx(1.575)
    assert stroke_for_size(20, tokens) == pytest.approx(1.75)


def test_every_icon_kind_renders_nonempty_at_frozen_sizes(
    qt_application: QApplication,
) -> None:
    del qt_application
    for kind in IconKind:
        for size in (16, 18, 20):
            pixmap = icon_pixmap(kind, size, "#000000")
            assert pixmap.width() == size
            assert pixmap.height() == size
            assert pixmap.devicePixelRatio() == pytest.approx(1.0)
            image = pixmap.toImage()
            non_empty = any(
                image.pixelColor(x, y).alpha() > 0
                for y in range(image.height())
                for x in range(image.width())
            )
            assert non_empty, f"{kind.value} rendered empty at {size}px"


def test_icon_pixmap_honors_device_pixel_ratio(
    qt_application: QApplication,
) -> None:
    del qt_application
    pixmap = icon_pixmap(IconKind.SEND, 20, "#000000", dpr=2.0)
    assert pixmap.width() == 40
    assert pixmap.height() == 40
    assert pixmap.devicePixelRatio() == pytest.approx(2.0)


def test_inventory_is_exactly_frozen_set() -> None:
    expected = {
        "home",
        "chat_work",
        "character_animation",
        "settings",
        "attach",
        "folder",
        "artifact",
        "open",
        "export",
        "retry",
        "send",
    }
    assert {kind.value for kind in _INVENTORY_KINDS} == expected


def test_page_icon_mapping_covers_exactly_primary_navigation() -> None:
    assert icon_kind_for_page(DashboardPage.HOME) is IconKind.HOME
    assert icon_kind_for_page(DashboardPage.CHAT_WORK) is IconKind.CHAT_WORK
    assert (
        icon_kind_for_page(DashboardPage.CHARACTER_ANIMATION)
        is IconKind.CHARACTER_ANIMATION
    )
    mapped = {icon_kind_for_page(page) for page in DashboardPage}
    assert len(mapped) == len(set(DashboardPage))


# -- theme color contract ----------------------------------------------------


def test_neutral_and_accent_icon_colors_follow_theme_tokens(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    light = tokens.theme(ThemeVariant.LIGHT)
    dark = tokens.theme(ThemeVariant.DARK)
    assert icon_color_for_theme(tokens, QtTheme.LIGHT) == light.icon
    assert icon_color_for_theme(tokens, QtTheme.DARK) == dark.icon
    assert light.icon != dark.icon
    assert accent_color_for_theme(tokens, QtTheme.LIGHT) == light.accent.default
    assert accent_color_for_theme(tokens, QtTheme.DARK) == dark.accent.default
    assert light.accent.default != dark.accent.default


# -- widget integration ------------------------------------------------------


def test_nav_icon_kind_and_selected_accent(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow(tokens)
    navigation = window.navigation
    home_row = navigation.page_button(DashboardPage.HOME)
    chat_row = navigation.page_button(DashboardPage.CHAT_WORK)
    assert home_row.icon_kind() is IconKind.HOME
    assert chat_row.icon_kind() is IconKind.CHAT_WORK
    # HOME is selected at startup, so it renders accent; CHAT/WORK is neutral.
    assert _contains_color(
        home_row.icon_pixmap(), accent_color_for_theme(tokens, QtTheme.LIGHT)
    )
    assert _contains_color(
        chat_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.LIGHT)
    )
    navigation.select_page(DashboardPage.CHAT_WORK)
    assert _contains_color(
        chat_row.icon_pixmap(), accent_color_for_theme(tokens, QtTheme.LIGHT)
    )
    assert not _contains_color(
        chat_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.LIGHT)
    )
    assert _contains_color(
        home_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.LIGHT)
    )
    window.dispose()
    del window


def test_theme_switch_rerenders_nav_icons(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow(tokens)
    home_row = window.navigation.page_button(DashboardPage.HOME)
    chat_row = window.navigation.page_button(DashboardPage.CHAT_WORK)
    # HOME selected at startup: accent under Light.
    assert _contains_color(
        home_row.icon_pixmap(), accent_color_for_theme(tokens, QtTheme.LIGHT)
    )
    assert _contains_color(
        chat_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.LIGHT)
    )
    window.set_theme(QtTheme.DARK)
    # Selected accent and neutral icons both re-render for the Dark palette.
    assert _contains_color(
        home_row.icon_pixmap(), accent_color_for_theme(tokens, QtTheme.DARK)
    )
    assert _contains_color(
        chat_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.DARK)
    )
    assert not _contains_color(
        chat_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.LIGHT)
    )
    window.navigation.select_page(DashboardPage.CHAT_WORK)
    assert _contains_color(
        chat_row.icon_pixmap(), accent_color_for_theme(tokens, QtTheme.DARK)
    )
    assert _contains_color(
        home_row.icon_pixmap(), icon_color_for_theme(tokens, QtTheme.DARK)
    )
    window.dispose()
    del window


def test_settings_button_renders_vector_icon_and_hit_target(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    window = DashboardWindow(tokens)
    button = window.settings_button()
    assert button.text() == ""
    assert button.icon().isNull() is False
    assert button.width() == tokens.icon["default_hit_target"] == 40
    assert button.height() == 40
    assert button.accessibleName() == "Settings"
    assert _contains_color(
        button.icon().pixmap(20, 20),
        icon_color_for_theme(tokens, QtTheme.LIGHT),
    )
    window.set_theme(QtTheme.DARK)
    assert _contains_color(
        button.icon().pixmap(20, 20),
        icon_color_for_theme(tokens, QtTheme.DARK),
    )
    window.dispose()
    del window


def test_attach_button_renders_vector_icon_and_rerenders_on_theme(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    page = ChatWorkPage(tokens)
    button = page.attach_button()
    assert button.text() == ""
    assert button.icon().isNull() is False
    assert button.accessibleName() == "Attach file or image"
    assert (
        button.width()
        == tokens.component["dashboard"]["attachment"]["attach_hit_target"]
        == 40
    )
    assert _contains_color(
        button.icon().pixmap(20, 20),
        icon_color_for_theme(tokens, QtTheme.LIGHT),
    )
    page.set_theme(QtTheme.DARK)
    assert _contains_color(
        button.icon().pixmap(20, 20),
        icon_color_for_theme(tokens, QtTheme.DARK),
    )
    page.dispose()


def test_activity_row_renders_semantic_icon_and_state_color(
    qt_application: QApplication, tokens
) -> None:
    del qt_application
    light = tokens.theme(ThemeVariant.LIGHT)
    cases = (
        (ActivityState.COMPLETED, IconKind.ACTIVITY_COMPLETED, light.state.success),
        (ActivityState.CURRENT, IconKind.ACTIVITY_CURRENT, light.accent.default),
        (ActivityState.FUTURE, IconKind.ACTIVITY_FUTURE, light.text.tertiary),
        (ActivityState.ERROR, IconKind.ACTIVITY_ERROR, light.state.danger),
        (ActivityState.WARNING, IconKind.ACTIVITY_WARNING, light.state.warning),
    )
    for state, kind, expected_color in cases:
        row = ActivityRow(tokens, ActivityItem("Item", state), None)
        assert row.icon_kind() is kind
        assert row.text()
        pixmap = row.icon_pixmap()
        assert _contains_color(pixmap, expected_color)
        # Theme switch re-renders the same semantic mark with the Dark palette.
        row.set_theme(QtTheme.DARK)
        assert not _contains_color(row.icon_pixmap(), expected_color)
        row.deleteLater()
