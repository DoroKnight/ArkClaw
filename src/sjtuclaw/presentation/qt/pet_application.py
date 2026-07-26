"""Application composition for the placeholder desktop pet."""

from __future__ import annotations

import sys
from typing import NoReturn

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from sjtuclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from sjtuclaw.presentation.qt.application import (
    default_provider_metadata_path,
)
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


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
        self._pet_window.open_agent_requested.connect(self.open_agent_window)
        self._pet_window.safe_exit_requested.connect(self.request_safe_exit)
        self._bridge.shutdown_finished.connect(self._on_shutdown_finished)

    @Slot()
    def open_agent_window(self) -> None:
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    @Slot()
    def request_safe_exit(self) -> None:
        self._main_window.request_safe_close()

    @Slot(bool, str)
    def _on_shutdown_finished(self, success: bool, safe_code: str) -> None:
        del safe_code
        if not success:
            self._pet_window.recover_from_failed_close()
            return
        self._pet_window.complete_safe_close()
        self._main_window.request_safe_close()
        QTimer.singleShot(0, self.quit_requested.emit)


def main(argv: list[str] | None = None) -> int:
    """Run the placeholder pet without activating a cloud Provider."""

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SJTUClaw")
    app.setOrganizationName("SJTU")
    app.setQuitOnLastWindowClosed(False)
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
    coordinator.quit_requested.connect(app.quit)
    pet_window.show()
    return app.exec()


def run() -> NoReturn:
    """Console-script compatible wrapper."""

    raise SystemExit(main())
