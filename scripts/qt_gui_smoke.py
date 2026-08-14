"""Offline subprocess smoke for the minimal Qt main window."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from arkclaw.bootstrap.qt_runtime import (
    FakeQtRuntimeCompositionRoot,
)
from arkclaw.presentation.qt.platform.runtime_bridge import (
    QtRuntimeBridge,
)
from arkclaw.presentation.qt.ui.main_window import MainWindow


def main() -> int:
    app = QApplication([])
    shutdown_results: list[tuple[bool, str]] = []
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="arkclaw-gui-smoke-") as directory:
        bridge = QtRuntimeBridge(
            FakeQtRuntimeCompositionRoot(
                Path(directory) / "profiles.json"
            )
        )
        window: MainWindow

        def request_close() -> None:
            QTimer.singleShot(0, window.close)

        def record_shutdown(success: bool, safe_code: str) -> None:
            shutdown_results.append((success, safe_code))

        def timeout() -> None:
            nonlocal timed_out
            timed_out = True
            app.quit()

        bridge.runtime_ready.connect(request_close)
        bridge.shutdown_finished.connect(record_shutdown)
        window = MainWindow(bridge)
        window.show()
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
        )
        print(
            f"qt_gui_smoke={success} "
            f"shutdown_count={len(shutdown_results)} "
            f"thread_running={bridge.runtime_thread.isRunning()} "
            "pending_asyncio_tasks="
            f"{bridge.runtime_thread.pending_task_count_at_close}"
        )
        return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
