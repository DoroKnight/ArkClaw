from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import (
    QEventLoop,
    QLockFile,
    QObject,
    QProcess,
    QTimer,
    Signal,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from sjtuclaw.presentation.qt import pet_application
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from sjtuclaw.presentation.qt.single_instance import (
    ActivationMessageStatus,
    SingleInstanceManager,
    SingleInstanceResult,
    SingleInstanceRole,
    _ClientSession,
    classify_activation_message,
)


class _ManualShutdownBridge(QObject):
    shutdown_finished = Signal(bool, str)


class _CleanupEmitter(QObject):
    cleanup_requested = Signal()


class _RecordingMainWindow:
    def __init__(self) -> None:
        self.close_requests = 0

    def request_safe_close(self) -> None:
        self.close_requests += 1

    def show(self) -> None:
        pass

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


class _FakeApplication:
    def __init__(self) -> None:
        self.quit_count = 0

    def setApplicationName(self, value: str) -> None:
        del value

    def setOrganizationName(self, value: str) -> None:
        del value

    def setQuitOnLastWindowClosed(self, value: bool) -> None:
        del value

    def exec(self) -> int:
        return 0

    def quit(self) -> None:
        self.quit_count += 1


class _SecondaryOnlyManager:
    def start(self) -> SingleInstanceResult:
        return SingleInstanceResult(SingleInstanceRole.SECONDARY, "none")


class _FakeLock:
    def __init__(
        self,
        *,
        acquired: bool,
        error: QLockFile.LockError,
        unlock_failures: int = 0,
    ) -> None:
        self._acquired = acquired
        self._error = error
        self._unlock_failures = unlock_failures
        self.unlock_count = 0
        self.stale_lock_times: list[int] = []
        self.calls: list[str] = []

    def setStaleLockTime(self, timeout: int) -> None:
        self.calls.append("set_stale")
        self.stale_lock_times.append(timeout)

    def tryLock(self, timeout: int) -> bool:
        self.calls.append("try_lock")
        assert timeout == 0
        return self._acquired

    def error(self) -> QLockFile.LockError:
        return self._error

    def unlock(self) -> None:
        self.unlock_count += 1
        if self.unlock_count <= self._unlock_failures:
            raise RuntimeError("controlled lock cleanup failure")


class _FakeServer(QObject):
    newConnection = Signal()

    def __init__(
        self,
        *,
        listening: bool,
        close_failures: int = 0,
    ) -> None:
        super().__init__()
        self._listening = listening
        self._close_failures = close_failures
        self.close_count = 0
        self.options: QLocalServer.SocketOption | None = None

    def setSocketOptions(
        self,
        options: QLocalServer.SocketOption,
    ) -> None:
        self.options = options

    def setMaxPendingConnections(self, count: int) -> None:
        assert count == 8

    def listen(self, name: str) -> bool:
        assert name
        return self._listening

    def close(self) -> None:
        self.close_count += 1
        if self.close_count <= self._close_failures:
            raise RuntimeError("controlled server cleanup failure")

    def hasPendingConnections(self) -> bool:
        return False


class _UnreachableSocket:
    def __init__(
        self,
        error: QLocalSocket.LocalSocketError = (
            QLocalSocket.LocalSocketError.ServerNotFoundError
        ),
    ) -> None:
        self._error = error

    def connectToServer(self, name: str) -> None:
        assert name

    def waitForConnected(self, timeout: int) -> bool:
        assert timeout > 0
        return False

    def abort(self) -> None:
        pass

    def error(self) -> QLocalSocket.LocalSocketError:
        return self._error


class _FakeCleanupSocket:
    def __init__(self, *, abort_failures: int = 0) -> None:
        self._abort_failures = abort_failures
        self.abort_count = 0
        self.delete_count = 0

    def abort(self) -> None:
        self.abort_count += 1
        if self.abort_count <= self._abort_failures:
            raise RuntimeError("controlled client cleanup failure")

    def deleteLater(self) -> None:
        self.delete_count += 1


class _FakeCleanupTimer:
    def __init__(self, *, stop_failures: int = 0) -> None:
        self._stop_failures = stop_failures
        self.stop_count = 0
        self.delete_count = 0

    def stop(self) -> None:
        self.stop_count += 1
        if self.stop_count <= self._stop_failures:
            raise RuntimeError("controlled timer cleanup failure")

    def deleteLater(self) -> None:
        self.delete_count += 1


class _FakeReadBuffer:
    def __init__(self, value: bytes) -> None:
        self._value = value

    def data(self) -> bytes:
        return self._value


class _FakeAcceptedSocket(QObject):
    readyRead = Signal()
    disconnected = Signal()

    def __init__(self, payload: bytes = b"") -> None:
        super().__init__()
        self._payload = payload
        self.abort_count = 0
        self.delete_count = 0
        self.disconnect_count = 0
        self.responses: list[bytes] = []

    def setReadBufferSize(self, size: int) -> None:
        assert size == 65

    def bytesAvailable(self) -> int:
        return len(self._payload)

    def readAll(self) -> _FakeReadBuffer:
        value = self._payload
        self._payload = b""
        return _FakeReadBuffer(value)

    def write(self, value: bytes) -> int:
        self.responses.append(value)
        return len(value)

    def flush(self) -> bool:
        return True

    def disconnectFromServer(self) -> None:
        self.disconnect_count += 1
        self.disconnected.emit()

    def abort(self) -> None:
        self.abort_count += 1
        self.disconnected.emit()

    def deleteLater(self) -> None:
        self.delete_count += 1


class _FakeClientTimer(QObject):
    timeout = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.single_shot = False
        self.start_values: list[int] = []
        self.stop_count = 0
        self.delete_count = 0

    def setSingleShot(self, enabled: bool) -> None:
        self.single_shot = enabled

    def start(self, timeout: int) -> None:
        self.active = True
        self.start_values.append(timeout)

    def stop(self) -> None:
        self.active = False
        self.stop_count += 1

    def deleteLater(self) -> None:
        self.delete_count += 1


class _FakeAcceptingServer(_FakeServer):
    def __init__(self, sockets: list[_FakeAcceptedSocket]) -> None:
        super().__init__(listening=True)
        self.sockets = sockets

    def hasPendingConnections(self) -> bool:
        return bool(self.sockets)

    def nextPendingConnection(self) -> QLocalSocket:
        return cast(QLocalSocket, self.sockets.pop(0))


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app


def _run_until(
    predicate: Callable[[], bool],
    *,
    timeout_ms: int = 5_000,
) -> bool:
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)

    def check() -> None:
        if predicate():
            loop.quit()

    poll.timeout.connect(check)
    timeout.timeout.connect(loop.quit)
    poll.start(1)
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    return predicate()


