"""Offline subprocess probe for the QThread CancelledError boundary."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from arkclaw.application.agent.runtime_session_controller import (
    RuntimeCommandResult,
    RuntimeSessionController,
)
from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.platform.runtime_thread import (
    RuntimeThread,
    RuntimeThreadCommand,
)


async def _cancel_command(
    runtime_thread: RuntimeThread,
    command: RuntimeThreadCommand,
    controller: RuntimeSessionController,
) -> RuntimeCommandResult:
    del runtime_thread, command, controller
    raise asyncio.CancelledError("opaque-subprocess-cancel-secret")


def main() -> int:
    _app = QCoreApplication([])
    RuntimeThread._execute_command = _cancel_command  # type: ignore[assignment]
    with tempfile.TemporaryDirectory(
        prefix="arkclaw-cancel-boundary-"
    ) as directory:
        bridge = QtRuntimeBridge(
            FakeQtRuntimeCompositionRoot(
                Path(directory) / "profiles.json"
            )
        )
        completed: list[str] = []
        failed: list[tuple[str, str]] = []
        shutdown_results: list[tuple[bool, str]] = []
        thread_finished: list[bool] = []
        command_id: list[str] = []

        bridge.command_completed.connect(completed.append)
        bridge.command_failed.connect(
            lambda selected_id, code, _message: failed.append(
                (selected_id, code)
            )
        )
        bridge.shutdown_finished.connect(
            lambda success, code: shutdown_results.append((success, code))
        )
        bridge.runtime_thread.finished.connect(
            lambda: thread_finished.append(True)
        )
        bridge.runtime_ready.connect(
            lambda: command_id.append(bridge.request_snapshot())
        )

        bridge.start_runtime()
        wait_loop = QEventLoop()
        poll_timer = QTimer()
        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)

        def finished() -> bool:
            return bool(shutdown_results) and bool(thread_finished)

        poll_timer.timeout.connect(
            lambda: wait_loop.quit() if finished() else None
        )
        timeout_timer.timeout.connect(wait_loop.quit)
        poll_timer.start(1)
        timeout_timer.start(5_000)
        wait_loop.exec()
        poll_timer.stop()
        timeout_timer.stop()

        selected_id = command_id[0] if command_id else ""
        terminal_count = completed.count(selected_id) + sum(
            1 for failed_id, _code in failed if failed_id == selected_id
        )
        safe_code = next(
            (
                code
                for failed_id, code in failed
                if failed_id == selected_id
            ),
            "missing",
        )
        pending_tasks: int | None = (
            bridge.runtime_thread.pending_task_count_at_close
        )
        success = (
            selected_id != ""
            and safe_code == "runtime_command_cancelled"
            and terminal_count == 1
            and len(shutdown_results) == 1
            and shutdown_results[0]
            == (False, "runtime_command_cancelled")
            and len(thread_finished) == 1
            and not bridge.runtime_thread.isRunning()
            and pending_tasks == 0
        )
        print(
            f"cancel_subprocess={success} safe_code={safe_code} "
            f"command_terminal_count={terminal_count} "
            f"shutdown_finished_count={len(shutdown_results)} "
            f"qthread_finished_count={len(thread_finished)} "
            f"thread_running={bridge.runtime_thread.isRunning()} "
            f"pending_asyncio_tasks={pending_tasks}"
        )
        return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
