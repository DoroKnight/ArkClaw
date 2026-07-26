"""Application composition for the placeholder desktop pet."""

from __future__ import annotations

import sys
from typing import NoReturn

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.pet_state import PetLifecycleState
from sjtuclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from sjtuclaw.presentation.qt.application import (
    default_provider_metadata_path,
)
from sjtuclaw.presentation.qt.main_window import MainWindow
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
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._main_window = main_window
        self._pet_window = pet_window
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
        if self._system_tray is not None:
            self._system_tray.complete_shutdown()
        self._pet_window.complete_safe_close()
        self._main_window.request_safe_close()
        QTimer.singleShot(0, self.quit_requested.emit)


def main(argv: list[str] | None = None) -> int:
    """Run the placeholder pet without activating a cloud Provider."""

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SJTUClaw")
    app.setOrganizationName("SJTU")
    app.setQuitOnLastWindowClosed(False)
    single_instance = create_production_single_instance(app)
    instance_result = single_instance.start()
    if instance_result.role is not SingleInstanceRole.OWNER:
        return instance_result.exit_code
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            default_provider_metadata_path()
        )
    )
    main_window = MainWindow(bridge, hide_on_close=True)
    pet_window = PetWindow()
    coordinator = PetApplicationCoordinator(
        bridge,
        main_window,
        pet_window,
    )
    pet_window.show()
    system_tray = SystemTrayController(
        coordinator,
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