def _namespace() -> str:
    return f"SJTUClaw.Test.SingleInstance.{uuid.uuid4().hex}"


def _probe_path() -> Path:
    return Path(__file__).parents[2] / "scripts" / (
        "qt_single_instance_smoke.py"
    )


def _run_probe(arguments: list[str]) -> tuple[int, str, str]:
    process = QProcess()
    process.setProgram(sys.executable)
    process.setArguments([str(_probe_path()), *arguments])
    process.start()
    assert _run_until(
        lambda: (
            process.state() is QProcess.ProcessState.NotRunning
        )
    )
    stdout = bytes(process.readAllStandardOutput().data()).decode("utf-8")
    stderr = bytes(process.readAllStandardError().data()).decode("utf-8")
    assert process.exitStatus() is QProcess.ExitStatus.NormalExit
    return process.exitCode(), stdout, stderr


def _start_secondary(
    lock_path: Path,
    server_name: str,
) -> SingleInstanceResult:
    exit_code, stdout, stderr = _run_probe(
        [
            "--secondary-probe",
            str(lock_path),
            server_name,
        ]
    )
    assert stderr == ""
    if "secondary_role=secondary safe_code=none" in stdout:
        assert exit_code == 0
        return SingleInstanceResult(SingleInstanceRole.SECONDARY, "none")
    if (
        "secondary_role=secondary "
        "safe_code=single_instance_owner_busy"
    ) in stdout:
        assert exit_code == 2
        return SingleInstanceResult(
            SingleInstanceRole.SECONDARY,
            "single_instance_owner_busy",
        )
    raise AssertionError(f"Unexpected safe secondary output: {stdout!r}")


def _install_cleanup_fakes(
    manager: SingleInstanceManager,
    *,
    server: _FakeServer,
    lock: _FakeLock,
    socket: _FakeCleanupSocket,
    timer: _FakeCleanupTimer,
) -> None:
    typed_socket = cast(QLocalSocket, socket)
    manager._server = cast(QLocalServer, server)
    manager._lock = cast(QLockFile, lock)
    manager._lock_held = True
    manager._clients[typed_socket] = _ClientSession(
        socket=typed_socket,
        timer=cast(QTimer, timer),
        buffer=bytearray(),
    )


