"""Fully offline subprocess smoke for the placeholder desktop pet."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from sjtuclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


def main() -> int:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    timed_out = False
    shutdown_results: list[tuple[bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="sjtuclaw-pet-smoke-") as directory:
        bridge = QtRuntimeBridge(
            FakeQtRuntimeCompositionRoot(
                Path(directory) / "profiles.json"
            )
        )
        main_window = MainWindow(bridge, hide_on_close=True)
        pet_window = PetWindow()
        coordinator = PetApplicationCoordinator(
            bridge,
            main_window,
            pet_window,
        )

        def timeout() -> None:
            nonlocal timed_out
            timed_out = True
            app.quit()

        bridge.runtime_ready.connect(pet_window.request_safe_exit)
        bridge.shutdown_finished.connect(
            lambda success, safe_code: shutdown_results.append(
                (success, safe_code)
            )
        )
        coordinator.quit_requested.connect(app.quit)
        pet_window.show()
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(timeout)
        watchdog.start(10_000)
        exit_code = app.exec()
        watchdog.stop()

        success = (
            exit_code == 0
            and not timed_out
            and shutdown_results == [(True, "none")]
            and not bridge.runtime_thread.isRunning()
            and bridge.runtime_thread.pending_task_count_at_close == 0
            and not pet_window.physics_timer.isActive()
        )
        print(
            f"qt_pet_smoke={success} "
            f"shutdown_count={len(shutdown_results)} "
            f"thread_running={bridge.runtime_thread.isRunning()} "
            "pending_asyncio_tasks="
            f"{bridge.runtime_thread.pending_task_count_at_close} "
            f"timer_active={pet_window.physics_timer.isActive()}"
        )
        return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
