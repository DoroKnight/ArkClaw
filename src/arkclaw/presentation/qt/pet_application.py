"""Application composition for the production desktop pet and safe fallback."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from typing import NoReturn

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_settings import PetSettings
from arkclaw.application.pet.pet_state import (
    PetActivityState,
    PetLifecycleState,
)
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_operation_journal import (
    AutostartOperationContext,
    AutostartOperationEvent,
    AutostartOperationJournalError,
    AutostartOperationOrigin,
    AutostartOperationRuntimeState,
)
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.application.system.startup_mode import (
    StartupModeArgumentError,
    parse_startup_mode,
)
from arkclaw.bootstrap.autostart import (
    create_production_autostart_service,
)
from arkclaw.bootstrap.autostart_diagnostics import (
    run_autostart_runtime_diagnostic_if_requested,
)
from arkclaw.bootstrap.pet_production import (
    create_optional_production_pet_composition,
)
from arkclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from arkclaw.presentation.dashboard_presentation import (
    ActiveCharacterSummary,
    AnimationItem,
    AnimationState,
    CharacterAnimationSnapshot,
    DashboardPresentationModel,
    HomeSnapshot,
    RecentWorkItem,
)
from arkclaw.presentation.frontend_presentation import (
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
    FrontendPresentationIntent,
    FrontendPresentationResult,
    ShowForegroundOverlayIntent,
)
from arkclaw.presentation.qt.application import (
    default_provider_metadata_path,
)
from arkclaw.presentation.qt.dashboard.dashboard_integration import (
    DashboardIntegration,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.platform.single_instance import (
    SingleInstanceRole,
    create_production_single_instance,
)
from arkclaw.presentation.qt.platform.system_tray import SystemTrayController
from arkclaw.presentation.qt.theme.qt_theme import QtTheme
from arkclaw.presentation.qt.theme.theme_controller import ThemeController
from arkclaw.presentation.qt.ui.action_palette import (
    ActionPaletteEffectSink,
    ActionPaletteWindowStrategy,
)
from arkclaw.presentation.qt.ui.autostart_controller import (
    AutostartUiController,
)
from arkclaw.presentation.qt.ui.autostart_operation_diagnostics import (
    AutostartOperationDiagnosticArgumentError,
    prepare_autostart_operation_diagnostic_launch,
)
from arkclaw.presentation.qt.ui.main_window import MainWindow
from arkclaw.presentation.qt.ui.owner_ui_readiness import (
    OwnerStartupFailure,
    OwnerStartupStage,
    OwnerUiCheckpointRecorder,
    OwnerUiDiagnosticArgumentError,
    OwnerUiReadinessSnapshot,
    classify_owner_ui_readiness,
    prepare_owner_ui_diagnostic_launch,
)
from arkclaw.presentation.qt.ui.pet_settings_controller import (
    PetSettingsController,
    create_production_pet_settings_controller,
)


class _HookSyncingPresentationCoordinator(FrontendPresentationCoordinator):
    """Presentation coordinator that syncs outside-press routing.

    Every model dispatch is followed by the production outside-press sync,
    which keeps the cross-process Palette dismissal poller scoped to the
    Palette being the foreground overlay (06 9.4 L, 6B 14/38).
    """

    def __init__(
        self,
        *,
        effect_sink: ActionPaletteEffectSink,
        sync_hook: Callable[[], None],
    ) -> None:
        super().__init__(effect_sink=effect_sink)
        self._sync_hook = sync_hook

    def dispatch(
        self,
        intent: FrontendPresentationIntent,
    ) -> FrontendPresentationResult:
        result = super().dispatch(intent)
        self._sync_hook()
        return result


_PALETTE_RAPID_REOPEN_SECONDS = 0.4

# Show-grace for the deactivation-based outside dismissal: the Windows QPA
# plugin can deliver a spurious WindowDeactivate to the Tool host while it is
# being shown (activation dance).  Ignore that dismissal path for a short
# grace after the Palette becomes the foreground overlay; real outside
# presses are still dismissed by the 15 ms native poller, so the frozen
# outside-click contracts are unchanged (06 9.4, 6B 14/38).
_PALETTE_DEACTIVATE_GRACE_SECONDS = 0.5



class _ProductionCommandDescriptorSource:
    """Read-only CommandDescriptorSource projection of the live coordinator."""

    def __init__(
        self,
        coordinator: PetApplicationCoordinator,
        autostart_controller: AutostartUiController | None,
    ) -> None:
        self._coordinator = coordinator
        self._autostart_controller = autostart_controller

    @property
    def pet_visible(self) -> bool:
        return self._coordinator.pet_visible

    @property
    def pet_paused(self) -> bool:
        return self._coordinator.pet_paused

    @property
    def pet_always_on_top(self) -> bool:
        return self._coordinator.pet_always_on_top

    @property
    def pet_closing(self) -> bool:
        return self._coordinator.pet_closing

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]:
        return self._coordinator.available_pet_actions

    @property
    def autostart_snapshot(self) -> AutostartSnapshot:
        controller = self._autostart_controller
        if controller is None:
            return AutostartSnapshot.for_status(AutostartStatus.UNAVAILABLE)
        return controller.snapshot

    @property
    def autostart_busy(self) -> bool:
        controller = self._autostart_controller
        return False if controller is None else controller.busy


class _ProductionCommandDispatcher:
    """Dispatch boundary that routes back to the existing coordinator callbacks."""

    def __init__(
        self,
        coordinator: PetApplicationCoordinator,
        autostart_controller: AutostartUiController | None,
    ) -> None:
        self._coordinator = coordinator
        self._autostart_controller = autostart_controller

    @property
    def pet_always_on_top(self) -> bool:
        return self._coordinator.pet_always_on_top

    @property
    def autostart_enabled(self) -> bool:
        controller = self._autostart_controller
        if controller is None:
            return False
        return controller.snapshot.enabled

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        return self._coordinator.request_pet_action(action)

    def resume_pet_autonomous(self) -> ActionOutcome:
        return self._coordinator.resume_pet_autonomous()

    def toggle_paused(self) -> None:
        self._coordinator.toggle_paused()

    def set_always_on_top(self, enabled: bool) -> None:
        self._coordinator.set_always_on_top(enabled)

    def set_autostart_enabled(self, enabled: bool) -> None:
        controller = self._autostart_controller
        if controller is None:
            return
        controller.set_enabled(
            enabled,
            origin=AutostartOperationOrigin.PET_MENU_ACTION,
        )

    def open_agent_window(self) -> None:
        self._coordinator.open_agent_window()

    def open_chat_work(self) -> None:
        from arkclaw.presentation.qt.dashboard.dashboard_page import (
            DashboardPage,
        )

        self._coordinator.open_dashboard(DashboardPage.CHAT_WORK)

    def open_character_animation(self) -> None:
        from arkclaw.presentation.qt.dashboard.dashboard_page import (
            DashboardPage,
        )

        self._coordinator.open_dashboard(DashboardPage.CHARACTER_ANIMATION)

    def open_settings(self) -> None:
        self._coordinator.open_dashboard_settings()

    def toggle_pet_visibility(self) -> None:
        self._coordinator.toggle_pet_visibility()

    def request_safe_exit(self) -> None:
        self._coordinator.request_safe_exit()

    def dispatch_presentation_intent(
        self,
        intent: FrontendPresentationIntent,
    ) -> object:
        return self._coordinator.frontend_presentation.dispatch(intent)


class PetApplicationCoordinator(QObject):
    """Coordinate windows while leaving runtime ownership in the bridge."""

    quit_requested = Signal()
    application_ready = Signal()

    def __init__(
        self,
        bridge: QtRuntimeBridge,
        main_window: MainWindow | None,
        pet_window: PetWindow,
        *,
        settings_controller: PetSettingsController | None = None,
        autostart_controller: AutostartUiController | None = None,
        theme_controller: ThemeController | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._main_window = main_window
        self._pet_window = pet_window
        self._autostart_controller = autostart_controller
        self._theme_controller = (
            theme_controller
            if theme_controller is not None
            else ThemeController()
        )
        self._palette_source = _ProductionCommandDescriptorSource(
            self,
            autostart_controller,
        )
        self._palette_dispatcher = _ProductionCommandDispatcher(
            self,
            autostart_controller,
        )
        self._palette_sink = ActionPaletteEffectSink(
            source=self._palette_source,
            dispatcher=self._palette_dispatcher,
            strategy=ActionPaletteWindowStrategy.TOOL,
            anchor_source=self._palette_anchor_geometry,
            theme=self._theme_controller.effective_theme,
        )
        self._theme_controller.theme_changed.connect(self._on_theme_changed)
        self.frontend_presentation = _HookSyncingPresentationCoordinator(
            effect_sink=self._palette_sink,
            sync_hook=self._sync_palette_outside_hook,
        )
        self._palette_sink.attach_intent_handler(
            self._dispatch_presentation_intent
        )
        self._dashboard_integration: DashboardIntegration | None = None
        self._settings_controller = settings_controller
        self._system_tray: SystemTrayController | None = None
        self._palette_clock = time.monotonic
        self._last_palette_open_at = -1.0e9
        self._palette_rapid_reopen_seconds = (
            _PALETTE_RAPID_REOPEN_SECONDS
        )
        self._outside_press_timer: QTimer | None = None
        self._disposed = False
        self._hook_target_hwnds: list[int] = []
        self._palette_overlay_since = -1.0e9
        self._application_ready_published = False
        self._last_action_label = "Relax"
        self._pet_window.open_agent_requested.connect(self.open_agent_window)
        self._pet_window.safe_exit_requested.connect(
            self._begin_runtime_shutdown
        )
        self._pet_window.action_palette_requested.connect(
            self._on_action_palette_requested
        )
        self._pet_window.presentation_state_changed.connect(
            self._refresh_system_tray
        )
        self._pet_window.presentation_state_changed.connect(
            self._refresh_control_center
        )
        for signal_name, callback in (
            ("toggle_pet_visibility_requested", self.toggle_pet_visibility),
            ("toggle_pet_paused_requested", self.toggle_paused),
            ("set_pet_always_on_top_requested", self.set_always_on_top),
            ("pet_action_requested", self.request_pet_action_by_name),
        ):
            signal = getattr(self._main_window, signal_name, None)
            if signal is not None:
                signal.connect(callback)
        self._bridge.shutdown_finished.connect(self._on_shutdown_finished)
        self._install_outside_dismiss_routing()
        self._refresh_control_center()

    @property
    def palette_sink(self) -> ActionPaletteEffectSink:
        """The composed production Action Palette effect sink.

        The coordinator owns the sink (and lazily owns the single TOOL
        host); PetWindow only knows "request Palette" (06 4.3, 09 21).
        """

        return self._palette_sink

    @property
    def dashboard_integration(self) -> DashboardIntegration | None:
        """The lazily-created Dashboard integration (None until opened)."""
        return self._dashboard_integration

    def _palette_anchor_geometry(self) -> QRect:
        """Current Schwarz frame that the Palette anchors beside (06 9.2)."""
        geom = self._pet_window.frameGeometry()
        with suppress(Exception):
            anim = getattr(self._pet_window, "_animation", None)
            if anim is not None and anim.frame.state.activity is PetActivityState.SITTING:
                # When sitting, the character's head drops ~40px. Align anchor with sitting head.
                return QRect(geom.x(), geom.y() + 40, geom.width(), max(1, geom.height() - 40))
        return geom

    def open_dashboard(self, page: object | None = None) -> None:
        """Open the Full Dashboard (lazy, one window per product, 07 11).

        Opening is a pure presentation transition: zero Conversation, zero
        backend task, zero application command.  The Dashboard consumes the
        same authoritative FrontendPresentationCoordinator (ConversationContext
        + draft); it never creates a second truth store.
        """
        integration = self._dashboard_integration
        if integration is None:
            character_summary = ActiveCharacterSummary(
                available=True,
                display_name="Schwarz / 黑",
                is_reference=True,
                reference_name="Schwarz",
            )
            home_snapshot = HomeSnapshot(
                greeting="Welcome to ArkClaw",
                intro="Desktop Companion & Intelligent Agent",
                active_character=character_summary,
                recent_work=(
                    RecentWorkItem(
                        title="Chat Mode",
                        subtitle="Casual conversation, character companion & Q&A",
                    ),
                    RecentWorkItem(
                        title="Work Mode",
                        subtitle="Structured tasks, workflows & artifact generation",
                    ),
                ),
            )
            animation_items = (
                AnimationItem(action_id="relax", name="Relax", state=AnimationState.IDLE),
                AnimationItem(action_id="move_left", name="Move Left", state=AnimationState.IDLE),
                AnimationItem(action_id="move_right", name="Move Right", state=AnimationState.IDLE),
                AnimationItem(action_id="sit", name="Sit", state=AnimationState.IDLE),
                AnimationItem(action_id="sleep", name="Sleep", state=AnimationState.IDLE),
                AnimationItem(action_id="special", name="Special", state=AnimationState.IDLE),
                AnimationItem(action_id="interact", name="Interact", state=AnimationState.IDLE),
            )
            character_snapshot = CharacterAnimationSnapshot(
                active_character=character_summary,
                available_characters=("Schwarz / 黑",),
                animations=animation_items,
            )
            model = DashboardPresentationModel(
                home=home_snapshot,
                character=character_snapshot,
            )
            integration = DashboardIntegration(
                self.frontend_presentation,
                model=model,
                autostart_controller=self._autostart_controller,
                animation_trigger_handler=self.request_pet_action_by_name,
                restore_character_handler=self.show_pet,
            )
            self._dashboard_integration = integration
        from arkclaw.presentation.qt.dashboard.dashboard_page import (
            DashboardPage,
        )

        target_page = page if isinstance(page, DashboardPage) else None
        integration.open(target_page)

    def open_dashboard_settings(self) -> None:
        """Open the Full Dashboard and present the Settings dialog."""
        if self.pet_closing:
            return
        self.open_dashboard()
        if (
            self._dashboard_integration is not None
            and self._dashboard_integration.window is not None
        ):
            self._dashboard_integration.window.open_settings_dialog()

    def _on_theme_changed(self, theme: QtTheme) -> None:
        self._palette_sink.set_theme(theme)
        if self._system_tray is not None:
            self._system_tray.set_theme(theme)
        if (
            self._dashboard_integration is not None
            and self._dashboard_integration.window is not None
        ):
            self._dashboard_integration.window.set_theme(theme)

    def dispose(self) -> None:
        """Dispose owned presentation surfaces (idempotent, 6B lifecycle).

        Stops the native outside-press poller, detaches the shared
        application event filter, disconnects the Palette request hook, and
        disposes the Palette sink so no ActionPaletteHost owned by this
        composition survives.  Application command semantics are unchanged;
        calling more than once is safe.
        """
        if self._disposed:
            return
        self._disposed = True
        self._remove_outside_dismiss_routing()
        self._outside_press_timer = None
        with suppress(RuntimeError):
            self._pet_window.action_palette_requested.disconnect(
                self._on_action_palette_requested
            )
        self._palette_sink.dispose()
        integration = self._dashboard_integration
        if integration is not None:
            integration.dispose()
            self._dashboard_integration = None

    def publish_application_ready(self) -> None:
        """Publish the process-wide ready edge exactly once."""

        if self._application_ready_published:
            return
        self._application_ready_published = True
        self.application_ready.emit()

    @property
    def pet_visible(self) -> bool:
        return self._pet_window.isVisible()

    @property
    def pet_paused(self) -> bool:
        return (
            self._pet_window.lifecycle_state
            is PetLifecycleState.PAUSED
        )

    @property
    def pet_always_on_top(self) -> bool:
        return self._pet_window.always_on_top

    @property
    def pet_closing(self) -> bool:
        return (
            self._pet_window.lifecycle_state
            is PetLifecycleState.CLOSING
        )

    @property
    def active_role_pack_id(self) -> str:
        return self._pet_window.active_role_pack_id

    @property
    def available_pet_actions(self) -> frozenset[ProductionAction]:
        return self._pet_window.available_pet_actions

    @property
    def tray_safe_code(self) -> str:
        if self._system_tray is None:
            return "system_tray_not_configured"
        return self._system_tray.safe_code

    @property
    def settings_safe_code(self) -> str:
        if self._settings_controller is None:
            return "pet_settings_not_configured"
        return self._settings_controller.safe_code

    def restore_pet_settings(self) -> None:
        """Restore presentation settings before the owner window is shown."""

        if self._settings_controller is None:
            return
        try:
            result = self._settings_controller.load_once()
            if result.settings is None:
                return
            self._pet_window.set_always_on_top(
                result.settings.always_on_top
            )
            self._pet_window.restore_persisted_position(
                result.settings.window_x,
                result.settings.window_y,
            )
        except Exception:
            self._settings_controller.record_restore_failure()
            with suppress(Exception):
                self._pet_window.restore_builtin_presentation_defaults()

    def attach_system_tray(
        self,
        system_tray: SystemTrayController,
    ) -> None:
        if self._system_tray is not None:
            raise RuntimeError("System tray is already configured.")
        self._system_tray = system_tray
        if self._theme_controller is not None and hasattr(system_tray, "set_theme"):
            system_tray.set_theme(self._theme_controller.effective_theme)
        if hasattr(system_tray, "refresh"):
            system_tray.refresh()

    def attach_autostart_controller(
        self,
        autostart_controller: AutostartUiController,
    ) -> None:
        self._autostart_controller = autostart_controller
        self._palette_source._autostart_controller = autostart_controller
        self._palette_dispatcher._autostart_controller = autostart_controller

    @Slot()
    def show_pet(self) -> None:
        if self.pet_closing:
            return
        self._pet_window.reclaim_to_workspace()
        self._pet_window.show()
        self._refresh_system_tray()
        self._refresh_control_center()

    @Slot()
    def hide_pet(self) -> None:
        if self.pet_closing:
            return
        self._pet_window.hide()
        self._refresh_system_tray()
        self._refresh_control_center()

    @Slot()
    def toggle_pet_visibility(self) -> None:
        if self.pet_visible:
            self.hide_pet()
        else:
            self.show_pet()

    @Slot()
    def open_agent_window(self) -> None:
        if self.pet_closing:
            return
        if self._main_window is not None:
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()
        else:
            self.open_dashboard()

    @Slot()
    def toggle_paused(self) -> None:
        self._pet_window.toggle_paused()

    @Slot(bool)
    def set_always_on_top(self, enabled: bool) -> None:
        self._pet_window.set_always_on_top(enabled)

    @Slot()
    def request_safe_exit(self) -> None:
        self._pet_window.request_safe_exit()

    def request_pet_action(self, action: ProductionAction) -> ActionOutcome:
        outcome = self._pet_window.request_pet_action(action)
        if outcome in (ActionOutcome.ACCEPTED, ActionOutcome.REJECTED_DUPLICATE):
            self._last_action_label = action.value.replace("_", " ").title()
        self._refresh_control_center()
        return outcome

    @Slot(str)
    def request_pet_action_by_name(self, name: str) -> None:
        """Translate control-center labels into the current action contract."""

        action_by_label = {
            "Relax": ProductionAction.RELAX,
            "Move Left": ProductionAction.MOVE_LEFT,
            "Move Right": ProductionAction.MOVE_RIGHT,
            "Sit": ProductionAction.SIT,
            "Sleep": ProductionAction.SLEEP,
            "Special": ProductionAction.SPECIAL,
            "Interact": ProductionAction.INTERACT,
            "relax": ProductionAction.RELAX,
            "move_left": ProductionAction.MOVE_LEFT,
            "move_right": ProductionAction.MOVE_RIGHT,
            "sit": ProductionAction.SIT,
            "sleep": ProductionAction.SLEEP,
            "special": ProductionAction.SPECIAL,
            "interact": ProductionAction.INTERACT,
        }
        action = action_by_label.get(name)
        if action is None:
            return
        self.request_pet_action(action)

    def resume_pet_autonomous(self) -> ActionOutcome:
        outcome = self._pet_window.resume_pet_autonomous()
        if outcome in (ActionOutcome.ACCEPTED, ActionOutcome.REJECTED_DUPLICATE):
            self._last_action_label = "Autonomous"
        self._refresh_control_center()
        return outcome

    @Slot()
    def _begin_runtime_shutdown(self) -> None:
        if self._main_window is not None:
            self._main_window.request_safe_close()
        else:
            self._bridge.shutdown(cancel_active=True)

    @Slot()
    def _refresh_system_tray(self) -> None:
        if self._system_tray is not None:
            self._system_tray.refresh()

    @Slot()
    def _refresh_control_center(self) -> None:
        if self._main_window is None:
            return
        update_presentation = getattr(
            self._main_window,
            "update_pet_presentation",
            None,
        )
        if update_presentation is None:
            return
        update_presentation(
            self.pet_visible,
            self.pet_paused,
            self.pet_always_on_top,
            self._last_action_label,
        )

    @Slot(bool, str)
    def _on_shutdown_finished(self, success: bool, safe_code: str) -> None:
        del safe_code
        if not success:
            self._pet_window.recover_from_failed_close()
            if self._system_tray is not None:
                self._system_tray.recover_failed_shutdown()
            return
        try:
            self._save_pet_settings()
        except Exception:
            if self._settings_controller is not None:
                self._settings_controller.record_snapshot_failure()
        if self._system_tray is not None:
            self._system_tray.complete_shutdown()
        self._pet_window.complete_safe_close()
        if self._main_window is not None:
            self._main_window.request_safe_close()
        QTimer.singleShot(0, self.quit_requested.emit)

    def _dispatch_presentation_intent(
        self,
        intent: FrontendPresentationIntent,
    ) -> None:
        """Route one Palette-originated intent through the model/coordinator."""

        self.frontend_presentation.dispatch(intent)

    def _on_action_palette_requested(self) -> None:
        """Route one completed Schwarz Right Click (06 4.3, 9.4).

        - Palette open + distinct stable right click -> dismiss;
        - rapid double right click during Palette enter -> one open result;
        - otherwise -> ShowForegroundOverlayIntent(PALETTE) at ROOT.
        Opening performs zero application command / zero Conversation.
        """

        snapshot = self.frontend_presentation.snapshot
        now = self._palette_clock()
        if snapshot.foreground_overlay is ForegroundOverlay.PALETTE:
            rapid = (
                now - self._last_palette_open_at
                < self._palette_rapid_reopen_seconds
            )
            if rapid:
                return
            self.frontend_presentation.dispatch(
                DismissForegroundOverlayIntent()
            )
            return
        self._palette_overlay_since = time.monotonic()
        self.frontend_presentation.dispatch(
            ShowForegroundOverlayIntent(ForegroundOverlay.PALETTE)
        )
        self._last_palette_open_at = now

    def _install_outside_dismiss_routing(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        application.installEventFilter(self)
        if os.name == "nt" and self._outside_press_timer is None:
            timer = QTimer(self)
            timer.setInterval(15)
            timer.timeout.connect(self._poll_outside_press)
            self._outside_press_timer = timer
        self.destroyed.connect(self._remove_outside_dismiss_routing)
        application.aboutToQuit.connect(self._remove_outside_dismiss_routing)

    def _remove_outside_dismiss_routing(self) -> None:
        if self._outside_press_timer is not None:
            self._outside_press_timer.stop()
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route Palette-while-open pointer presses (frozen K/L contracts).

        - presses on the Palette host itself are Palette interaction;
        - presses on Schwarz surfaces (PetWindow / its effect overlay) are
          NOT consumed so the existing character chain keeps its exactly-one
          Interact / Drag result (contract K / Drag);
        - an ordinary outside press on any other target dismisses the Palette
          and is consumed: no pass-through (contract L);
        - the Palette host losing activation to an outside native target
          dismisses the Palette through the same presentation seam
          (cross-process outside click, 06 9.4).
        Right-button presses are left to the context-menu seam.
        """

        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self._is_palette_surface(watched)
            and self.frontend_presentation.snapshot.foreground_overlay
            is ForegroundOverlay.PALETTE
            and time.monotonic() - self._palette_overlay_since
            >= _PALETTE_DEACTIVATE_GRACE_SECONDS
        ):
            host = self._palette_sink.host
            if host is not None and host.isVisible():
                cursor_pos = QCursor.pos()
                if self._widget_global_contains(host, cursor_pos):
                    return False
                sub_host = getattr(host, "sub_host", None)
                if (
                    sub_host is not None
                    and sub_host.isVisible()
                    and self._widget_global_contains(sub_host, cursor_pos)
                ):
                    return False
            self.frontend_presentation.dispatch(
                DismissForegroundOverlayIntent()
            )
            return False
        if event.type() not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
        ):
            return False
        if (
            self.frontend_presentation.snapshot.foreground_overlay
            is not ForegroundOverlay.PALETTE
        ):
            return False
        if not isinstance(event, QMouseEvent):
            return False
        if event.button() is Qt.MouseButton.RightButton:
            return False
        if self._is_palette_surface(watched):
            return False
        if self._is_schwarz_surface(watched):
            # Contract K / Drag: a Schwarz press dismisses the Palette but is
            # never consumed, so the existing character chain keeps its
            # exactly-one Interact / Drag result (09 5.1 K, 6B 12/13).
            self.frontend_presentation.dispatch(
                DismissForegroundOverlayIntent()
            )
            return False
        self.frontend_presentation.dispatch(
            DismissForegroundOverlayIntent()
        )
        return True

    def _is_palette_surface(self, watched: object) -> bool:
        """True when the pressed target is a Palette surface (host/sub_host/children/handle)."""
        host = self._palette_sink.host
        if host is None or not host.isVisible():
            return False
        cursor_pos = QCursor.pos()
        if self._widget_global_contains(host, cursor_pos):
            return True
        sub_host = getattr(host, "sub_host", None)
        if (
            sub_host is not None
            and sub_host.isVisible()
            and self._widget_global_contains(sub_host, cursor_pos)
        ):
            return True
        if watched is host:
            return True
        if isinstance(watched, QWidget) and host.isAncestorOf(watched):
            return True
        host_handle = host.windowHandle()
        if host_handle is not None and watched is host_handle:
            return True
        if sub_host is not None and sub_host.isVisible():
            if watched is sub_host:
                return True
            if isinstance(watched, QWidget) and sub_host.isAncestorOf(watched):
                return True
            sub_handle = sub_host.windowHandle()
            if sub_handle is not None and watched is sub_handle:
                return True
        return False

    def _is_schwarz_surface(self, watched: object) -> bool:
        """True when the pressed target is a Schwarz surface (pet/overlay).

        Qt delivers a native press twice through the application event
        filter: once for the QWindow and once for the QWidget (plus the
        overlay's forwarded QMouseEvent).  Both native handles belong to the
        Schwarz surface; consuming the QWindow-level press would swallow the
        character chain (contract K / Drag).
        """

        if watched is self._pet_window:
            return True
        if isinstance(watched, QWidget) and self._pet_window.isAncestorOf(
            watched
        ):
            return True
        pet_handle = self._pet_window.windowHandle()
        if pet_handle is not None and watched is pet_handle:
            return True
        overlay = getattr(self._pet_window, "_effect_overlay", None)
        if overlay is None:
            return False
        if watched is overlay:
            return True
        if isinstance(watched, QWidget) and overlay.isAncestorOf(watched):
            return True
        overlay_handle = overlay.windowHandle()
        return overlay_handle is not None and watched is overlay_handle

    def _poll_outside_press(self) -> None:
        """Dismiss the Palette on an outside left press while it is open.

        A cross-process press (e.g. on the desktop) never reaches the Qt
        event filter.  A WH_MOUSE_LL hook is unusable here: it conflicts
        with Qt's processEvents during drags (RPC_E_DISCONNECTED
        0x8001010d), so the outside press is observed by polling the native
        button state while the Palette is the foreground overlay.  Palette
        and Schwarz presses are ignored: their frozen Qt seams keep
        exactly-one semantics (06 9.4 L, 6B 12/13/14/38).
        """
        if os.name != "nt":
            return
        if not self._native_left_button_down():
            return
        if self._cursor_outside_targets():
            self.frontend_presentation.dispatch(
                DismissForegroundOverlayIntent()
            )

    def _sync_palette_outside_hook(self) -> None:
        """Start/stop the outside-press poller with the Palette state."""

        timer = self._outside_press_timer
        if timer is None:
            return
        try:
            if (
                self.frontend_presentation.snapshot.foreground_overlay
                is ForegroundOverlay.PALETTE
            ):
                if self._palette_overlay_since < 0.0:
                    self._palette_overlay_since = time.monotonic()
                self._hook_target_hwnds = self._capture_outside_targets()
                timer.start()
            else:
                timer.stop()
                self._palette_overlay_since = -1.0e9
        except Exception:
            pass

    def _capture_outside_targets(self) -> list[int]:
        """Native HWNDs that must never be treated as outside presses."""

        targets: list[int] = []
        widgets: list[QWidget] = [self._pet_window]
        host = self._palette_sink.host
        if host is not None:
            widgets.append(host)
            sub_host = getattr(host, "sub_host", None)
            if sub_host is not None:
                widgets.append(sub_host)
        overlay = getattr(self._pet_window, "_effect_overlay", None)
        if overlay is not None:
            widgets.append(overlay)
        for widget in widgets:
            handle = widget.windowHandle()
            if handle is not None:
                targets.append(int(handle.winId()))
        return targets

    @staticmethod
    def _widget_global_contains(widget: QWidget, point: QPoint) -> bool:
        if not widget.isVisible():
            return False
        top_left = widget.mapToGlobal(QPoint(0, 0))
        rect = QRect(top_left, widget.size())
        return rect.contains(point) or widget.frameGeometry().contains(point)

    def _cursor_outside_targets(self) -> bool:
        host = self._palette_sink.host
        if host is not None and host.isVisible():
            cursor_pos = QCursor.pos()
            if self._widget_global_contains(host, cursor_pos):
                return False
            sub_host = getattr(host, "sub_host", None)
            if (
                sub_host is not None
                and self._widget_global_contains(sub_host, cursor_pos)
            ):
                return False
            if self._widget_global_contains(self._pet_window, cursor_pos):
                return False
            overlay = getattr(self._pet_window, "_effect_overlay", None)
            return not (
                overlay is not None
                and self._widget_global_contains(overlay, cursor_pos)
            )

        point = ctypes.wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return False
        targets = self._capture_outside_targets()
        return not any(
            self._native_point_in_hwnd(point.x, point.y, hwnd)
            for hwnd in targets
        )

    def _native_left_button_down(self) -> bool:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)

    def _native_point_in_hwnd(self, x: int, y: int, hwnd: int) -> bool:
        """True when native screen (x, y) is inside the native window."""

        try:
            rect = ctypes.wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(
                hwnd, ctypes.byref(rect)
            ):
                return False
        except Exception:
            return False
        return rect.left <= x < rect.right and rect.top <= y < rect.bottom

    def _save_pet_settings(self) -> None:
        if (
            self._settings_controller is None
            or not self._settings_controller.write_allowed
        ):
            return
        try:
            window_x, window_y, always_on_top = (
                self._pet_window.persisted_presentation_state()
            )
            settings = PetSettings(
                window_x=window_x,
                window_y=window_y,
                always_on_top=always_on_top,
            )
        except Exception:
            self._settings_controller.record_snapshot_failure()
            return
        self._settings_controller.save_once(settings)


