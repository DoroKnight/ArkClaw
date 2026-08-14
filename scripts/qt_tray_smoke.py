"""Fully offline system-tray smoke using a controlled fake tray view."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("QT_QPA_FONTDIR", None)
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet_state import PetLifecycleState
from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.qt.main_window import MainWindow
from arkclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from arkclaw.presentation.qt.pet_window import PetWindow
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.system_tray import (
    PetTrayState,
    SystemTrayController,
    TrayCallbacks,
)
from scripts.qt_pet_smoke import (
    _EXPECTED_QT_PLATFORM_WARNING_COUNTS,
    _QtMessageAudit,
)

_EXPECTED_TRAY_QT_WARNING_COUNTS = (
    _EXPECTED_QT_PLATFORM_WARNING_COUNTS.copy()
)
_EXPECTED_TRAY_QT_WARNING_COUNTS[
    "This plugin does not support raise()"
] = 4


class _FakeTrayView:
    def __init__(self, callbacks: TrayCallbacks) -> None:
        self.callbacks = callbacks
        self.show_count = 0
        self.close_count = 0
        self.states: list[PetTrayState] = []

    def show(self) -> None:
        self.show_count += 1

    def is_visible(self) -> bool:
        return self.show_count > 0 and self.close_count == 0

    def update_state(self, state: PetTrayState) -> None:
        self.states.append(state)

    def close(self) -> None:
        self.close_count += 1


class _FakeTrayFactory:
    def __init__(self) -> None:
        self.call_count = 0
        self.view: _FakeTrayView | None = None

    def __call__(
        self,
        callbacks: TrayCallbacks,
        parent: QObject,
    ) -> _FakeTrayView:
        del parent
        self.call_count += 1
        self.view = _FakeTrayView(callbacks)
        return self.view


def _run_smoke(message_audit: _QtMessageAudit) -> int:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    timed_out = False
    shutdown_results: list[tuple[bool, str]] = []
    with tempfile.TemporaryDirectory(
        prefix="arkclaw-tray-smoke-"
    ) as directory:
        bridge = QtRuntimeBridge(
            FakeQtRuntimeCompositionRoot(
                Path(directory) / "profiles.json"
            )
        )
        main_window = MainWindow(bridge, hide_on_close=True)
        pet_window = PetWindow(always_on_top=False)
        coordinator = PetApplicationCoordinator(
            bridge,
            main_window,
            pet_window,
        )
        pet_window.show()
        factory = _FakeTrayFactory()
        tray = SystemTrayController(
            coordinator,
            view_factory=factory,
            parent=coordinator,
        )
        coordinator.attach_system_tray(tray)
        view = factory.view
        if view is None:
            return 2
        observed = {
            "hidden_without_runtime_stop": False,
            "shown_inside_workspace": False,
            "agent_opened": False,
            "agent_hidden": False,
            "pause_synchronized": False,
            "continue_synchronized": False,
            "top_synchronized": False,
            "exit_idempotent": False,
        }

        def timeout() -> None:
            nonlocal timed_out
            timed_out = True
            app.quit()

        def exercise_tray() -> None:
            view.callbacks.toggle_pet_visibility()
            observed["hidden_without_runtime_stop"] = (
                not pet_window.isVisible()
                and pet_window.physics_timer.isActive()
                and bridge.runtime_thread.isRunning()
            )
            pet_window.move(50_000, 50_000)
            view.callbacks.toggle_pet_visibility()
            observed["shown_inside_workspace"] = (
                pet_window.isVisible()
                and pet_window.pos().x() < 50_000
                and pet_window.pos().y() < 50_000
            )
            view.callbacks.open_agent_window()
            observed["agent_opened"] = main_window.isVisible()
            main_window.close()
            observed["agent_hidden"] = (
                not main_window.isVisible()
                and bridge.runtime_thread.isRunning()
            )
            view.callbacks.toggle_paused()
            observed["pause_synchronized"] = (
                pet_window.lifecycle_state
                is PetLifecycleState.PAUSED
                and view.states[-1].paused
            )
            view.callbacks.toggle_paused()
            observed["continue_synchronized"] = (
                pet_window.lifecycle_state
                is PetLifecycleState.ACTIVE
                and not view.states[-1].paused
            )
            view.callbacks.set_always_on_top(True)
            observed["top_synchronized"] = (
                pet_window.always_on_top
                and view.states[-1].always_on_top
            )
            view.callbacks.request_safe_exit()
            view.callbacks.request_safe_exit()
            observed["exit_idempotent"] = (
                pet_window.lifecycle_state
                is PetLifecycleState.CLOSING
            )

        bridge.runtime_ready.connect(exercise_tray)
        bridge.shutdown_finished.connect(
            lambda success, safe_code: shutdown_results.append(
                (success, safe_code)
            )
        )
        coordinator.quit_requested.connect(app.quit)
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
            and factory.call_count == 1
            and view.show_count == 1
            and view.close_count == 1
            and tray.closed
            and not bridge.runtime_thread.isRunning()
            and bridge.runtime_thread.pending_task_count_at_close == 0
            and not pet_window.physics_timer.isActive()
            and all(observed.values())
            and message_audit.missing_warning_count == 0
            and message_audit.duplicate_warning_count == 0
            and not message_audit.unexpected_warnings
            and not message_audit.critical_messages
            and not message_audit.other_messages
        )
        print(
            f"qt_tray_smoke={success} "
            f"fake_tray=True "
            f"tray_factory_calls={factory.call_count} "
            f"tray_show_count={view.show_count} "
            f"tray_close_count={view.close_count} "
            f"expected_qt_platform_warnings="
            f"{message_audit.expected_warning_count} "
            f"missing_qt_platform_warnings="
            f"{message_audit.missing_warning_count} "
            f"duplicate_qt_platform_warnings="
            f"{message_audit.duplicate_warning_count} "
            f"unexpected_qt_warnings="
            f"{len(message_audit.unexpected_warnings)} "
            f"qt_critical_messages="
            f"{len(message_audit.critical_messages)} "
            f"qt_other_messages={len(message_audit.other_messages)} "
            f"shutdown_count={len(shutdown_results)} "
            f"thread_running={bridge.runtime_thread.isRunning()} "
            "pending_asyncio_tasks="
            f"{bridge.runtime_thread.pending_task_count_at_close} "
            f"timer_active={pet_window.physics_timer.isActive()} "
            "failed_checks="
            + ",".join(
                name for name, passed in observed.items() if not passed
            )
        )
        return 0 if success else 2


def main() -> int:
    message_audit = _QtMessageAudit(
        _EXPECTED_TRAY_QT_WARNING_COUNTS
    )
    previous_handler = qInstallMessageHandler(message_audit.handle)
    try:
        return _run_smoke(message_audit)
    finally:
        qInstallMessageHandler(previous_handler)


if __name__ == "__main__":
    sys.exit(main())