@pytest.mark.parametrize(
    ("payload", "disconnected", "expected"),
    [
        (
            b"ACTIVATE_PET_V1\n",
            False,
            ActivationMessageStatus.ACTIVATE,
        ),
        (b"ACTIVATE_PET_V1", False, ActivationMessageStatus.INCOMPLETE),
        (b"ACTIVATE_PET_V1", True, ActivationMessageStatus.REJECT),
        (b"UNKNOWN\n", False, ActivationMessageStatus.REJECT),
        (
            b"ACTIVATE_PET_V1\nACTIVATE_PET_V1\n",
            False,
            ActivationMessageStatus.REJECT,
        ),
        (b"\xff\n", False, ActivationMessageStatus.REJECT),
        (b"A" * 65, False, ActivationMessageStatus.REJECT),
    ],
)
def test_fixed_activation_protocol_rejects_invalid_messages(
    payload: bytes,
    disconnected: bool,
    expected: ActivationMessageStatus,
) -> None:
    assert (
        classify_activation_message(
            payload,
            disconnected=disconnected,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("stale_lock_time_ms", -1),
        ("client_timeout_ms", 0),
        ("max_active_clients", 0),
    ],
)
def test_invalid_instance_limits_fail_before_filesystem_access(
    tmp_path: Path,
    parameter: str,
    value: int,
) -> None:
    lock_path = tmp_path / "not-created" / "pet.lock"

    with pytest.raises(ValueError):
        if parameter == "stale_lock_time_ms":
            SingleInstanceManager(
                lock_path,
                _namespace(),
                stale_lock_time_ms=value,
            )
        elif parameter == "client_timeout_ms":
            SingleInstanceManager(
                lock_path,
                _namespace(),
                client_timeout_ms=value,
            )
        else:
            SingleInstanceManager(
                lock_path,
                _namespace(),
                max_active_clients=value,
            )

    assert not lock_path.parent.exists()


def test_stale_lock_time_is_set_to_zero_before_try_lock(
    tmp_path: Path,
) -> None:
    lock = _FakeLock(
        acquired=False,
        error=QLockFile.LockError.PermissionError,
    )
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        lock_factory=lambda path: cast(QLockFile, lock),
    )

    result = manager.start()

    assert manager.stale_lock_time_ms == 0
    assert lock.stale_lock_times == [0]
    assert lock.calls == ["set_stale", "try_lock"]
    assert result.safe_code == "single_instance_lock_permission_denied"


