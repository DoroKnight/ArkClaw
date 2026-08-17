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
from PySide6.QtWidgets import QApplication, QMenu, QPushButton

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
    ConversationOpenOrRestoreIntent,
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
            command_id=CommandId.RESUME_AUTONOMOUS,
            label="Resume Autonomous",
            group=CommandGroup.CHARACTER,
            enabled=False,
            invoke_intent=CommandInvokeIntent.RESUME_AUTONOMOUS,
            disabled_reason="action_unavailable",
            conditional=True,
        ),
        CommandDescriptor(
            command_id=CommandId.ALWAYS_ON_TOP,
            label="Always on Top",
            group=CommandGroup.SYSTEM,
            enabled=True,
            invoke_intent=CommandInvokeIntent.SET_ALWAYS_ON_TOP,
            checked=True,
        ),
        CommandDescriptor(
            command_id=CommandId.QUIT,
            label="Quit",
            group=CommandGroup.SYSTEM,
            enabled=True,
            invoke_intent=CommandInvokeIntent.REQUEST_SAFE_EXIT,
        ),
    )


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


def _dispose_host(sink: ActionPaletteEffectSink) -> None:
    host = sink.host
    if host is None:
        return
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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

def test_palette_root_layer_renders_ask_character_system(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.ROOT, _renderable_descriptors())

    assert host.current_layer is ActionPaletteLayer.ROOT
    assert host.items == (
        ("command", CommandId.ASK_ARKCLAW),
        ("nav", ActionPaletteLayer.CHARACTER),
        ("nav", ActionPaletteLayer.SYSTEM),
    )

    ask = host.row_button(CommandId.ASK_ARKCLAW)
    assert ask is not None
    assert ask.text() == "Ask ArkClaw"
    assert ask.isEnabled()
    assert host.navigation_button(ActionPaletteLayer.CHARACTER) is not None
    assert host.navigation_button(ActionPaletteLayer.SYSTEM) is not None
    # ROOT never shows Character/System command rows.
    assert host.row_button(CommandId.INTERACT) is None
    assert host.row_button(CommandId.ALWAYS_ON_TOP) is None

    host.close()
    host.deleteLater()


def test_palette_character_layer_renders_character_descriptors_plus_back(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.CHARACTER, _renderable_descriptors())

    assert host.current_layer is ActionPaletteLayer.CHARACTER
    assert host.items == (
        ("command", CommandId.INTERACT),
        ("command", CommandId.RESUME_AUTONOMOUS),
        ("nav", ActionPaletteLayer.ROOT),
    )

    interact = host.row_button(CommandId.INTERACT)
    assert interact is not None
    assert interact.text() == "Interact"
    assert interact.isEnabled()

    resume = host.row_button(CommandId.RESUME_AUTONOMOUS)
    assert resume is not None
    assert resume.text() == "Resume Autonomous"
    assert not resume.isEnabled()
    assert resume.toolTip() == "action_unavailable"

    back = host.navigation_button(ActionPaletteLayer.ROOT)
    assert back is not None
    assert back.text() == "Back"
    # System commands are not on the Character layer.
    assert host.row_button(CommandId.ALWAYS_ON_TOP) is None

    host.close()
    host.deleteLater()


def test_palette_system_layer_renders_system_descriptors_plus_back(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.SYSTEM, _renderable_descriptors())

    assert host.current_layer is ActionPaletteLayer.SYSTEM
    assert host.items == (
        ("command", CommandId.ALWAYS_ON_TOP),
        ("command", CommandId.QUIT),
        ("nav", ActionPaletteLayer.ROOT),
    )

    top = host.row_button(CommandId.ALWAYS_ON_TOP)
    assert top is not None
    assert "\u2713" in top.text()
    assert host.checked(CommandId.ALWAYS_ON_TOP) is True
    assert host.checked(CommandId.QUIT) is None

    quit_button = host.row_button(CommandId.QUIT)
    assert quit_button is not None
    assert quit_button.text() == "Quit"
    assert quit_button.isEnabled()

    back = host.navigation_button(ActionPaletteLayer.ROOT)
    assert back is not None
    assert back.text() == "Back"
    # Character commands are not on the System layer.
    assert host.row_button(CommandId.INTERACT) is None

    host.close()
    host.deleteLater()


# --- RED 3: exactly-one selection across rerender ---

def test_palette_selection_emits_exactly_one_command_id_across_rerender(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.CHARACTER, _renderable_descriptors())
    spy = QSignalSpy(host.command_selected)

    interact = host.row_button(CommandId.INTERACT)
    assert interact is not None
    QTest.mouseClick(interact, Qt.MouseButton.LeftButton)
    assert spy.count() == 1
    assert spy.at(0)[0] == CommandId.INTERACT

    # Rerender must not duplicate signal wiring.
    host.render_palette(ActionPaletteLayer.CHARACTER, _renderable_descriptors())
    assert len(host.findChildren(QPushButton)) == 3
    interact_again = host.row_button(CommandId.INTERACT)
    assert interact_again is not None
    QTest.mouseClick(interact_again, Qt.MouseButton.LeftButton)
    assert spy.count() == 2
    assert spy.at(1)[0] == CommandId.INTERACT

    host.close()
    host.deleteLater()


