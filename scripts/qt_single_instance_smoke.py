"""Offline two-process smoke for the desktop-pet instance boundary."""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("QT_QPA_FONTDIR", None)
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QProcess, QTimer, qInstallMessageHandler
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.qt.main_window import MainWindow
from arkclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from arkclaw.presentation.qt.pet_window import PetWindow
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.single_instance import (
    SingleInstanceManager,
    SingleInstanceRole,
)
from arkclaw.presentation.qt.system_tray import (
    PetTrayState,
    SystemTrayController,
    TrayCallbacks,
)
from scripts.qt_pet_smoke import (
    _EXPECTED_QT_PLATFORM_WARNING_COUNTS,
    _QtMessageAudit,
)

_EXPECTED_SINGLE_INSTANCE_WARNING_COUNTS = (
    _EXPECTED_QT_PLATFORM_WARNING_COUNTS.copy()
)
_EXPECTED_SINGLE_INSTANCE_WARNING_COUNTS.pop(
    "This plugin does not support propagateSizeHints()"
)
_EXPECTED_SINGLE_INSTANCE_WARNING_COUNTS[
    "This plugin does not support raise()"
] = 2


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


def _run_secondary_probe(lock_path: Path, server_name: str) -> int:
    app = QApplication([])
    app.setApplicationName("ArkClawSingleInstanceSmokeSecondary")
    manager = SingleInstanceManager(lock_path, server_name)
    result = manager.start()
    print(
        f"secondary_role={result.role.value} "
        f"safe_code={result.safe_code}"
    )
    return result.exit_code


def _run_raw_probe(server_name: str, case_name: str) -> int:
    payloads = {
        "unknown": b"UNKNOWN_V1\n",
        "repeated": b"ACTIVATE_PET_V1\nACTIVATE_PET_V1\n",
        "invalid": b"\xff\n",
        "overlong": b"A" * 65,
        "truncated": b"ACTIVATE_PET_V1",
    }
    payload = payloads.get(case_name)
    if payload is None:
        return 2
    app = QApplication([])
    app.setApplicationName("ArkClawSingleInstanceRawProbe")
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(1_500):
        return 2
    if socket.write(payload) != len(payload):
        return 2
    socket.flush()
    if socket.bytesToWrite() > 0:
        socket.waitForBytesWritten(1_500)
    if case_name == "truncated":
        socket.abort()
        print("raw_probe=truncated_sent")
        return 0
    if not socket.waitForReadyRead(1_500) and socket.bytesAvailable() == 0:
        socket.abort()
        return 2
    response = bytes(socket.readAll().data())
    socket.abort()
    if response != b"REJECT_V1\n":
        return 2
    print("raw_probe=rejected")
    return 0


def _run_owner_hold(lock_path: Path, server_name: str) -> int:
    app = QApplication([])
    manager = SingleInstanceManager(lock_path, server_name)
    result = manager.start()
    if result.role is not SingleInstanceRole.OWNER:
        return 2
    print("owner_hold=ready", flush=True)
    return app.exec()


def _run_contender(
    lock_path: Path,
    server_name: str,
    expected_activations: int,
) -> int:
    app = QApplication([])
    manager = SingleInstanceManager(lock_path, server_name)
    result = manager.start()
    print(
        f"contender_role={result.role.value} "
        f"safe_code={result.safe_code}",
        flush=True,
    )
    if result.role is not SingleInstanceRole.OWNER:
        return result.exit_code
    activation_count = 0
    timed_out = False

    def activated() -> None:
        nonlocal activation_count
        activation_count += 1
        if activation_count == expected_activations:
            manager.close()
            app.quit()

    def timeout() -> None:
        nonlocal timed_out
        timed_out = True
        manager.close()
        app.quit()

    manager.activation_requested.connect(activated)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(timeout)
    watchdog.start(5_000)
    exit_code = app.exec()
    watchdog.stop()
    return (
        0
        if exit_code == 0
        and not timed_out
        and activation_count == expected_activations
        else 2
    )