def test_old_lock_file_age_does_not_replace_live_owner(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    lock_path = tmp_path / "pet.lock"
    server_name = _namespace()
    owner = SingleInstanceManager(lock_path, server_name)
    assert owner.start().role is SingleInstanceRole.OWNER
    os.utime(lock_path, (1, 1))

    result = _start_secondary(lock_path, server_name)

    assert result.role is SingleInstanceRole.SECONDARY
    assert result.safe_code == "none"
    assert owner.lock_held
    owner.close()


def test_first_instance_owns_lock_and_second_only_activates(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    lock_path = tmp_path / "pet.lock"
    server_name = _namespace()
    owner = SingleInstanceManager(lock_path, server_name)
    activation_count = 0

    def activated() -> None:
        nonlocal activation_count
        activation_count += 1

    owner.activation_requested.connect(activated)
    first = owner.start()

    assert first.role is SingleInstanceRole.OWNER
    assert owner.lock_held
    second = _start_secondary(lock_path, server_name)

    assert second == SingleInstanceResult(
        SingleInstanceRole.SECONDARY,
        "none",
    )
    assert activation_count == 1
    assert owner.last_ipc_safe_code == "none"

    owner.close()
    assert owner.released
    successor = SingleInstanceManager(lock_path, server_name)
    assert successor.start().role is SingleInstanceRole.OWNER
    successor.close()


def test_activation_reclaims_hidden_pet_without_touching_runtime_turn(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    lock_path = tmp_path / "pet.lock"
    server_name = _namespace()
    owner = SingleInstanceManager(lock_path, server_name)
    assert owner.start().role is SingleInstanceRole.OWNER
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    pet = PetWindow()
    pet.move(50_000, 50_000)
    pet.hide()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    owner.set_closing_probe(lambda: coordinator.pet_closing)
    owner.activation_requested.connect(coordinator.show_pet)

    result = _start_secondary(lock_path, server_name)

    assert result.safe_code == "none"
    assert pet.isVisible()
    assert pet.pos().x() < 50_000
    assert pet.pos().y() < 50_000
    assert main_window.close_requests == 0
    owner.close()
    pet.complete_safe_close()


def test_closing_owner_returns_busy_without_reactivation(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    lock_path = tmp_path / "pet.lock"
    server_name = _namespace()
    owner = SingleInstanceManager(lock_path, server_name)
    owner.set_closing_probe(lambda: True)
    activation_count = 0

    def activated() -> None:
        nonlocal activation_count
        activation_count += 1

    owner.activation_requested.connect(activated)
    assert owner.start().role is SingleInstanceRole.OWNER

    result = _start_secondary(lock_path, server_name)

    assert result.role is SingleInstanceRole.SECONDARY
    assert result.safe_code == "single_instance_owner_busy"
    assert result.exit_code == 2
    assert activation_count == 0
    assert owner.lock_held
    owner.close()


def test_runtime_shutdown_failure_retains_lock_until_successful_retry(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
    )
    assert owner.start().role is SingleInstanceRole.OWNER
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    pet = PetWindow()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    coordinator.quit_requested.connect(owner.close)

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(False, "runtime_shutdown_failed")

    assert owner.lock_held
    assert not owner.released
    assert pet.physics_timer.isActive()

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")

    assert _run_until(lambda: owner.released)
    assert not pet.physics_timer.isActive()


def test_active_client_limit_rejects_ninth_idle_connection(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    sockets = [_FakeAcceptedSocket() for _ in range(9)]
    server = _FakeAcceptingServer(sockets.copy())
    timers: list[_FakeClientTimer] = []

    def timer_factory(parent: QObject) -> QTimer:
        del parent
        timer = _FakeClientTimer()
        timers.append(timer)
        return cast(QTimer, timer)

    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        client_timeout_ms=5_000,
        max_active_clients=8,
        timer_factory=timer_factory,
    )
    owner._server = cast(QLocalServer, server)

    owner._accept_connections()

    assert owner.last_ipc_safe_code == (
        "single_instance_client_limit_reached"
    )
    assert owner.active_client_count == 8
    assert len(timers) == 8
    assert all(timer.active for timer in timers)
    assert sockets[8].responses == [b"REJECT_V1\n"]
    assert sockets[8].disconnect_count == 1
    owner.close()
    assert owner.active_client_count == 0
    assert all(not timer.active for timer in timers)


def test_idle_client_timeout_releases_capacity_without_sleep(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    first = _FakeAcceptedSocket()
    second = _FakeAcceptedSocket()
    server = _FakeAcceptingServer([first])
    timers: list[_FakeClientTimer] = []

    def timer_factory(parent: QObject) -> QTimer:
        del parent
        timer = _FakeClientTimer()
        timers.append(timer)
        return cast(QTimer, timer)

    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        client_timeout_ms=25,
        max_active_clients=1,
        timer_factory=timer_factory,
    )
    owner._server = cast(QLocalServer, server)
    owner._accept_connections()
    assert owner.active_client_count == 1

    timers[0].timeout.emit()

    assert _run_until(
        lambda: (
            owner.active_client_count == 0
            and owner.last_ipc_safe_code
            == "single_instance_client_timeout"
        )
    )
    assert first.abort_count == 1
    assert not timers[0].active

    server.sockets.append(second)
    owner._accept_connections()

    assert owner.active_client_count == 1
    assert len(timers) == 2
    owner.close()
    assert owner.active_client_count == 0


def test_ready_read_and_timeout_race_has_one_terminal_cleanup(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    socket = _FakeAcceptedSocket(b"ACTIVATE_PET_V1\n")
    server = _FakeAcceptingServer([socket])
    timers: list[_FakeClientTimer] = []

    def timer_factory(parent: QObject) -> QTimer:
        del parent
        timer = _FakeClientTimer()
        timers.append(timer)
        return cast(QTimer, timer)

    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        client_timeout_ms=5_000,
        max_active_clients=1,
        timer_factory=timer_factory,
    )
    activation_count = 0

    def activated() -> None:
        nonlocal activation_count
        activation_count += 1

    owner.activation_requested.connect(activated)
    owner._server = cast(QLocalServer, server)
    owner._accept_connections()
    server_socket = cast(QLocalSocket, socket)

    owner._read_client(server_socket)
    owner._expire_client(server_socket)

    assert owner.active_client_count == 0
    assert owner.last_ipc_safe_code == "none"
    assert _run_until(lambda: activation_count == 1)
    assert socket.responses == [b"ACK_V1\n"]
    assert socket.disconnect_count == 1
    assert timers[0].stop_count == 1
    assert timers[0].delete_count == 1
    assert socket.delete_count == 1
    owner.close()


def test_manager_close_stops_all_client_timers(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    sockets = [_FakeAcceptedSocket() for _ in range(3)]
    server = _FakeAcceptingServer(sockets.copy())
    timers: list[_FakeClientTimer] = []

    def timer_factory(parent: QObject) -> QTimer:
        del parent
        timer = _FakeClientTimer()
        timers.append(timer)
        return cast(QTimer, timer)

    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        client_timeout_ms=5_000,
        timer_factory=timer_factory,
    )
    owner._server = cast(QLocalServer, server)
    owner._accept_connections()
    assert owner.active_client_count == 3
    assert len(timers) == 3
    assert all(timer.active for timer in timers)

    owner.close()

    assert owner.active_client_count == 0
    assert all(not timer.active for timer in timers)
    assert all(timer.stop_count == 1 for timer in timers)
    assert all(socket.abort_count == 1 for socket in sockets)


def test_permission_error_does_not_attempt_ipc_or_become_owner(
    tmp_path: Path,
) -> None:
    lock = _FakeLock(
        acquired=False,
        error=QLockFile.LockError.PermissionError,
    )
    socket_calls = 0

    def socket_factory() -> QLocalSocket:
        nonlocal socket_calls
        socket_calls += 1
        raise AssertionError("IPC must not start after a lock permission error.")

    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        lock_factory=lambda path: cast(QLockFile, lock),
        socket_factory=socket_factory,
    )

    result = manager.start()

    assert result.role is SingleInstanceRole.FAILED
    assert result.safe_code == "single_instance_lock_permission_denied"
    assert socket_calls == 0
    assert not manager.lock_held


def test_server_listen_failure_releases_newly_acquired_lock(
    tmp_path: Path,
) -> None:
    lock = _FakeLock(
        acquired=True,
        error=QLockFile.LockError.NoError,
    )
    server = _FakeServer(listening=False)
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        lock_factory=lambda path: cast(QLockFile, lock),
        server_factory=lambda parent: cast(QLocalServer, server),
    )

    result = manager.start()

    assert result.role is SingleInstanceRole.FAILED
    assert result.safe_code == "single_instance_server_listen_failed"
    assert lock.unlock_count == 1
    assert server.close_count == 1
    assert not manager.lock_held


def test_unreachable_owner_fails_closed_without_lock_takeover(
    tmp_path: Path,
) -> None:
    lock = _FakeLock(
        acquired=False,
        error=QLockFile.LockError.LockFailedError,
    )
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        ipc_timeout_ms=10,
        lock_factory=lambda path: cast(QLockFile, lock),
        socket_factory=lambda: cast(QLocalSocket, _UnreachableSocket()),
    )

    result = manager.start()

    assert result.role is SingleInstanceRole.FAILED
    assert result.safe_code == "single_instance_owner_unreachable"
    assert lock.unlock_count == 0
    assert not manager.lock_held


def test_ipc_permission_error_is_distinct_and_fails_closed(
    tmp_path: Path,
) -> None:
    lock = _FakeLock(
        acquired=False,
        error=QLockFile.LockError.LockFailedError,
    )
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        ipc_timeout_ms=10,
        lock_factory=lambda path: cast(QLockFile, lock),
        socket_factory=lambda: cast(
            QLocalSocket,
            _UnreachableSocket(
                QLocalSocket.LocalSocketError.SocketAccessError
            ),
        ),
    )

    result = manager.start()

    assert result.role is SingleInstanceRole.FAILED
    assert result.safe_code == "single_instance_ipc_permission_denied"
    assert not manager.lock_held