# --- RED 4: disabled command ---

def test_disabled_palette_command_emits_zero_selection(
    qt_application: QApplication,
) -> None:
    del qt_application
    host = ActionPaletteHost()
    host.render_palette(ActionPaletteLayer.CHARACTER, _renderable_descriptors())
    spy = QSignalSpy(host.command_selected)

    resume = host.row_button(CommandId.RESUME_AUTONOMOUS)
    assert resume is not None
    assert not resume.isEnabled()
    QTest.mouseClick(resume, Qt.MouseButton.LeftButton)
    assert spy.count() == 0

    host.close()
    host.deleteLater()


def test_disabled_current_descriptor_dispatch_is_zero(
    qt_application: QApplication,
) -> None:
    del qt_application
    # Rendered while INTERACT is available...
    source = _FakeCommandSource(
        available_actions=frozenset({ProductionAction.INTERACT})
    )
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    character = host.navigation_button(ActionPaletteLayer.CHARACTER)
    assert character is not None
    character.click()
    QApplication.processEvents()
    interact = host.row_button(CommandId.INTERACT)
    assert interact is not None
    assert interact.isEnabled()

    # ...but the authoritative source drifts before dispatch: the CURRENT
    # descriptor is resolved at dispatch time and a now-disabled command
    # must produce zero execution.
    source._available_actions = frozenset()
    interact.click()
    QApplication.processEvents()

    assert dispatcher.calls == []
    assert dispatcher.requested_actions == []
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


# --- RED 5: stale render protection ---

