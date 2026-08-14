"""Application composition for the production desktop pet and safe fallback."""

from __future__ import annotations

import sys
from contextlib import suppress
from functools import partial
from typing import NoReturn

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_settings import PetSettings
from arkclaw.application.pet.pet_state import PetLifecycleState
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.system.autostart_operation_journal import (
    AutostartOperationContext,
    AutostartOperationEvent,
    AutostartOperationJournalError,
    AutostartOperationOrigin,
    AutostartOperationRuntimeState,
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
from arkclaw.presentation.qt.application import (
    default_provider_metadata_path,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.platform.single_instance import (
    SingleInstanceRole,
    create_production_single_instance,
)
from arkclaw.presentation.qt.platform.system_tray import SystemTrayController
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


class PetApplicationCoordinator(QObject):
    """Coordinate windows while leaving runtime ownership in the bridge."""

    quit_requested = Signal()
    application_ready = Signal()

    def __init__(
        self,
        bridge: QtRuntimeBridge,
        main_window: MainWindow,
        pet_window: PetWindow,
        *,
        settings_controller: PetSettingsController | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._main_window = main_window
        self._pet_window = pet_window
        self._settings_controller = settings_controller
        self._system_tray: SystemTrayController | None = None
        self._application_ready_published = False
        self._last_action_label = "Relax"
        self._pet_window.open_agent_requested.connect(self.open_agent_window)
        self._pet_window.safe_exit_requested.connect(
            self._begin_runtime_shutdown
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
        self._refresh_control_center()

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
        system_tray.refresh()

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
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

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
        self._main_window.request_safe_close()

    @Slot()
    def _refresh_system_tray(self) -> None:
        if self._system_tray is not None:
            self._system_tray.refresh()

    @Slot()
    def _refresh_control_center(self) -> None:
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
        self._main_window.request_safe_close()
        QTimer.singleShot(0, self.quit_requested.emit)

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
    main_window = MainWindow(
        bridge,
        hide_on_close=True,
        autostart_controller=autostart_controller,
    )
    production_pet = create_optional_production_pet_composition()
    if production_pet is None:
        pet_window = PetWindow(
            autostart_controller=autostart_controller,
        )
    else:
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
        except Exception:
            with suppress(Exception):
                production_pet.renderer.close()
            pet_window = PetWindow(
                autostart_controller=autostart_controller,
            )
    if recorder is not None:
        recorder.record(OwnerStartupStage.PET_WINDOW_CREATED)
    coordinator = PetApplicationCoordinator(
        bridge,
        main_window,
        pet_window,
        settings_controller=settings_controller,
    )
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
