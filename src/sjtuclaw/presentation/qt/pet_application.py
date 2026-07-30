"""Application composition for the placeholder desktop pet."""

from __future__ import annotations

import sys
from contextlib import suppress
from typing import NoReturn

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.pet_settings import PetSettings
from sjtuclaw.application.pet_state import PetLifecycleState
from sjtuclaw.application.startup_mode import (
    StartupModeArgumentError,
    parse_startup_mode,
)
from sjtuclaw.bootstrap.autostart import (
    create_production_autostart_service,
)
from sjtuclaw.bootstrap.autostart_diagnostics import (
    run_autostart_runtime_diagnostic_if_requested,
)
from sjtuclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from sjtuclaw.presentation.qt.application import (
    default_provider_metadata_path,
)
from sjtuclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_settings_controller import (
    PetSettingsController,
    create_production_pet_settings_controller,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from sjtuclaw.presentation.qt.single_instance import (
    SingleInstanceRole,
    create_production_single_instance,
)
from sjtuclaw.presentation.qt.system_tray import SystemTrayController


class PetApplicationCoordinator(QObject):
    """Coordinate windows while leaving runtime ownership in the bridge."""

    quit_requested = Signal()

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
        self._pet_window.open_agent_requested.connect(self.open_agent_window)
        self._pet_window.safe_exit_requested.connect(
            self._begin_runtime_shutdown
        )
        self._pet_window.presentation_state_changed.connect(
            self._refresh_system_tray
        )
        self._bridge.shutdown_finished.connect(self._on_shutdown_finished)

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

    @Slot()
    def hide_pet(self) -> None:
        if self.pet_closing:
            return
        self._pet_window.hide()
        self._refresh_system_tray()

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

    @Slot()
    def _begin_runtime_shutdown(self) -> None:
        self._main_window.request_safe_close()

    @Slot()
    def _refresh_system_tray(self) -> None:
        if self._system_tray is not None:
            self._system_tray.refresh()

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


def main(argv: list[str] | None = None) -> int:
    """Run the placeholder pet without activating a cloud Provider."""

    arguments = list(sys.argv if argv is None else argv)
    diagnostic_exit_code = (
        run_autostart_runtime_diagnostic_if_requested(arguments)
    )
    if diagnostic_exit_code is not None:
        return diagnostic_exit_code
    try:
        parse_startup_mode(arguments)
    except StartupModeArgumentError:
        return 2
    app = QApplication(arguments)
    app.setApplicationName("SJTUClaw")
    app.setOrganizationName("SJTU")
    app.setQuitOnLastWindowClosed(False)
    single_instance = create_production_single_instance(app)
    instance_result = single_instance.start()
    if instance_result.role is not SingleInstanceRole.OWNER:
        return instance_result.exit_code
    settings_controller = _create_optional_pet_settings_controller()
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            default_provider_metadata_path()
        ),
        autostart_service_factory=create_production_autostart_service,
    )
    autostart_controller = AutostartUiController(bridge, bridge)
    main_window = MainWindow(
        bridge,
        hide_on_close=True,
        autostart_controller=autostart_controller,
    )
    pet_window = PetWindow(
        autostart_controller=autostart_controller,
    )
    coordinator = PetApplicationCoordinator(
        bridge,
        main_window,
        pet_window,
        settings_controller=settings_controller,
    )
    coordinator.restore_pet_settings()
    pet_window.show()
    system_tray = SystemTrayController(
        coordinator,
        autostart_controller=autostart_controller,
        parent=coordinator,
    )
    coordinator.attach_system_tray(system_tray)
    single_instance.set_closing_probe(lambda: coordinator.pet_closing)
    single_instance.activation_requested.connect(coordinator.show_pet)
    coordinator.quit_requested.connect(single_instance.close)
    coordinator.quit_requested.connect(app.quit)
    return app.exec()


def run() -> NoReturn:
    """Console-script compatible wrapper."""

    raise SystemExit(main())