def test_stale_checked_render_cannot_own_always_on_top_mutation_target(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource(pet_always_on_top=False)
    dispatcher = _RecordingCommandDispatcher(pet_always_on_top=False)
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    system = host.navigation_button(ActionPaletteLayer.SYSTEM)
    assert system is not None
    system.click()
    QApplication.processEvents()
    assert host.checked(CommandId.ALWAYS_ON_TOP) is False

    # Authoritative current state drifts to True after the stale render.
    dispatcher._pet_always_on_top = True

    top = host.row_button(CommandId.ALWAYS_ON_TOP)
    assert top is not None
    top.click()
    QApplication.processEvents()

    # Target is SET(not current authoritative True) -> False; the stale
    # rendered checked=False snapshot must not become the mutation target.
    assert dispatcher.calls == [("set_always_on_top", (False,))]
    assert sink.host is host
    assert not host.isVisible()
    _dispose_host(sink)


def test_stale_checked_render_cannot_own_autostart_mutation_target(
    qt_application: QApplication,
) -> None:
    del qt_application
    source = _FakeCommandSource(
        autostart_snapshot=AutostartSnapshot.for_status(
            AutostartStatus.DISABLED
        )
    )
    dispatcher = _RecordingCommandDispatcher(autostart_enabled=False)
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None
    system = host.navigation_button(ActionPaletteLayer.SYSTEM)
    assert system is not None
    system.click()
    QApplication.processEvents()
    assert host.checked(CommandId.START_WITH_WINDOWS) is False

    dispatcher._autostart_enabled = True

    start = host.row_button(CommandId.START_WITH_WINDOWS)
    assert start is not None
    start.click()
    QApplication.processEvents()

    assert dispatcher.calls == [("set_autostart_enabled", (False,))]
    _dispose_host(sink)


# --- RED 6: Ask semantic ---

def test_palette_ask_dispatches_exactly_one_conversation_open_or_restore(
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

    ask = host.row_button(CommandId.ASK_ARKCLAW)
    assert ask is not None
    ask.click()
    QApplication.processEvents()

    assert dispatcher.presentation_intents == [
        ConversationOpenOrRestoreIntent()
    ]
    assert dispatcher.requested_actions == []
    assert dispatcher.calls == [
        ("dispatch_presentation_intent", (ConversationOpenOrRestoreIntent(),))
    ]
    # Select dismisses the Palette.
    assert sink.host is host
    assert not host.isVisible()
    _dispose_host(sink)


# --- RED 7: Interact semantic ---

def test_palette_interact_dispatches_existing_interact_exactly_once(
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

    # ROOT -> Character -> Interact (same host, one layer transition).
    character = host.navigation_button(ActionPaletteLayer.CHARACTER)
    assert character is not None
    character.click()
    QApplication.processEvents()
    assert sink.host is host
    assert host.current_layer is ActionPaletteLayer.CHARACTER
    assert dispatcher.calls == []

    interact = host.row_button(CommandId.INTERACT)
    assert interact is not None
    interact.click()
    QApplication.processEvents()

    assert dispatcher.requested_actions == [ProductionAction.INTERACT]
    assert dispatcher.presentation_intents == []
    assert dispatcher.calls == [
        ("request_pet_action", (ProductionAction.INTERACT,))
    ]
    # Select dismisses the Palette.
    assert sink.host is host
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

def test_palette_opens_to_root_layer_with_ask_character_system(
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
        ("command", CommandId.ASK_ARKCLAW),
        ("nav", ActionPaletteLayer.CHARACTER),
        ("nav", ActionPaletteLayer.SYSTEM),
    )
    assert dispatcher.calls == []
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


# --- RED B: Character navigation, same host, zero dispatch ---

def test_palette_character_navigation_same_host_zero_dispatch(
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

    character = host.navigation_button(ActionPaletteLayer.CHARACTER)
    assert character is not None
    character.click()
    QApplication.processEvents()

    assert sink.host is host
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.CHARACTER
    assert host.current_layer is ActionPaletteLayer.CHARACTER
    assert host.isVisible()
    assert host.row_button(CommandId.INTERACT) is not None
    assert host.navigation_button(ActionPaletteLayer.ROOT) is not None
    assert host.navigation_button(ActionPaletteLayer.SYSTEM) is None
    assert dispatcher.calls == []
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


# --- RED C: System navigation, same host, zero dispatch ---

def test_palette_system_navigation_same_host_zero_dispatch(
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

    system = host.navigation_button(ActionPaletteLayer.SYSTEM)
    assert system is not None
    system.click()
    QApplication.processEvents()

    assert sink.host is host
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.SYSTEM
    assert host.current_layer is ActionPaletteLayer.SYSTEM
    assert host.isVisible()
    assert host.row_button(CommandId.ALWAYS_ON_TOP) is not None
    assert host.navigation_button(ActionPaletteLayer.ROOT) is not None
    assert host.navigation_button(ActionPaletteLayer.CHARACTER) is None
    assert dispatcher.calls == []
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


# --- RED D: Back returns to ROOT in the same host, zero dispatch ---

@pytest.mark.parametrize(
    "layer",
    [ActionPaletteLayer.CHARACTER, ActionPaletteLayer.SYSTEM],
)
def test_palette_back_returns_to_root_same_host_zero_dispatch(
    qt_application: QApplication,
    layer: ActionPaletteLayer,
) -> None:
    del qt_application
    source = _FakeCommandSource()
    dispatcher = _RecordingCommandDispatcher()
    sink, coordinator = _make_harness(source, dispatcher)
    _open_palette(coordinator)
    QApplication.processEvents()
    host = sink.host
    assert host is not None

    nav = host.navigation_button(layer)
    assert nav is not None
    nav.click()
    QApplication.processEvents()
    assert coordinator.snapshot.palette_layer is layer
    assert host.current_layer == layer

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
        ("command", CommandId.ASK_ARKCLAW),
        ("nav", ActionPaletteLayer.CHARACTER),
        ("nav", ActionPaletteLayer.SYSTEM),
    )
    assert dispatcher.calls == []
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


# --- RED H: Escape follows 06 7 (sublayer -> root; root -> dismiss) ---

def test_palette_escape_on_character_layer_returns_to_root(
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
    nav = host.navigation_button(ActionPaletteLayer.CHARACTER)
    assert nav is not None
    nav.click()
    QApplication.processEvents()
    assert host.current_layer is ActionPaletteLayer.CHARACTER

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
    assert dispatcher.presentation_intents == []
    _dispose_host(sink)


def test_palette_escape_on_system_layer_returns_to_root(
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
    nav = host.navigation_button(ActionPaletteLayer.SYSTEM)
    assert nav is not None
    nav.click()
    QApplication.processEvents()
    assert host.current_layer is ActionPaletteLayer.SYSTEM

    QTest.keyClick(host, Qt.Key.Key_Escape)
    QApplication.processEvents()

    model_layer: ActionPaletteLayer = coordinator.snapshot.palette_layer
    rendered_layer: ActionPaletteLayer = host.current_layer
    assert model_layer is ActionPaletteLayer.ROOT
    assert rendered_layer is ActionPaletteLayer.ROOT
    assert host.isVisible()
    assert dispatcher.calls == []
    assert dispatcher.presentation_intents == []
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

    nav = host.navigation_button(ActionPaletteLayer.SYSTEM)
    assert nav is not None
    nav.click()
    QApplication.processEvents()
    assert coordinator.snapshot.palette_layer is ActionPaletteLayer.SYSTEM

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
        ("command", CommandId.ASK_ARKCLAW),
        ("nav", ActionPaletteLayer.CHARACTER),
        ("nav", ActionPaletteLayer.SYSTEM),
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

    character = host.navigation_button(ActionPaletteLayer.CHARACTER)
    assert character is not None
    QTest.mouseClick(character, Qt.MouseButton.LeftButton)

    assert navigation_spy.count() == 1
    assert navigation_spy.at(0)[0] == ActionPaletteLayer.CHARACTER
    assert command_spy.count() == 0
    # The frozen Slice 5A command inventory gained no Palette-navigation ids.
    assert not hasattr(CommandId, "CHARACTER_MENU")
    assert not hasattr(CommandId, "SYSTEM_MENU")
    assert not hasattr(CommandId, "BACK")

    host.close()
    host.deleteLater()


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
