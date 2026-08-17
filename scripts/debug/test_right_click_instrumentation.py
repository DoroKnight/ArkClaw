"""Native right-click instrumentation probe for Stage 10R."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure native windows platform
os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.frontend_presentation import (
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge


def run_probe() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    bridge = QtRuntimeBridge(FakeQtRuntimeCompositionRoot(Path("test_providers.json")))
    pet = PetWindow()
    coordinator = PetApplicationCoordinator(bridge, None, pet)  # type: ignore[arg-type]
    pet.show()
    pet.move(200, 200)
    app.processEvents()

    events_log: list[str] = []

    def log(msg: str) -> None:
        events_log.append(f"[{time.monotonic():.4f}] {msg}")
        print(events_log[-1])

    pet.action_palette_requested.connect(lambda: log("SIGNAL: action_palette_requested"))

    # Test Scenario 1: First right click from closed state
    log("=== Scenario 1: First Right Click (Closed -> Open) ===")
    overlay_before = coordinator.frontend_presentation.snapshot.foreground_overlay
    log(f"Overlay before: {overlay_before}")

    ev1 = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        QPoint(50, 50),
        pet.mapToGlobal(QPoint(50, 50)),
    )
    pet.contextMenuEvent(ev1)
    app.processEvents()

    overlay_after1 = coordinator.frontend_presentation.snapshot.foreground_overlay
    host1 = coordinator.palette_sink.host
    host1_visible = host1 is not None and host1.isVisible()
    log(f"Overlay after 1: {overlay_after1}, host visible: {host1_visible}")

    # Test Scenario 2: Outside dismiss followed immediately by second right click
    log("=== Scenario 2: Dismiss then Immediate Right Click ===")
    coordinator.frontend_presentation.dispatch(DismissForegroundOverlayIntent())
    app.processEvents()
    overlay_dismissed = coordinator.frontend_presentation.snapshot.foreground_overlay
    log(f"Overlay after dismiss: {overlay_dismissed}")

    time.sleep(0.05)  # 50ms later (well within 400ms debounce)

    ev2 = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        QPoint(50, 50),
        pet.mapToGlobal(QPoint(50, 50)),
    )
    pet.contextMenuEvent(ev2)
    app.processEvents()

    overlay_after2 = coordinator.frontend_presentation.snapshot.foreground_overlay
    host2 = coordinator.palette_sink.host
    host2_visible = host2 is not None and host2.isVisible()
    log(f"Overlay after 2 (immediate reopen): {overlay_after2}, host visible: {host2_visible}")

    # Test Scenario 3: 20 sequential open -> dismiss -> open cycles
    log("=== Scenario 3: 20 Sequential Cycles ===")
    failures = 0
    for i in range(20):
        # Dismiss if open
        if coordinator.frontend_presentation.snapshot.foreground_overlay is ForegroundOverlay.PALETTE:
            coordinator.frontend_presentation.dispatch(DismissForegroundOverlayIntent())
            app.processEvents()

        time.sleep(0.02)  # 20ms gap

        ev = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            QPoint(50, 50),
            pet.mapToGlobal(QPoint(50, 50)),
        )
        pet.contextMenuEvent(ev)
        app.processEvents()

        current_overlay = coordinator.frontend_presentation.snapshot.foreground_overlay
        current_host = coordinator.palette_sink.host
        visible = current_host is not None and current_host.isVisible()
        if current_overlay is not ForegroundOverlay.PALETTE or not visible:
            log(f"FAIL at cycle {i}: overlay={current_overlay}, visible={visible}")
            failures += 1
        else:
            log(f"PASS cycle {i}: overlay={current_overlay}, visible={visible}")

    log(f"Total failures: {failures}")
    coordinator.dispose()
    pet.close()
    return failures


if __name__ == "__main__":
    sys.exit(run_probe())