def test_server_factory_exception_is_sanitized_and_releases_lock(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive = "sk-test-never-use-this-value C:\\private\\server"
    lock = _FakeLock(
        acquired=True,
        error=QLockFile.LockError.NoError,
    )

    def server_factory(parent: QObject) -> QLocalServer:
        del parent
        raise RuntimeError(sensitive)

    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
        lock_factory=lambda path: cast(QLockFile, lock),
        server_factory=server_factory,
    )

    result = manager.start()
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            result.safe_code,
            repr(manager),
            captured.out,
            captured.err,
            caplog.text,
        )
    )

    assert result.safe_code == (
        "single_instance_server_initialization_failed"
    )
    assert sensitive not in visible
    assert "sk-test-never-use-this-value" not in visible
    assert "Traceback" not in captured.err
    assert lock.unlock_count == 1


@pytest.mark.parametrize(
    ("server_failures", "client_failures", "timer_failures"),
    [
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 1, 1),
    ],
)
def test_cleanup_failures_are_contained_retained_and_retryable(
    tmp_path: Path,
    server_failures: int,
    client_failures: int,
    timer_failures: int,
) -> None:
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
    )
    server = _FakeServer(
        listening=True,
        close_failures=server_failures,
    )
    lock = _FakeLock(
        acquired=True,
        error=QLockFile.LockError.NoError,
    )
    socket = _FakeCleanupSocket(abort_failures=client_failures)
    timer = _FakeCleanupTimer(stop_failures=timer_failures)
    _install_cleanup_fakes(
        manager,
        server=server,
        lock=lock,
        socket=socket,
        timer=timer,
    )

    manager.close()

    assert manager.cleanup_pending
    assert manager.cleanup_safe_code == "single_instance_cleanup_failed"
    assert not manager.released
    assert manager.active_client_count == int(
        client_failures > 0 or timer_failures > 0
    )

    manager.close()

    assert manager.released
    assert not manager.cleanup_pending
    assert manager.cleanup_safe_code == "none"
    assert manager.active_client_count == 0
    assert lock.unlock_count == 1


