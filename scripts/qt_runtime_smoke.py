"""Offline QCoreApplication smoke check for the Qt runtime bridge."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThread, QTimer

from sjtuclaw.application.provider_profile_service import (
    ProviderActivationOptions,
)
from sjtuclaw.bootstrap.qt_runtime import (
    QT_SMOKE_SECONDARY_PROFILE_ID,
    FakeQtRuntimeCompositionRoot,
)
from sjtuclaw.domain.models import FAKE_DEFAULT_PROFILE_ID
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge

_OPTIONS = ProviderActivationOptions(
    timeout_seconds=30.0,
    max_retries=0,
    stream=True,
)
_SMOKE_TIMEOUT_MILLISECONDS = 15_000


def _run_smoke(metadata_path: Path) -> int:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    if not isinstance(app, QCoreApplication):
        print("qt_runtime_smoke=False safe_code=invalid_qt_application")
        return 2

    bridge = QtRuntimeBridge(FakeQtRuntimeCompositionRoot(metadata_path))
    gui_thread = app.thread()
    state = {
        "safe_code": "smoke_incomplete",
        "turn_completed": False,
        "provider_switched": False,
        "signal_thread_safe": True,
        "timed_out": False,
        "shutdown_requested": False,
    }
    command_roles: dict[str, str] = {}

    def note_signal_thread() -> None:
        if QThread.currentThread() is not gui_thread:
            state["signal_thread_safe"] = False

    def request_shutdown() -> None:
        if state["shutdown_requested"]:
            return
        state["shutdown_requested"] = True
        if bridge.runtime_thread.isRunning():
            command_id = bridge.shutdown(cancel_active=True)
            command_roles[command_id] = "shutdown"
        else:
            app.quit()

    def fail(safe_code: str) -> None:
        if state["safe_code"] == "smoke_incomplete":
            state["safe_code"] = safe_code
        request_shutdown()

    def on_ready() -> None:
        note_signal_thread()
        command_id = bridge.activate_profile(
            FAKE_DEFAULT_PROFILE_ID.value,
            _OPTIONS,
            None,
        )
        command_roles[command_id] = "activate_initial"

    def on_command_completed(command_id: str) -> None:
        note_signal_thread()
        role = command_roles.get(command_id)
        if role == "activate_initial":
            send_id = bridge.send_message("offline smoke", "qt-smoke")
            command_roles[send_id] = "send"
        elif role == "activate_secondary":
            state["provider_switched"] = True
            request_shutdown()

    def on_turn_completed(turn_id: str, final_text: str) -> None:
        del turn_id
        note_signal_thread()
        if final_text != "qt-runtime-ok":
            fail("unexpected_fake_response")
            return
        state["turn_completed"] = True
        command_id = bridge.activate_profile(
            QT_SMOKE_SECONDARY_PROFILE_ID.value,
            _OPTIONS,
            None,
        )
        command_roles[command_id] = "activate_secondary"

    def on_command_failed(
        command_id: str,
        safe_code: str,
        safe_message: str,
    ) -> None:
        del command_id, safe_message
        note_signal_thread()
        fail(safe_code)

    def on_shutdown_finished(success: bool, safe_code: str) -> None:
        note_signal_thread()
        if (
            success
            and not state["timed_out"]
            and state["turn_completed"]
            and state["provider_switched"]
            and state["signal_thread_safe"]
        ):
            state["safe_code"] = "none"
        elif state["safe_code"] == "smoke_incomplete":
            state["safe_code"] = safe_code
        app.quit()

    def on_timeout() -> None:
        state["timed_out"] = True
        fail("qt_smoke_timeout")

    bridge.runtime_ready.connect(on_ready)
    bridge.command_completed.connect(on_command_completed)
    bridge.command_failed.connect(on_command_failed)
    bridge.turn_completed.connect(on_turn_completed)
    bridge.shutdown_finished.connect(on_shutdown_finished)

    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.timeout.connect(on_timeout)
    timeout_timer.start(_SMOKE_TIMEOUT_MILLISECONDS)
    start_id = bridge.start_runtime()
    command_roles[start_id] = "start"
    app.exec()
    timeout_timer.stop()

    success = (
        state["safe_code"] == "none"
        and not bridge.runtime_thread.isRunning()
        and bridge.runtime_thread.pending_task_count_at_close == 0
    )
    safe_code = "none" if success else str(state["safe_code"])
    print(
        f"qt_runtime_smoke={success} safe_code={safe_code} "
        f"turn_completed={state['turn_completed']} "
        f"provider_switched={state['provider_switched']} "
        f"signal_thread_safe={state['signal_thread_safe']} "
        f"runtime_thread_closed={not bridge.runtime_thread.isRunning()} "
        "pending_asyncio_tasks="
        f"{bridge.runtime_thread.pending_task_count_at_close}"
    )
    return 0 if success else 2


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sjtuclaw-qt-smoke-") as directory:
        return _run_smoke(Path(directory) / "provider-profiles.json")


if __name__ == "__main__":
    sys.exit(main())
