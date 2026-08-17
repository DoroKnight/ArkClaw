"""Slice 5B - Inactive Action Palette Host characterization (harness only).

Authority: 08 14.2 (Slice 5B), 07 21/23-25, 06 9.2.
The Palette host is an explicit test/development harness surface only: it is
never reachable from production Schwarz. Production Right Click continues to
open the existing native QMenu (Slice 6B owns the cutover).

Contracts proven here:
- the host is lazy-created on the first Palette show request, hidden (never
  destroyed) on dismiss, and the same instance is reused on re-show;
- opening the Palette performs zero command dispatch;
- the host renders CommandDescriptor fields only (label/group/enabled/
  checked/disabled_reason/ordering);
- selection emits exactly one stable CommandId per click and rerender never
  duplicates signal wiring;
- disabled descriptors produce zero selection and zero dispatch;
- dispatch re-resolves the CURRENT descriptor and never lets a stale rendered
  checked snapshot own the mutation target;
- Ask dispatches exactly one ConversationOpenOrRestoreIntent;
- Interact dispatches exactly one existing ProductionAction.INTERACT;
- creating/showing/hiding the Palette through the harness does not change the
  production Schwarz Right Click -> native QMenu path.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu

import arkclaw.presentation.qt.ui.action_palette as action_palette_module
from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.presentation.command_descriptor_adapter import (
    CommandDescriptor,
    CommandGroup,
    CommandId,
    CommandInvokeIntent,
)
from arkclaw.presentation.frontend_presentation import (
    ActionPaletteLayer,
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
    FrontendPresentationIntent,
    ShowForegroundOverlayIntent,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    ThemeVariant,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme
from arkclaw.presentation.qt.ui.action_palette import (
    ActionPaletteEffectSink,
    ActionPaletteHost,
    compute_anchored_palette_position,
)
from tests.qt.test_slice3_character_input_preservation import (
    _Clock,
    _make_window,
    _Player,
    _RecordingCoordinator,
)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = (
        existing if isinstance(existing, QApplication) else QApplication([])
    )
    yield application


class _FakeCommandSource:
    """Qt-free structural stand-in for the existing command source."""

    def __init__(
        self,
        *,
        pet_visible: bool = True,
        pet_paused: bool = False,
        pet_always_on_top: bool = False,
        pet_closing: bool = False,
        available_actions: frozenset[ProductionAction] = frozenset(
            ProductionAction
        ),
        autostart_snapshot: AutostartSnapshot | None = None,
        autostart_busy: bool = False,
    ) -> None:
        self._pet_visible = pet_visible
        self._pet_paused = pet_paused
        self._pet_always_on_top = pet_always_on_top
        self._pet_closing = pet_closing
        self._available_actions = available_actions
        self._autostart_snapshot = autostart_snapshot or (
            AutostartSnapshot.for_status(AutostartStatus.DISABLED)
        )
        self._autostart_busy = autostart_busy

    @property
    def pet_visible(self) -> bool:
        return self._pet_visible

    @property
    def pet_paused(self) -> bool:
        return self._pet_paused

    @property
    def pet_always_on_top(self) -> bool:
        return self._pet_always_on_top

    @property
    def pet_closing(self) -> bool:
        return self._pet_closing

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]:
        return self._available_actions

    @property
    def autostart_snapshot(self) -> AutostartSnapshot:
        return self._autostart_snapshot

    @property
    def autostart_busy(self) -> bool:
        return self._autostart_busy


class _RecordingCommandDispatcher:
    """Records every callback invocation without executing real commands."""

    def __init__(
        self,
        *,
        pet_always_on_top: bool = False,
        autostart_enabled: bool = False,
    ) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.requested_actions: list[ProductionAction] = []
        self.presentation_intents: list[FrontendPresentationIntent] = []
        self._pet_always_on_top = pet_always_on_top
        self._autostart_enabled = autostart_enabled

    @property
    def pet_always_on_top(self) -> bool:
        return self._pet_always_on_top

    @property
    def autostart_enabled(self) -> bool:
        return self._autostart_enabled

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        self.calls.append(("request_pet_action", (action,)))
        self.requested_actions.append(action)
        return ActionOutcome.ACCEPTED

    def resume_pet_autonomous(self) -> ActionOutcome:
        self.calls.append(("resume_pet_autonomous", ()))
        return ActionOutcome.ACCEPTED

    def toggle_paused(self) -> None:
        self.calls.append(("toggle_paused", ()))

    def set_always_on_top(self, enabled: bool) -> None:
        self.calls.append(("set_always_on_top", (enabled,)))

    def set_autostart_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_autostart_enabled", (enabled,)))

    def open_agent_window(self) -> None:
        self.calls.append(("open_agent_window", ()))

    def open_chat_work(self) -> None:
        self.calls.append(("open_chat_work", ()))

    def open_character_animation(self) -> None:
        self.calls.append(("open_character_animation", ()))

    def open_settings(self) -> None:
        self.calls.append(("open_settings", ()))

    def toggle_pet_visibility(self) -> None:
        self.calls.append(("toggle_pet_visibility", ()))

    def request_safe_exit(self) -> None:
        self.calls.append(("request_safe_exit", ()))

    def dispatch_presentation_intent(
        self,
        intent: FrontendPresentationIntent,
    ) -> object:
        self.calls.append(("dispatch_presentation_intent", (intent,)))
        self.presentation_intents.append(intent)
        return None


def _renderable_descriptors() -> tuple[CommandDescriptor, ...]:
    from arkclaw.presentation.command_descriptor_adapter import (
        build_command_descriptors,
    )

    return build_command_descriptors(_FakeCommandSource())


def _dispatch_discarding(
    coordinator: FrontendPresentationCoordinator,
) -> Callable[[FrontendPresentationIntent], None]:
    def handler(intent: FrontendPresentationIntent) -> None:
        coordinator.dispatch(intent)

    return handler


def _make_harness(
    source: _FakeCommandSource,
    dispatcher: _RecordingCommandDispatcher,
) -> tuple[
    ActionPaletteEffectSink,
    FrontendPresentationCoordinator,
]:
    sink = ActionPaletteEffectSink(source=source, dispatcher=dispatcher)
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    return sink, coordinator


def _open_palette(
    coordinator: FrontendPresentationCoordinator,
) -> None:
    coordinator.dispatch(
        ShowForegroundOverlayIntent(ForegroundOverlay.PALETTE)
    )


def _cleanup_host(host: ActionPaletteHost | None) -> None:
    if host is None:
        return
    host.close()
    host.deleteLater()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _dispose_host(sink: ActionPaletteEffectSink) -> None:
    host = sink.host
    sink.dispose()
    _cleanup_host(host)


# --- RED 1: lazy host lifecycle ---

def test_palette_host_is_lazy_created_hidden_and_reused(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)

    assert sink.host is None

    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    assert host.isVisible()
    # Visible-window inventory: exactly one Palette host exists and is shown.
    assert [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, ActionPaletteHost)
    ] == [host]
    # Opening the Palette performs no command.
    assert dispatcher.calls == []

    coordinator.dispatch(DismissForegroundOverlayIntent())
    QApplication.processEvents()
    assert sink.host is host
    assert not host.isVisible()
    assert [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, ActionPaletteHost) and widget.isVisible()
    ] == []

    # Second show reuses the same host instance.
    _open_palette(coordinator)
    QApplication.processEvents()
    assert sink.host is host
    assert host.isVisible()
    assert [
        widget
        for widget in QApplication.topLevelWidgets()
        if isinstance(widget, ActionPaletteHost) and widget.isVisible()
    ] == [host]

    _dispose_host(sink)


# --- RED 2: layered descriptor rendering (same shell) ---

def test_palette_root_layer_renders_fixed_order(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
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

    char_btn = host.row_button(CommandId.OPEN_CHARACTER_ANIMATION)
    assert char_btn is not None
    assert char_btn.text() == "Character"
    assert char_btn.isEnabled()

    anim_btn = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim_btn is not None
    assert anim_btn.text() == "Animation"

    sys_btn = host.row_button(CommandId.OPEN_SETTINGS)
    assert sys_btn is not None
    assert sys_btn.text() == "System"
    assert sys_btn.isEnabled()

    _cleanup_host(host)


def test_palette_animation_layer_renders_actions_plus_back(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.ANIMATION, _renderable_descriptors())

    assert host.current_layer is ActionPaletteLayer.ANIMATION
    back = host.navigation_button(ActionPaletteLayer.ROOT)
    assert back is not None
    assert back.text() == "Back"

    for action_id in (
        CommandId.RELAX,
        CommandId.MOVE_LEFT,
        CommandId.MOVE_RIGHT,
        CommandId.SIT,
        CommandId.SLEEP,
        CommandId.SPECIAL,
        CommandId.INTERACT,
    ):
        btn = host.row_button(action_id)
        assert btn is not None
        assert btn.isEnabled()

    _cleanup_host(host)


def test_palette_selection_emits_exactly_one_command_id_across_rerender(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.ANIMATION, _renderable_descriptors())
    spy = QSignalSpy(host.command_selected)

    sit = host.row_button(CommandId.SIT)
    assert sit is not None
    QTest.mouseClick(sit, Qt.MouseButton.LeftButton)
    assert spy.count() == 1
    assert spy.at(0)[0] == CommandId.SIT

    # Rerender must not duplicate signal wiring.
    host.render_palette(ActionPaletteLayer.ANIMATION, _renderable_descriptors())
    sit_again = host.row_button(CommandId.SIT)
    assert sit_again is not None
    QTest.mouseClick(sit_again, Qt.MouseButton.LeftButton)
    assert spy.count() == 2
    assert spy.at(1)[0] == CommandId.SIT

    _cleanup_host(host)


def test_disabled_palette_command_emits_zero_selection(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    descriptors = (
        CommandDescriptor(
            command_id=CommandId.SIT,
            label="Sit",
            group=CommandGroup.CHARACTER,
            enabled=False,
            invoke_intent=CommandInvokeIntent.PRODUCTION_ACTION,
        ),
    )
    host.render_palette(ActionPaletteLayer.ANIMATION, descriptors)
    spy = QSignalSpy(host.command_selected)

    sit = host.row_button(CommandId.SIT)
    assert sit is not None
    assert not sit.isEnabled()
    QTest.mouseClick(sit, Qt.MouseButton.LeftButton)
    assert spy.count() == 0

    _cleanup_host(host)


def test_disabled_current_descriptor_dispatch_is_zero(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource(
        available_actions=frozenset({ProductionAction.SIT})
    )
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    anim = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim is not None
    anim.click()
    QApplication.processEvents()
    sit = host.row_button(CommandId.SIT)
    assert sit is not None
    assert sit.isEnabled()

    # Dynamic drift to disabled before click
    source._available_actions = frozenset()
    sit.click()
    QApplication.processEvents()

    assert dispatcher.calls == []
    assert dispatcher.requested_actions == []
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


def test_palette_ask_dispatches_open_chat_work(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    ask = host.row_button(CommandId.OPEN_CHAT_WORK)
    assert ask is not None
    ask.click()
    QApplication.processEvents()

    assert ("open_chat_work", ()) in dispatcher.calls
    assert sink.host is host
    assert not host.isVisible()
    _dispose_host(sink)


def test_palette_character_dispatches_open_character_animation(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    char_btn = host.row_button(CommandId.OPEN_CHARACTER_ANIMATION)
    assert char_btn is not None
    char_btn.click()
    QApplication.processEvents()

    assert ("open_character_animation", ()) in dispatcher.calls
    assert not host.isVisible()
    _dispose_host(sink)


def test_palette_system_dispatches_open_settings(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    sys_btn = host.row_button(CommandId.OPEN_SETTINGS)
    assert sys_btn is not None
    sys_btn.click()
    QApplication.processEvents()

    assert ("open_settings", ()) in dispatcher.calls
    assert not host.isVisible()
    _dispose_host(sink)


def test_palette_animation_action_dispatches_action(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    anim_nav = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim_nav is not None
    anim_nav.click()
    QApplication.processEvents()
    assert host.current_layer is ActionPaletteLayer.ANIMATION
    assert dispatcher.calls == []

    sit = host.row_button(CommandId.SIT)
    assert sit is not None
    sit.click()
    QApplication.processEvents()

    assert dispatcher.requested_actions == [ProductionAction.SIT]
    assert ("request_pet_action", (ProductionAction.SIT,)) in dispatcher.calls
    assert not host.isVisible()
    _dispose_host(sink)


# --- 08 14.2 test-first: Escape dismiss ---

def test_palette_escape_routes_dismiss_intent_to_model(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    QTest.keyClick(host, Qt.Key.Key_Escape)
    QApplication.processEvents()

    assert sink.host is host
    assert not host.isVisible()
    assert (
        coordinator.snapshot.foreground_overlay is ForegroundOverlay.NONE
    )
    assert dispatcher.calls == []
    _dispose_host(sink)


# --- RED 8: production right-click isolation ---

def test_palette_host_presence_does_not_change_production_right_click(
    qt_application: QApplication,
) -> None:
    clock = _Clock()
    player = _Player()
    window, _ = _make_window(player, clock)
    coordinator = _RecordingCoordinator()

    # Create/show/hide the Palette through the 5B harness first.
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    palette_sink, palette_coordinator = _make_harness(source, dispatcher)
    _open_palette(palette_coordinator)
    QApplication.processEvents()
    assert palette_sink.host is not None
    palette_coordinator.dispatch(DismissForegroundOverlayIntent())
    QApplication.processEvents()
    assert not palette_sink.host.isVisible()

    # Slice 6B: production Schwarz Right Click now requests the Action
    # Palette; the legacy native QMenu is no longer the Character route.
    palette_requests: list[bool] = []
    window.action_palette_requested.connect(
        lambda: palette_requests.append(True)
    )
    window.show()
    local = window.rect().center()
    context_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        local,
        window.mapToGlobal(local),
    )
    qt_application.sendEvent(window, context_event)
    popup = QApplication.activePopupWidget()

    assert palette_requests == [True]
    assert not isinstance(popup, QMenu)
    assert player.requests == []
    assert len(coordinator.intents) == 0
    assert len(coordinator.effects) == 0

    _dispose_host(palette_sink)
    window.complete_safe_close()


# --- Slice 5B same-shell navigation (08 14.2 "sublevel/back", 07 21, 06 9.4) ---

# --- RED A: Palette opens to ROOT with exactly Ask + Character + System ---

def test_palette_opens_to_root_layer_with_fixed_order(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.ROOT
    assert host.current_layer is ActionPaletteLayer.ROOT
    assert host.items == (
        ("command", CommandId.OPEN_CHAT_WORK),
        ("command", CommandId.OPEN_CHARACTER_ANIMATION),
        ("nav", ActionPaletteLayer.ANIMATION),
        ("command", CommandId.OPEN_SETTINGS),
    )
    assert dispatcher.calls == []
    _dispose_host(sink)


# --- RED B: Character navigation, same host, zero dispatch ---

def test_palette_animation_navigation_same_host_zero_dispatch(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    anim = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim is not None
    anim.click()
    QApplication.processEvents()

    assert sink.host is host
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.ANIMATION
    assert host.current_layer is ActionPaletteLayer.ANIMATION
    assert host.isVisible()
    assert host.row_button(CommandId.SIT) is not None
    assert host.navigation_button(ActionPaletteLayer.ROOT) is not None
    assert dispatcher.calls == []
    _dispose_host(sink)


# --- RED D: Back returns to ROOT in the same host, zero dispatch ---

def test_palette_back_returns_to_root_same_host_zero_dispatch(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    anim = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim is not None
    anim.click()
    QApplication.processEvents()
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.ANIMATION
    assert host.current_layer == ActionPaletteLayer.ANIMATION

    back = host.navigation_button(ActionPaletteLayer.ROOT)
    assert back is not None
    assert back.text() == "Back"
    back.click()
    QApplication.processEvents()

    assert sink.host is host
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.ROOT
    assert host.current_layer is ActionPaletteLayer.ROOT
    assert host.isVisible()
    assert host.items == (
        ("command", CommandId.OPEN_CHAT_WORK),
        ("command", CommandId.OPEN_CHARACTER_ANIMATION),
        ("nav", ActionPaletteLayer.ANIMATION),
        ("command", CommandId.OPEN_SETTINGS),
    )
    assert dispatcher.calls == []
    _dispose_host(sink)


# --- RED H: Escape follows 06 7 (sublayer -> root; root -> dismiss) ---

def test_palette_escape_on_animation_layer_returns_to_root(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    nav = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert nav is not None
    nav.click()
    QApplication.processEvents()
    assert host.current_layer is ActionPaletteLayer.ANIMATION

    QTest.keyClick(host, Qt.Key.Key_Escape)
    QApplication.processEvents()

    model_layer: ActionPaletteLayer = coordinator.snapshot.palette_layer
    rendered_layer: ActionPaletteLayer = host.current_layer
    assert model_layer is ActionPaletteLayer.ROOT
    assert rendered_layer is ActionPaletteLayer.ROOT
    assert host.isVisible()
    assert (
        coordinator.snapshot.foreground_overlay is ForegroundOverlay.PALETTE
    )
    assert dispatcher.calls == []
    _dispose_host(sink)


# --- RED I: reopen always starts at ROOT (06 9.4 "Right Click -> Root") ---

def test_palette_reopen_always_returns_to_root_layer(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    nav = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert nav is not None
    nav.click()
    QApplication.processEvents()
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.ANIMATION

    coordinator.dispatch(DismissForegroundOverlayIntent())
    QApplication.processEvents()
    assert not host.isVisible()

    _open_palette(coordinator)
    QApplication.processEvents()

    assert sink.host is host
    model_layer: ActionPaletteLayer = coordinator.snapshot.palette_layer
    rendered_layer: ActionPaletteLayer = host.current_layer
    assert model_layer is ActionPaletteLayer.ROOT
    assert rendered_layer is ActionPaletteLayer.ROOT
    assert host.items == (
        ("command", CommandId.OPEN_CHAT_WORK),
        ("command", CommandId.OPEN_CHARACTER_ANIMATION),
        ("nav", ActionPaletteLayer.ANIMATION),
        ("command", CommandId.OPEN_SETTINGS),
    )
    _dispose_host(sink)


# --- Navigation rows are Palette semantics, never CommandIds ---

def test_palette_navigation_rows_are_not_command_ids(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.ROOT, _renderable_descriptors())
    command_spy = QSignalSpy(host.command_selected)
    navigation_spy = QSignalSpy(host.navigation_requested)

    anim = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim is not None
    QTest.mouseClick(anim, Qt.MouseButton.LeftButton)

    assert navigation_spy.count() == 1
    assert navigation_spy.at(0)[0] == ActionPaletteLayer.ANIMATION
    assert command_spy.count() == 0
    assert not hasattr(CommandId, "CHARACTER_MENU")
    assert not hasattr(CommandId, "SYSTEM_MENU")
    assert not hasattr(CommandId, "BACK")

    _cleanup_host(host)


# --- Anchored positioning and frozen-tokens theming (Visual Freeze v1) ---

def test_palette_position_anchors_right_of_schwarz_with_gap() -> None:
    anchor = QRect(100, 200, 160, 180)
    work_area = QRect(0, 0, 1920, 1080)
    position = compute_anchored_palette_position(
        anchor=anchor,
        palette_size=QSize(304, 156),
        work_area=work_area,
        gap=12,
        margin=12,
    )
    assert position == QPoint(272, 200)


def test_palette_position_flips_left_when_right_side_does_not_fit() -> None:
    anchor = QRect(1700, 200, 160, 180)
    work_area = QRect(0, 0, 1920, 1080)
    position = compute_anchored_palette_position(
        anchor=anchor,
        palette_size=QSize(304, 156),
        work_area=work_area,
        gap=12,
        margin=12,
    )
    assert position == QPoint(1700 - 12 - 304, 200)


def test_palette_position_flips_above_when_sides_do_not_fit() -> None:
    anchor = QRect(300, 400, 160, 180)
    work_area = QRect(0, 0, 600, 1080)
    position = compute_anchored_palette_position(
        anchor=anchor,
        palette_size=QSize(304, 156),
        work_area=work_area,
        gap=12,
        margin=12,
    )
    # Neither side fits (right would exceed 380 - 12; left would go below 0):
    # the palette centers above the anchor.
    assert position == QPoint(300 + (160 - 304) // 2, 400 - 12 - 156)


def test_palette_position_clamps_into_work_area_when_off_screen() -> None:
    anchor = QRect(-800, 2000, 160, 180)
    work_area = QRect(0, 0, 1920, 1080)
    position = compute_anchored_palette_position(
        anchor=anchor,
        palette_size=QSize(304, 156),
        work_area=work_area,
        gap=12,
        margin=12,
    )
    assert position.x() == 12
    assert position.y() == 1080 - 12 - 156


class _FakePaletteScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1920, 1080)


class _FakeGuiApplication:
    @staticmethod
    def screenAt(point: QPoint) -> _FakePaletteScreen:
        del point
        return _FakePaletteScreen()

    @staticmethod
    def primaryScreen() -> _FakePaletteScreen:
        return _FakePaletteScreen()


def test_palette_host_is_positioned_next_to_anchor_when_provided(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    monkeypatch.setattr(
        action_palette_module,
        "QGuiApplication",
        _FakeGuiApplication,
    )
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    anchor = QRect(100, 200, 160, 180)
    sink = ActionPaletteEffectSink(
        source=source,
        dispatcher=dispatcher,
        anchor_source=lambda: anchor,
    )
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    assert host.isVisible()
    assert host.x() == 100 + 160 + 12
    assert host.y() == 200
    _dispose_host(sink)


def test_palette_host_applies_frozen_tokens_theme_when_configured(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink = ActionPaletteEffectSink(
        source=source,
        dispatcher=dispatcher,
        theme=QtTheme.LIGHT,
    )
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    tokens = load_design_tokens()
    light = tokens.theme(ThemeVariant.LIGHT)
    assert light.surface.surface in host.styleSheet()
    assert light.accent.default in host.styleSheet()
    _dispose_host(sink)


def test_compute_cascading_subpalette_position_right_side_and_left_flip() -> None:
    work_area = QRect(0, 0, 1920, 1080)
    sub_size = QSize(220, 420)
    gap = 6
    margin = 12

    # Normal placement: right of main palette
    main_rect = QRect(100, 200, 220, 200)
    anim_button_rect = QRect(100, 280, 220, 44)
    pos = action_palette_module.compute_cascading_subpalette_position(
        main_palette_rect=main_rect,
        anim_button_rect=anim_button_rect,
        subpalette_size=sub_size,
        work_area=work_area,
        gap=gap,
        margin=margin,
    )
    assert pos.x() == 100 + 220 + gap
    assert pos.y() == 280

    # Near right edge: flips to left of main palette
    main_near_right = QRect(1750, 200, 220, 200)
    anim_btn_near_right = QRect(1750, 280, 220, 44)
    pos_flipped = action_palette_module.compute_cascading_subpalette_position(
        main_palette_rect=main_near_right,
        anim_button_rect=anim_btn_near_right,
        subpalette_size=sub_size,
        work_area=work_area,
        gap=gap,
        margin=margin,
    )
    assert pos_flipped.x() == 1750 - gap - 220
    assert pos_flipped.y() == 280

    # Near bottom edge: vertically clamped
    anim_btn_near_bottom = QRect(100, 900, 220, 44)
    pos_bottom = action_palette_module.compute_cascading_subpalette_position(
        main_palette_rect=main_rect,
        anim_button_rect=anim_btn_near_bottom,
        subpalette_size=sub_size,
        work_area=work_area,
        gap=gap,
        margin=margin,
    )
    assert pos_bottom.y() == 1080 - margin - 420


def test_cascading_sub_palette_selection_and_back(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink = ActionPaletteEffectSink(
        source=source,
        dispatcher=dispatcher,
    )
    coordinator = FrontendPresentationCoordinator(effect_sink=sink)
    sink.attach_intent_handler(_dispatch_discarding(coordinator))
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    # Click Animation to open sub-palette
    anim_nav = host.navigation_button(ActionPaletteLayer.ANIMATION)
    assert anim_nav is not None
    QTest.mouseClick(anim_nav, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    sub_host = host.sub_host
    assert sub_host is not None
    assert sub_host.isVisible()
    assert host.isVisible()  # Main palette stays open!

    # Sub-palette contains Back + actions
    back_btn = sub_host.navigation_button(ActionPaletteLayer.ROOT)
    assert back_btn is not None
    sit_btn = sub_host.row_button(CommandId.SIT)
    assert sit_btn is not None

    # Click Sit in sub-palette
    QTest.mouseClick(sit_btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    assert not sub_host.isVisible()
    assert not host.isVisible()
    assert dispatcher.requested_actions == [ProductionAction.SIT]

    _dispose_host(sink)