def test_lock_unlock_failure_does_not_report_released_until_retry(
    tmp_path: Path,
) -> None:
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
    )
    server = _FakeServer(listening=True)
    lock = _FakeLock(
        acquired=True,
        error=QLockFile.LockError.NoError,
        unlock_failures=1,
    )
    socket = _FakeCleanupSocket()
    timer = _FakeCleanupTimer()
    _install_cleanup_fakes(
        manager,
        server=server,
        lock=lock,
        socket=socket,
        timer=timer,
    )

    manager.close()

    assert manager.cleanup_pending
    assert manager.lock_held
    assert not manager.released
    assert lock.unlock_count == 1

    manager.close()

    assert manager.released
    assert not manager.lock_held
    assert lock.unlock_count == 2


def test_cleanup_exception_does_not_escape_qt_slot_or_block_exit_request(
    qt_application: QApplication,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del qt_application
    manager = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
    )
    server = _FakeServer(listening=True, close_failures=2)
    lock = _FakeLock(
        acquired=True,
        error=QLockFile.LockError.NoError,
        unlock_failures=2,
    )
    socket = _FakeCleanupSocket(abort_failures=2)
    timer = _FakeCleanupTimer(stop_failures=2)
    _install_cleanup_fakes(
        manager,
        server=server,
        lock=lock,
        socket=socket,
        timer=timer,
    )
    emitter = _CleanupEmitter()
    exit_requests = 0

    def request_exit() -> None:
        nonlocal exit_requests
        exit_requests += 1

    emitter.cleanup_requested.connect(manager.close)
    emitter.cleanup_requested.connect(request_exit)

    emitter.cleanup_requested.emit()
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            manager.cleanup_safe_code,
            repr(manager),
            captured.out,
            captured.err,
            caplog.text,
        )
    )

    assert exit_requests == 1
    assert manager.cleanup_pending
    assert manager.cleanup_safe_code == "single_instance_cleanup_failed"
    assert "controlled server cleanup failure" not in visible
    assert "controlled client cleanup failure" not in visible
    assert "controlled timer cleanup failure" not in visible
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "case_name",
    ["unknown", "repeated", "invalid", "overlong"],
)
def test_owner_rejects_invalid_wire_messages_without_activation(
    qt_application: QApplication,
    tmp_path: Path,
    case_name: str,
) -> None:
    del qt_application
    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
    )
    activation_count = 0

    def activated() -> None:
        nonlocal activation_count
        activation_count += 1

    owner.activation_requested.connect(activated)
    assert owner.start().role is SingleInstanceRole.OWNER

    exit_code, stdout, stderr = _run_probe(
        ["--raw-probe", owner.server_name, case_name]
    )

    assert exit_code == 0
    assert stdout.strip() == "raw_probe=rejected"
    assert stderr == ""
    assert activation_count == 0
    assert owner.last_ipc_safe_code == (
        "single_instance_activation_rejected"
    )
    owner.close()


