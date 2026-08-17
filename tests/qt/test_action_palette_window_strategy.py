"""Slice 6A - Palette native window strategy seam (spike, harness only).

Authority: 08 15.1 (Slice 6A Tool-vs-Popup native spike), 07 23.
The window strategy is a spike-only seam: flags are applied once at
construction and are never restyled per render.  The frozen production
default remains Qt.Tool (07 23 "independent focusable top-level Tool"
candidate); Qt.Popup exists only so the 6A native harness can measure both
candidates.  No production cutover happens here (Slice 6B owns it).

These tests never call show() on a POPUP host: a Qt.Popup widget enters a
modal native loop on show, which is exactly the behaviour the 6A native
harness measures separately.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

from arkclaw.presentation.command_descriptor_adapter import (
    CommandDescriptor,
    CommandGroup,
    CommandId,
    CommandInvokeIntent,
)
from arkclaw.presentation.frontend_presentation import (
    ActionPaletteLayer,
    ForegroundOverlay,
    PresentationEffect,
    PresentationEffectKind,
)
from arkclaw.presentation.qt.ui.action_palette import (
    ActionPaletteEffectSink,
    ActionPaletteHost,
    ActionPaletteWindowStrategy,
)
from tests.qt.test_action_palette import (
    _FakeCommandSource,
    _RecordingCommandDispatcher,
)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
    yield application


def _renderable_descriptors() -> tuple[CommandDescriptor, ...]:
    return (
        CommandDescriptor(
            command_id=CommandId.ASK_ARKCLAW,
            label="Ask ArkClaw",
            group=CommandGroup.AGENT,
            enabled=True,
            invoke_intent=CommandInvokeIntent.CONVERSATION_OPEN_OR_RESTORE,
        ),
        CommandDescriptor(
            command_id=CommandId.INTERACT,
            label="Interact",
            group=CommandGroup.CHARACTER,
            enabled=True,
            invoke_intent=CommandInvokeIntent.PRODUCTION_ACTION,
        ),
        CommandDescriptor(
            command_id=CommandId.ALWAYS_ON_TOP,
            label="Always on Top",
            group=CommandGroup.SYSTEM,
            enabled=True,
            invoke_intent=CommandInvokeIntent.SET_ALWAYS_ON_TOP,
            checked=True,
        ),
    )


def _show_palette_effect() -> PresentationEffect:
    return PresentationEffect(
        PresentationEffectKind.SHOW_FOREGROUND_OVERLAY,
        overlay=ForegroundOverlay.PALETTE,
        layer=ActionPaletteLayer.ROOT,
    )


def _assert_strategy_flags(
    host: ActionPaletteHost,
    strategy: ActionPaletteWindowStrategy,
) -> None:
    flags = host.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    window_type = flags & Qt.WindowType.WindowType_Mask
    if strategy is ActionPaletteWindowStrategy.TOOL:
        assert window_type == Qt.WindowType.Tool
    else:
        assert window_type == Qt.WindowType.Popup


# --- RED A: strategy seam applies flags once at construction ---

def test_strategy_enum_exposes_tool_and_popup() -> None:
    assert ActionPaletteWindowStrategy.TOOL is not None
    assert ActionPaletteWindowStrategy.POPUP is not None


def _cleanup_widget(widget: QWidget) -> None:
    widget.close()
    widget.deleteLater()
    QApplication.instance().processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_tool_strategy_applies_tool_flags_at_construction(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost(strategy=ActionPaletteWindowStrategy.TOOL)
    _assert_strategy_flags(host, ActionPaletteWindowStrategy.TOOL)
    _cleanup_widget(host)


def test_popup_strategy_applies_popup_flags_at_construction(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost(strategy=ActionPaletteWindowStrategy.POPUP)
    _assert_strategy_flags(host, ActionPaletteWindowStrategy.POPUP)
    _cleanup_widget(host)


def test_default_strategy_remains_tool(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    _assert_strategy_flags(host, ActionPaletteWindowStrategy.TOOL)
    _cleanup_widget(host)


def test_render_never_restyles_window_flags(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost(strategy=ActionPaletteWindowStrategy.TOOL)
    before = host.windowFlags()
    host.render_palette(ActionPaletteLayer.ROOT, _renderable_descriptors())
    assert host.windowFlags() == before
    host.render_palette(ActionPaletteLayer.CHARACTER, _renderable_descriptors())
    assert host.windowFlags() == before
    host.render_palette(ActionPaletteLayer.SYSTEM, _renderable_descriptors())
    assert host.windowFlags() == before
    _cleanup_widget(host)


# --- RED B: sink forwards the strategy to the one lazy host ---

def test_sink_forwards_strategy_to_lazy_host(
    qt_application: QApplication,
) -> None:
    del qt_application
    sink = ActionPaletteEffectSink(
        source=_FakeCommandSource(),
        dispatcher=_RecordingCommandDispatcher(),
        strategy=ActionPaletteWindowStrategy.TOOL,
    )
    assert sink.host is None
    sink.apply(_show_palette_effect())
    host = sink.host
    assert host is not None
    _assert_strategy_flags(host, ActionPaletteWindowStrategy.TOOL)
    sink.dispose()
    QApplication.instance().processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- RED C: POPUP strategy preserves the frozen 5B rendering/selection ---

def test_popup_strategy_preserves_5b_rendering_and_selection(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost(strategy=ActionPaletteWindowStrategy.POPUP)
    host.render_palette(ActionPaletteLayer.ROOT, _renderable_descriptors())
    assert host.current_layer is ActionPaletteLayer.ROOT
    assert host.items == (
        ("command", CommandId.OPEN_CHAT_WORK),
        ("command", CommandId.OPEN_CHARACTER_ANIMATION),
        ("nav", ActionPaletteLayer.ANIMATION),
        ("command", CommandId.OPEN_SETTINGS),
    )
    ask = host.row_button(CommandId.OPEN_CHAT_WORK)
    assert ask is not None
    assert ask.text() == "Ask ArkClaw"
    assert ask.isEnabled()

    spy = QSignalSpy(host.command_selected)
    QTest.mouseClick(ask, Qt.MouseButton.LeftButton)
    assert spy.count() == 1
    assert spy.at(0)[0] == CommandId.OPEN_CHAT_WORK

    host.render_palette(
        ActionPaletteLayer.ANIMATION,
        _renderable_descriptors(),
    )
    assert host.items[0] == ("nav", ActionPaletteLayer.ROOT)
    interact = host.row_button(CommandId.INTERACT)
    assert interact is not None
    _cleanup_widget(host)