def _run_owner_smoke(message_audit: _QtMessageAudit) -> int:
    app = QApplication([])
    app.setApplicationName("ArkClawSingleInstanceSmokeOwner")
    app.setQuitOnLastWindowClosed(False)
    timed_out = False
    activation_count = 0
    secondary_count = 0
    owner_count = 0
    shutdown_results: list[tuple[bool, str]] = []
    failed_checks: list[str] = []

    with tempfile.TemporaryDirectory(
        prefix="arkclaw-single-instance-smoke-"
    ) as directory:
        root = Path(directory)
        lock_path = root / "pet.lock"
        server_name = (
            "ArkClaw.Test.SingleInstance."
            f"{uuid.uuid4().hex}"
        )
        owner = SingleInstanceManager(lock_path, server_name)
        owner_result = owner.start()
        if owner_result.role is not SingleInstanceRole.OWNER:
            print(
                "qt_single_instance_smoke=False "
                "failed_checks=owner_start"
            )
            return 2
        owner_count = 1

        bridge = QtRuntimeBridge(
            FakeQtRuntimeCompositionRoot(root / "profiles.json")
        )
        main_window = MainWindow(bridge, hide_on_close=True)
        pet_window = PetWindow(always_on_top=False)
        coordinator = PetApplicationCoordinator(
            bridge,
            main_window,
            pet_window,
        )
        pet_window.show()
        pet_window.move(50_000, 50_000)
        pet_window.hide()
        tray_factory = _FakeTrayFactory()
        tray = SystemTrayController(
            coordinator,
            view_factory=tray_factory,
            parent=coordinator,
        )
        coordinator.attach_system_tray(tray)
        owner.set_closing_probe(lambda: coordinator.pet_closing)
        owner.activation_requested.connect(coordinator.show_pet)

        process = QProcess()

        def on_activation() -> None:
            nonlocal activation_count
            activation_count += 1
            if not pet_window.isVisible():
                failed_checks.append("pet_not_shown")
            if (
                pet_window.pos().x() >= 50_000
                or pet_window.pos().y() >= 50_000
            ):
                failed_checks.append("pet_not_reclaimed")

        def on_secondary_finished(
            exit_code: int,
            exit_status: QProcess.ExitStatus,
        ) -> None:
            nonlocal secondary_count
            stdout = bytes(
                process.readAllStandardOutput().data()
            ).decode("utf-8", errors="replace")
            stderr = bytes(
                process.readAllStandardError().data()
            ).decode("utf-8", errors="replace")
            if (
                exit_code == 0
                and exit_status is QProcess.ExitStatus.NormalExit
                and "secondary_role=secondary safe_code=none" in stdout
                and stderr == ""
            ):
                secondary_count = 1
            else:
                failed_checks.append("secondary_probe")
            QTimer.singleShot(0, coordinator.request_safe_exit)

        def start_secondary() -> None:
            process.setProgram(sys.executable)
            process.setArguments(
                [
                    str(Path(__file__).resolve()),
                    "--secondary-probe",
                    str(lock_path),
                    server_name,
                ]
            )
            process.start()

        def timeout() -> None:
            nonlocal timed_out
            timed_out = True
            if process.state() is not QProcess.ProcessState.NotRunning:
                process.kill()
            app.quit()

        owner.activation_requested.connect(on_activation)
        process.finished.connect(on_secondary_finished)
        bridge.runtime_ready.connect(start_secondary)
        bridge.shutdown_finished.connect(
            lambda success, safe_code: shutdown_results.append(
                (success, safe_code)
            )
        )
        coordinator.quit_requested.connect(owner.close)
        coordinator.quit_requested.connect(app.quit)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(timeout)
        watchdog.start(15_000)
        exit_code = app.exec()
        watchdog.stop()

        view = tray_factory.view
        success = (
            exit_code == 0
            and not timed_out
            and owner_count == 1
            and secondary_count == 1
            and activation_count == 1
            and shutdown_results == [(True, "none")]
            and tray_factory.call_count == 1
            and view is not None
            and view.close_count == 1
            and owner.released
            and not bridge.runtime_thread.isRunning()
            and bridge.runtime_thread.pending_task_count_at_close == 0
            and not pet_window.physics_timer.isActive()
            and process.state() is QProcess.ProcessState.NotRunning
            and message_audit.missing_warning_count == 0
            and message_audit.duplicate_warning_count == 0
            and not message_audit.unexpected_warnings
            and not message_audit.critical_messages
            and not message_audit.other_messages
            and not failed_checks
        )
        print(
            f"qt_single_instance_smoke={success} "
            f"owner_count={owner_count} "
            f"secondary_count={secondary_count} "
            f"activation_count={activation_count} "
            "runtime_thread_count=1 "
            f"tray_count={tray_factory.call_count} "
            f"lock_released={owner.released} "
            "pending_asyncio_tasks="
            f"{bridge.runtime_thread.pending_task_count_at_close} "
            "missing_qt_platform_warnings="
            f"{message_audit.missing_warning_count} "
            "duplicate_qt_platform_warnings="
            f"{message_audit.duplicate_warning_count} "
            "unexpected_qt_warnings="
            f"{len(message_audit.unexpected_warnings)} "
            "failed_checks="
            + ",".join(failed_checks)
        )
        return 0 if success else 2


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "--secondary-probe":
        if len(arguments) != 3:
            return 2
        return _run_secondary_probe(
            Path(arguments[1]),
            arguments[2],
        )
    if arguments and arguments[0] == "--raw-probe":
        if len(arguments) != 3:
            return 2
        return _run_raw_probe(arguments[1], arguments[2])
    if arguments and arguments[0] == "--owner-hold":
        if len(arguments) != 3:
            return 2
        return _run_owner_hold(Path(arguments[1]), arguments[2])
    if arguments and arguments[0] == "--contender":
        if len(arguments) != 4:
            return 2
        try:
            expected_activations = int(arguments[3])
        except ValueError:
            return 2
        if expected_activations < 0:
            return 2
        return _run_contender(
            Path(arguments[1]),
            arguments[2],
            expected_activations,
        )
    if arguments:
        return 2
    message_audit = _QtMessageAudit(
        _EXPECTED_SINGLE_INSTANCE_WARNING_COUNTS
    )
    previous_handler = qInstallMessageHandler(message_audit.handle)
    try:
        return _run_owner_smoke(message_audit)
    finally:
        qInstallMessageHandler(previous_handler)


if __name__ == "__main__":
    sys.exit(main())