def test_owner_marks_truncated_wire_message_without_activation(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    owner = SingleInstanceManager(
        tmp_path / "pet.lock",
        _namespace(),
    )
    activation_count = 0

    def activated() -> None:
        nonlocal activation_count
        activation_count += 1

    owner.activation_requested.connect(activated)
    assert owner.start().role is SingleInstanceRole.OWNER

    exit_code, stdout, stderr = _run_probe(
        ["--raw-probe", owner.server_name, "truncated"]
    )

    assert exit_code == 0
    assert stdout.strip() == "raw_probe=truncated_sent"
    assert stderr == ""
    assert _run_until(
        lambda: (
            owner.last_ipc_safe_code
            == "single_instance_message_truncated"
        )
    )
    assert activation_count == 0
    owner.close()


def test_concurrent_starters_produce_exactly_one_owner(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    lock_path = tmp_path / "pet.lock"
    server_name = _namespace()
    processes = [QProcess() for _ in range(3)]
    for process in processes:
        process.setProgram(sys.executable)
        process.setArguments(
            [
                str(_probe_path()),
                "--contender",
                str(lock_path),
                server_name,
                "2",
            ]
        )
        process.start()

    assert _run_until(
        lambda: all(
            process.state() is QProcess.ProcessState.NotRunning
            for process in processes
        ),
        timeout_ms=10_000,
    )
    outputs = [
        bytes(process.readAllStandardOutput().data()).decode("utf-8")
        for process in processes
    ]
    errors = [
        bytes(process.readAllStandardError().data()).decode("utf-8")
        for process in processes
    ]

    exit_codes = [process.exitCode() for process in processes]
    assert exit_codes == [0, 0, 0], (exit_codes, outputs, errors)
    assert errors == ["", "", ""]
    assert sum("contender_role=owner" in output for output in outputs) == 1
    assert sum(
        "contender_role=secondary safe_code=none" in output
        for output in outputs
    ) == 2


def test_abnormal_owner_exit_is_recovered_only_by_qlockfile(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    lock_path = tmp_path / "pet.lock"
    server_name = _namespace()
    process = QProcess()
    process.setProgram(sys.executable)
    process.setArguments(
        [
            str(_probe_path()),
            "--owner-hold",
            str(lock_path),
            server_name,
        ]
    )
    process.start()
    assert _run_until(lambda: process.bytesAvailable() > 0)
    assert (
        bytes(process.readAllStandardOutput().data()).decode("utf-8").strip()
        == "owner_hold=ready"
    )

    process.kill()
    assert _run_until(
        lambda: (
            process.state() is QProcess.ProcessState.NotRunning
        )
    )
    process.close()

    recovered = SingleInstanceManager(
        lock_path,
        server_name,
        stale_lock_time_ms=1,
    )
    assert recovered.stale_lock_time_ms == 1
    assert recovered.start().role is SingleInstanceRole.OWNER
    assert recovered.lock_held
    recovered.close()


def test_secondary_main_path_constructs_no_runtime_gui_or_tray(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        constructed.append("forbidden")
        raise AssertionError("Secondary startup crossed the instance gate.")

    monkeypatch.setattr(
        pet_application,
        "QApplication",
        lambda argv: _FakeApplication(),
    )
    monkeypatch.setattr(
        pet_application,
        "create_production_single_instance",
        lambda parent: _SecondaryOnlyManager(),
    )
    monkeypatch.setattr(
        pet_application,
        "ProductionQtRuntimeCompositionRoot",
        forbidden,
    )
    monkeypatch.setattr(
        pet_application,
        "create_production_autostart_service",
        forbidden,
    )
    monkeypatch.setattr(pet_application, "QtRuntimeBridge", forbidden)
    monkeypatch.setattr(pet_application, "MainWindow", forbidden)
    monkeypatch.setattr(pet_application, "PetWindow", forbidden)
    monkeypatch.setattr(
        pet_application,
        "create_production_pet_settings_controller",
        forbidden,
    )
    monkeypatch.setattr(
        pet_application,
        "SystemTrayController",
        forbidden,
    )

    exit_code = pet_application.main([])

    assert exit_code == 0
    assert constructed == []


def test_startup_owner_keeps_agent_hidden_and_starts_pet_and_tray(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class CallbackSignal:
        def connect(self, callback: object) -> None:
            del callback

    class OwnerManager:
        def __init__(self) -> None:
            self.activation_requested = CallbackSignal()

        def start(self) -> SingleInstanceResult:
            events.append("owner")
            return SingleInstanceResult(SingleInstanceRole.OWNER, "none")

        def set_closing_probe(self, probe: object) -> None:
            del probe

        def close(self) -> None:
            events.append("lock_close")

    class FakePet:
        def __init__(self, *, autostart_controller: object) -> None:
            del autostart_controller

        def show(self) -> None:
            events.append("pet")

    class FakeCoordinator:
        def __init__(
            self,
            bridge: object,
            main_window: object,
            pet_window: object,
            *,
            settings_controller: object,
        ) -> None:
            del bridge, main_window, pet_window
            events.append(
                getattr(settings_controller, "safe_code", "missing")
            )
            self.quit_requested = CallbackSignal()
            self.pet_closing = False

        def restore_pet_settings(self) -> None:
            events.append("restore")

        def attach_system_tray(self, tray: object) -> None:
            del tray
            events.append("tray")

        def show_pet(self) -> None:
            pass

    def fail_settings_factory() -> object:
        raise OSError("sk-test-never-use-this-value CredentialBlob")

    def create_runtime_root(path: object) -> object:
        del path
        events.append("runtime_root")
        return object()

    def create_bridge(
        root: object,
        *,
        autostart_service_factory: object,
    ) -> object:
        del root, autostart_service_factory
        events.append("bridge")
        return object()

    def create_main_window(
        bridge: object,
        hide_on_close: bool,
        *,
        autostart_controller: object,
    ) -> object:
        del bridge, hide_on_close, autostart_controller
        events.append("main")
        return object()

    def create_autostart_controller(
        bridge: object,
        parent: object,
    ) -> object:
        del bridge, parent
        events.append("autostart_controller")
        return object()

    fake_application = _FakeApplication()
    monkeypatch.setattr(
        pet_application,
        "QApplication",
        lambda argv: fake_application,
    )
    monkeypatch.setattr(
        pet_application,
        "create_production_single_instance",
        lambda parent: OwnerManager(),
    )
    monkeypatch.setattr(
        pet_application,
        "create_production_pet_settings_controller",
        fail_settings_factory,
    )
    monkeypatch.setattr(
        pet_application,
        "ProductionQtRuntimeCompositionRoot",
        create_runtime_root,
    )
    monkeypatch.setattr(
        pet_application,
        "QtRuntimeBridge",
        create_bridge,
    )
    monkeypatch.setattr(
        pet_application,
        "MainWindow",
        create_main_window,
    )
    monkeypatch.setattr(
        pet_application,
        "AutostartUiController",
        create_autostart_controller,
    )
    monkeypatch.setattr(pet_application, "PetWindow", FakePet)
    monkeypatch.setattr(
        pet_application,
        "PetApplicationCoordinator",
        FakeCoordinator,
    )
    monkeypatch.setattr(
        pet_application,
        "SystemTrayController",
        lambda coordinator, autostart_controller, parent: object(),
    )

    exit_code = pet_application.main(["SJTUClaw.exe", "--startup"])

    assert exit_code == 0
    assert events[:2] == ["owner", "runtime_root"]
    assert "pet_settings_initialization_failed" in events
    assert "bridge" in events
    assert "main" in events
    assert "pet" in events
    assert "tray" in events
    assert "provider" not in events
    assert "credential" not in events
    assert "network" not in events


def test_invalid_sensitive_payload_is_not_exposed(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive = (
        b"sk-test-never-use-this-value "
        b"C:\\private\\CredentialBlob\n"
    )

    result = classify_activation_message(sensitive)
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            result.value,
            captured.out,
            captured.err,
            caplog.text,
        )
    )

    assert result is ActivationMessageStatus.REJECT
    assert "sk-test-never-use-this-value" not in visible
    assert "CredentialBlob" not in visible
    assert "Traceback" not in captured.err


def test_single_instance_smoke_uses_isolated_two_process_boundary() -> None:
    environment = {
        **os.environ,
        "QT_QPA_PLATFORM": "invalid-parent-platform",
        "QT_QPA_FONTDIR": r"C:\Windows\Fonts",
    }

    result = subprocess.run(
        [sys.executable, str(_probe_path())],
        cwd=_probe_path().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "qt_single_instance_smoke=True" in result.stdout
    assert "owner_count=1" in result.stdout
    assert "secondary_count=1" in result.stdout
    assert "activation_count=1" in result.stdout
    assert "runtime_thread_count=1" in result.stdout
    assert "tray_count=1" in result.stdout
    assert "lock_released=True" in result.stdout
    assert "pending_asyncio_tasks=0" in result.stdout
    assert "unexpected_qt_warnings=0" in result.stdout
    assert "failed_checks=" in result.stdout