def _create_optional_pet_settings_controller() -> PetSettingsController:
    try:
        controller = create_production_pet_settings_controller()
        controller.load_once()
    except Exception:
        return PetSettingsController.initialization_failed()
    return controller


class _OwnerUiStartupObserver(QObject):
    """Bridge Qt readiness facts into the opt-in redacted checkpoint."""

    def __init__(
        self,
        recorder: OwnerUiCheckpointRecorder,
        bridge: QtRuntimeBridge,
        pet_window: PetWindow,
        system_tray: SystemTrayController,
        coordinator: PetApplicationCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._recorder = recorder
        self._bridge = bridge
        self._pet_window = pet_window
        self._system_tray = system_tray
        self._coordinator = coordinator
        self._runtime_ready = False
        self._application_ready = False
        self._closing = False
        self._bridge.runtime_ready.connect(self._on_runtime_ready)
        self._coordinator.application_ready.connect(
            self._on_application_ready
        )
        if self._pet_window.isVisible():
            self._recorder.record(OwnerStartupStage.PET_WINDOW_VISIBLE)
        self._recorder.record(OwnerStartupStage.TRAY_CREATED)
        if self._system_tray.visible:
            self._recorder.record(OwnerStartupStage.TRAY_VISIBLE)
        QTimer.singleShot(0, self._observe_after_event_loop_start)

    @Slot()
    def _observe_after_event_loop_start(self) -> None:
        if self._bridge.accepting_commands and not self._runtime_ready:
            self._on_runtime_ready()

    @Slot()
    def _on_runtime_ready(self) -> None:
        if self._runtime_ready or self._closing:
            return
        self._runtime_ready = True
        self._recorder.record(OwnerStartupStage.RUNTIME_READY)
        anticipated = self._snapshot(application_ready=True)
        failure = classify_owner_ui_readiness(anticipated)
        if failure is not OwnerStartupFailure.NONE:
            self._recorder.record(OwnerStartupStage.FAILED_SAFE, failure)
            return
        self._coordinator.publish_application_ready()

    @Slot()
    def _on_application_ready(self) -> None:
        if self._application_ready or self._closing:
            return
        self._application_ready = True
        snapshot = self._snapshot(application_ready=True)
        failure = classify_owner_ui_readiness(snapshot)
        if failure is OwnerStartupFailure.NONE:
            self._recorder.record(OwnerStartupStage.APPLICATION_READY)
        else:
            self._recorder.record(OwnerStartupStage.FAILED_SAFE, failure)

    @Slot()
    def begin_closing(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._application_ready:
            self._recorder.record(OwnerStartupStage.CLOSING)
        elif self._recorder.last_stage is not OwnerStartupStage.FAILED_SAFE:
            failure = classify_owner_ui_readiness(
                self._snapshot(application_ready=False)
            )
            self._recorder.record(
                OwnerStartupStage.FAILED_SAFE,
                failure,
            )

    def complete_close(self) -> None:
        if self._recorder.last_stage is OwnerStartupStage.CLOSING:
            self._recorder.record(OwnerStartupStage.CLOSED)

    def _snapshot(
        self,
        *,
        application_ready: bool,
    ) -> OwnerUiReadinessSnapshot:
        return OwnerUiReadinessSnapshot(
            instance_owner=True,
            runtime_ready=self._runtime_ready,
            pet_window_constructed=True,
            pet_window_visible=self._pet_window.isVisible(),
            pet_window_in_workspace=_pet_window_in_available_workspace(
                self._pet_window
            ),
            tray_constructed=True,
            tray_available=self._system_tray.available,
            tray_visible=self._system_tray.visible,
            application_ready=application_ready,
        )


def _pet_window_in_available_workspace(pet_window: PetWindow) -> bool:
    geometry = pet_window.frameGeometry()
    return any(
        geometry.intersects(screen.availableGeometry())
        for screen in QApplication.screens()
    )


def main(argv: list[str] | None = None) -> int:
    """Run the production pet, falling back safely when no role pack loads."""

    arguments = list(sys.argv if argv is None else argv)
    diagnostic_exit_code = (
        run_autostart_runtime_diagnostic_if_requested(arguments)
    )
    if diagnostic_exit_code is not None:
        return diagnostic_exit_code
    try:
        operation_launch = prepare_autostart_operation_diagnostic_launch(
            arguments
        )
    except AutostartOperationDiagnosticArgumentError:
        return 2
    arguments = list(operation_launch.arguments)
    operation_journal = operation_launch.journal
    try:
        diagnostic_launch = prepare_owner_ui_diagnostic_launch(arguments)
    except OwnerUiDiagnosticArgumentError:
        return 2
    arguments = list(diagnostic_launch.arguments)
    recorder = diagnostic_launch.recorder
    if recorder is not None:
        recorder.record(OwnerStartupStage.STARTED)
    try:
        parse_startup_mode(arguments)
    except StartupModeArgumentError:
        if recorder is not None:
            recorder.record(
                OwnerStartupStage.FAILED_SAFE,
                OwnerStartupFailure.ARGUMENTS_INVALID,
            )
        return 2
    if recorder is not None:
        recorder.record(OwnerStartupStage.ARGUMENTS_VALIDATED)
    app = QApplication(arguments)
    app.setApplicationName("ArkClaw")
    app.setOrganizationName("ArkClaw")
    app.setQuitOnLastWindowClosed(False)
    single_instance = create_production_single_instance(app)
    instance_result = single_instance.start()
    if instance_result.role is not SingleInstanceRole.OWNER:
        if recorder is not None:
            failure = (
                OwnerStartupFailure.SINGLE_INSTANCE_SECONDARY
                if instance_result.role is SingleInstanceRole.SECONDARY
                else OwnerStartupFailure.SINGLE_INSTANCE_FAILED
            )
            recorder.record(OwnerStartupStage.FAILED_SAFE, failure)
        return instance_result.exit_code
    if recorder is not None:
        recorder.record(OwnerStartupStage.SINGLE_INSTANCE_OWNER)
    settings_controller = _create_optional_pet_settings_controller()
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            default_provider_metadata_path()
        ),
        autostart_service_factory=partial(
            create_production_autostart_service,
            operation_journal=operation_journal,
        ),
        operation_journal=operation_journal,
    )
    if recorder is not None:
        recorder.record(OwnerStartupStage.COMPOSITION_ROOT_CREATED)
    autostart_controller = AutostartUiController(
        bridge,
        bridge,
        operation_journal=operation_journal,
    )
    if recorder is not None:
        recorder.record(OwnerStartupStage.RUNTIME_STARTING)
    production_pet = create_optional_production_pet_composition()
    if production_pet is None:
        sys.stderr.write(
            "[ArkClaw] FATAL: Spine 3.8 production pet composition could not be loaded.\n"
        )
        if recorder is not None:
            recorder.record(
                OwnerStartupStage.FAILED_SAFE,
                OwnerStartupFailure.PET_WINDOW_NOT_CREATED,
            )
        return 2
    try:
        pet_window = PetWindow(
            autostart_controller=autostart_controller,
            renderer=production_pet.renderer,
            track0=production_pet.track0,
            active_role_pack_id=production_pet.role_pack_id,
            available_production_actions=production_pet.available_actions,
            autonomous_scheduler=production_pet.autonomous_scheduler,
            playback_event_source=production_pet.playback_event_source,
        )
    except Exception as exc:
        sys.stderr.write(
            f"[ArkClaw] FATAL: Failed to instantiate Spine 3.8 PetWindow: {exc}\n"
        )
        with suppress(Exception):
            production_pet.renderer.close()
        if recorder is not None:
            recorder.record(
                OwnerStartupStage.FAILED_SAFE,
                OwnerStartupFailure.PET_WINDOW_NOT_CREATED,
            )
        return 2
    if recorder is not None:
        recorder.record(OwnerStartupStage.PET_WINDOW_CREATED)
    theme_controller = ThemeController()
    coordinator = PetApplicationCoordinator(
        bridge,
        None,
        pet_window,
        settings_controller=settings_controller,
        theme_controller=theme_controller,
    )
    if hasattr(coordinator, "attach_autostart_controller"):
        coordinator.attach_autostart_controller(autostart_controller)
    coordinator.restore_pet_settings()
    if recorder is not None:
        recorder.record(OwnerStartupStage.SETTINGS_LOADED)
    pet_window.show()
    system_tray = SystemTrayController(
        coordinator,
        autostart_controller=autostart_controller,
        parent=coordinator,
    )
    coordinator.attach_system_tray(system_tray)
    startup_observer: _OwnerUiStartupObserver | None = None
    if recorder is not None:
        startup_observer = _OwnerUiStartupObserver(
            recorder,
            bridge,
            pet_window,
            system_tray,
            coordinator,
        )
        app.aboutToQuit.connect(startup_observer.begin_closing)
    single_instance.set_closing_probe(lambda: coordinator.pet_closing)
    single_instance.activation_requested.connect(coordinator.show_pet)
    coordinator.quit_requested.connect(single_instance.close)
    coordinator.quit_requested.connect(app.quit)
    if operation_journal is not None:
        closing_context = AutostartOperationContext(
            operation_id="application-closing",
            origin=AutostartOperationOrigin.SHUTDOWN,
        )

        def record_application_closing() -> None:
            with suppress(AutostartOperationJournalError):
                operation_journal.record(
                    AutostartOperationEvent.APPLICATION_CLOSING,
                    closing_context,
                    runtime_state=(
                        AutostartOperationRuntimeState.APPLICATION
                    ),
                )

        app.aboutToQuit.connect(record_application_closing)
    exit_code = app.exec()
    if startup_observer is not None:
        startup_observer.complete_close()
    return exit_code


def run() -> NoReturn:
    """Console-script compatible wrapper."""

    raise SystemExit(main())


if __name__ == "__main__":
    run()

