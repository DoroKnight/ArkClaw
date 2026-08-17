import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

from arkclaw.bootstrap.autostart import (
    create_production_autostart_service,
)
from arkclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from arkclaw.presentation.frontend_presentation import (
    ForegroundOverlay,
)
from arkclaw.presentation.qt.application import (
    default_provider_metadata_path,
)
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.ui.autostart_controller import (
    AutostartUiController,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow


def run_100_cycle_stress() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(default_provider_metadata_path()),
        autostart_service_factory=create_production_autostart_service,
    )
    autostart = AutostartUiController(bridge)
    pet = PetWindow(autostart_controller=autostart)
    coordinator = PetApplicationCoordinator(
        bridge, None, pet, autostart_controller=autostart
    )
    pet.show()
    app.processEvents()

    failures = 0
    current_time = 1000.0
    coordinator._palette_clock = lambda: current_time
    for cycle in range(100):
        # 1. Right click on pet (closed -> open)
        current_time += 1.0
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            QPoint(50, 50),
            pet.mapToGlobal(QPoint(50, 50)),
        )
        app.sendEvent(pet, event)
        app.processEvents()

        snap = coordinator.frontend_presentation.snapshot
        host = coordinator.palette_sink.host
        if snap.foreground_overlay != ForegroundOverlay.PALETTE or not (
            host and host.isVisible()
        ):
            print(
                f"FAIL cycle {cycle} OPEN: snap={snap.foreground_overlay}, host_visible={host and host.isVisible()}"
            )
            failures += 1

        # 2. Right click to dismiss (open -> closed)
        current_time += 1.0
        event2 = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            QPoint(50, 50),
            pet.mapToGlobal(QPoint(50, 50)),
        )
        app.sendEvent(pet, event2)
        app.processEvents()

        snap2 = coordinator.frontend_presentation.snapshot
        if snap2.foreground_overlay != ForegroundOverlay.NONE:
            print(f"FAIL cycle {cycle} DISMISS: snap={snap2.foreground_overlay}")
            failures += 1

    coordinator.dispose()
    pet.close()
    app.processEvents()
    print(f"100-cycle stress test completed: failures = {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run_100_cycle_stress())
