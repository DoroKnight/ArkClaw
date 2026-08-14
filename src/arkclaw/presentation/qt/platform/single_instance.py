"""Single-instance ownership and fixed local activation protocol."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import (
    QLockFile,
    QObject,
    QStandardPaths,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_ACTIVATE_MESSAGE = b"ACTIVATE_PET_V1\n"
_ACK_MESSAGE = b"ACK_V1\n"
_BUSY_MESSAGE = b"BUSY_V1\n"
_REJECT_MESSAGE = b"REJECT_V1\n"
_MAX_MESSAGE_BYTES = 64
_DEFAULT_IPC_TIMEOUT_MS = 1_500
_DEFAULT_CLIENT_TIMEOUT_MS = 1_500
_DEFAULT_MAX_ACTIVE_CLIENTS = 8
_DEFAULT_STALE_LOCK_TIME_MS = 0
_PRODUCTION_SERVER_NAME = "ArkClaw.Pet.SingleInstance.V1"
_PRODUCTION_LOCK_FILENAME = "arkclaw-pet-v1.lock"

LockFileFactory = Callable[[str], QLockFile]
LocalServerFactory = Callable[[QObject], QLocalServer]
LocalSocketFactory = Callable[[], QLocalSocket]
ClientTimerFactory = Callable[[QObject], QTimer]


class SingleInstanceRole(Enum):
    OWNER = "owner"
    SECONDARY = "secondary"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SingleInstanceResult:
    role: SingleInstanceRole
    safe_code: str

    @property
    def exit_code(self) -> int:
        if self.role is SingleInstanceRole.OWNER:
            return 0
        if (
            self.role is SingleInstanceRole.SECONDARY
            and self.safe_code == "none"
        ):
            return 0
        return 2


class ActivationMessageStatus(Enum):
    INCOMPLETE = "incomplete"
    ACTIVATE = "activate"
    REJECT = "reject"


def classify_activation_message(
    payload: bytes,
    *,
    disconnected: bool = False,
) -> ActivationMessageStatus:
    """Classify a bounded, newline-terminated, fixed ASCII command."""

    if len(payload) > _MAX_MESSAGE_BYTES:
        return ActivationMessageStatus.REJECT
    if b"\n" not in payload:
        if disconnected:
            return ActivationMessageStatus.REJECT
        return ActivationMessageStatus.INCOMPLETE
    if payload.count(b"\n") != 1 or not payload.endswith(b"\n"):
        return ActivationMessageStatus.REJECT
    try:
        payload.decode("ascii")
    except UnicodeDecodeError:
        return ActivationMessageStatus.REJECT
    if payload == _ACTIVATE_MESSAGE:
        return ActivationMessageStatus.ACTIVATE
    return ActivationMessageStatus.REJECT


@dataclass(slots=True)
class _ClientSession:
    socket: QLocalSocket
    timer: QTimer
    buffer: bytearray
    terminal: bool = False
    cleanup_in_progress: bool = False
    timer_cleaned: bool = False
    socket_cleaned: bool = False


class SingleInstanceManager(QObject):
    """Hold the process lock and serve one fixed activation command."""

    activation_requested = Signal()

    def __init__(
        self,
        lock_file_path: Path,
        server_name: str,
        *,
        ipc_timeout_ms: int = _DEFAULT_IPC_TIMEOUT_MS,
        client_timeout_ms: int = _DEFAULT_CLIENT_TIMEOUT_MS,
        max_active_clients: int = _DEFAULT_MAX_ACTIVE_CLIENTS,
        stale_lock_time_ms: int = _DEFAULT_STALE_LOCK_TIME_MS,
        lock_factory: LockFileFactory = QLockFile,
        server_factory: LocalServerFactory = QLocalServer,
        socket_factory: LocalSocketFactory = QLocalSocket,
        timer_factory: ClientTimerFactory = QTimer,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if ipc_timeout_ms <= 0:
            raise ValueError("IPC timeout must be positive.")
        if client_timeout_ms <= 0:
            raise ValueError("Client timeout must be positive.")
        if max_active_clients <= 0:
            raise ValueError("Active client limit must be positive.")
        if stale_lock_time_ms < 0:
            raise ValueError("Stale lock time cannot be negative.")
        self._lock_file_path = lock_file_path
        self._server_name = server_name
        self._ipc_timeout_ms = ipc_timeout_ms
        self._client_timeout_ms = client_timeout_ms
        self._max_active_clients = max_active_clients
        self._stale_lock_time_ms = stale_lock_time_ms
        self._lock_factory = lock_factory
        self._server_factory = server_factory
        self._socket_factory = socket_factory
        self._timer_factory = timer_factory
        self._lock: QLockFile | None = None
        self._server: QLocalServer | None = None
        self._clients: dict[QLocalSocket, _ClientSession] = {}
        self._role: SingleInstanceRole | None = None
        self._result: SingleInstanceResult | None = None
        self._lock_held = False
        self._closed = False
        self._closing = False
        self._closing_probe: Callable[[], bool] = lambda: False
        self._last_ipc_safe_code = "none"
        self._cleanup_safe_code = "none"

    @property
    def role(self) -> SingleInstanceRole | None:
        return self._role

    @property
    def lock_held(self) -> bool:
        return self._lock_held

    @property
    def released(self) -> bool:
        return self._closed and not self._lock_held

    @property
    def stale_lock_time_ms(self) -> int:
        return self._stale_lock_time_ms

    @property
    def active_client_count(self) -> int:
        return len(self._clients)

    @property
    def cleanup_pending(self) -> bool:
        return self._closing and not self._closed

    @property
    def cleanup_safe_code(self) -> str:
        return self._cleanup_safe_code

    @property
    def last_ipc_safe_code(self) -> str:
        return self._last_ipc_safe_code

    @property
    def server_name(self) -> str:
        return self._server_name

    def set_closing_probe(self, probe: Callable[[], bool]) -> None:
        self._closing_probe = probe

    def start(self) -> SingleInstanceResult:
        if self._result is not None:
            return self._result
        try:
            self._lock_file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            lock = self._lock_factory(str(self._lock_file_path))
            self._lock = lock
            lock.setStaleLockTime(self._stale_lock_time_ms)
            acquired = lock.tryLock(0)
        except Exception:
            return self._finish_start(
                SingleInstanceRole.FAILED,
                "single_instance_lock_unavailable",
            )
        if acquired:
            self._lock_held = True
            return self._start_owner_server()
        error = lock.error()
        if error is QLockFile.LockError.LockFailedError:
            return self._notify_existing_owner()
        if error is QLockFile.LockError.PermissionError:
            return self._finish_start(
                SingleInstanceRole.FAILED,
                "single_instance_lock_permission_denied",
            )
        return self._finish_start(
            SingleInstanceRole.FAILED,
            "single_instance_lock_unavailable",
        )

    def _start_owner_server(self) -> SingleInstanceResult:
        try:
            server = self._server_factory(self)
            server.setSocketOptions(
                QLocalServer.SocketOption.UserAccessOption
            )
            server.setMaxPendingConnections(self._max_active_clients)
            server.newConnection.connect(self._accept_connections)
            listening = server.listen(self._server_name)
        except Exception:
            self._release_lock_after_start_failure()
            return self._finish_start(
                SingleInstanceRole.FAILED,
                "single_instance_server_initialization_failed",
            )
        if not listening:
            server.close()
            self._release_lock_after_start_failure()
            return self._finish_start(
                SingleInstanceRole.FAILED,
                "single_instance_server_listen_failed",
            )
        self._server = server
        return self._finish_start(SingleInstanceRole.OWNER, "none")

    def _notify_existing_owner(self) -> SingleInstanceResult:
        socket = self._socket_factory()
        try:
            if not self._connect_to_owner(socket):
                if (
                    socket.error()
                    is QLocalSocket.LocalSocketError.SocketAccessError
                ):
                    return self._finish_start(
                        SingleInstanceRole.FAILED,
                        "single_instance_ipc_permission_denied",
                    )
                return self._finish_start(
                    SingleInstanceRole.FAILED,
                    "single_instance_owner_unreachable",
                )
            if socket.write(_ACTIVATE_MESSAGE) != len(_ACTIVATE_MESSAGE):
                return self._finish_start(
                    SingleInstanceRole.FAILED,
                    "single_instance_activation_write_failed",
                )
            socket.flush()
            if socket.bytesToWrite() > 0:
                socket.waitForBytesWritten(self._ipc_timeout_ms)
            response = self._wait_for_response(socket)
        except Exception:
            return self._finish_start(
                SingleInstanceRole.FAILED,
                "single_instance_ipc_failed",
            )
        finally:
            socket.abort()
        if response == _ACK_MESSAGE:
            return self._finish_start(SingleInstanceRole.SECONDARY, "none")
        if response == _BUSY_MESSAGE:
            return self._finish_start(
                SingleInstanceRole.SECONDARY,
                "single_instance_owner_busy",
            )
        if response is None:
            return self._finish_start(
                SingleInstanceRole.FAILED,
                "single_instance_activation_timeout",
            )
        return self._finish_start(
            SingleInstanceRole.FAILED,
            "single_instance_activation_rejected",
        )

    def _connect_to_owner(self, socket: QLocalSocket) -> bool:
        deadline = time.monotonic() + (self._ipc_timeout_ms / 1_000)
        while True:
            socket.connectToServer(self._server_name)
            remaining_ms = round((deadline - time.monotonic()) * 1_000)
            if remaining_ms <= 0:
                return False
            if socket.waitForConnected(min(remaining_ms, 100)):
                return True
            socket.abort()
            remaining_ms = round((deadline - time.monotonic()) * 1_000)
            if remaining_ms <= 0:
                return False
            QThread.msleep(min(25, remaining_ms))

    def _wait_for_response(self, socket: QLocalSocket) -> bytes | None:
        deadline = time.monotonic() + (self._ipc_timeout_ms / 1_000)
        response = bytearray()
        while b"\n" not in response:
            if socket.bytesAvailable() > 0:
                response.extend(socket.readAll().data())
                if len(response) > _MAX_MESSAGE_BYTES:
                    return bytes(response)
                continue
            remaining_ms = round((deadline - time.monotonic()) * 1_000)
            if remaining_ms <= 0:
                return None
            if not socket.waitForReadyRead(remaining_ms):
                if socket.bytesAvailable() > 0:
                    continue
                return None
        return bytes(response)

    def _finish_start(
        self,
        role: SingleInstanceRole,
        safe_code: str,
    ) -> SingleInstanceResult:
        result = SingleInstanceResult(role=role, safe_code=safe_code)
        self._role = role
        self._result = result
        return result

    def _release_lock_after_start_failure(self) -> None:
        lock = self._lock
        if lock is None or not self._lock_held:
            return
        try:
            lock.unlock()
        except Exception:
            return
        self._lock_held = False

    @Slot()
    def _accept_connections(self) -> None:
        server = self._server
        if server is None or self._closing:
            return
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if len(self._clients) >= self._max_active_clients:
                self._last_ipc_safe_code = (
                    "single_instance_client_limit_reached"
                )
                self._reject_untracked_client(socket)
                continue
            socket.setReadBufferSize(_MAX_MESSAGE_BYTES + 1)
            timer = self._timer_factory(self)
            timer.setSingleShot(True)
            session = _ClientSession(
                socket=socket,
                timer=timer,
                buffer=bytearray(),
            )
            self._clients[socket] = session
            socket.readyRead.connect(
                lambda current=socket: self._read_client(current)
            )
            socket.disconnected.connect(
                lambda current=socket: self._drop_client(current)
            )
            timer.timeout.connect(
                lambda current=socket: self._expire_client(current)
            )
            timer.start(self._client_timeout_ms)
            if socket.bytesAvailable() > 0:
                self._read_client(socket)

    def _read_client(self, socket: QLocalSocket) -> None:
        session = self._clients.get(socket)
        if session is None or session.terminal:
            return
        session.buffer.extend(socket.readAll().data())
        status = classify_activation_message(bytes(session.buffer))
        if status is ActivationMessageStatus.INCOMPLETE:
            return
        if status is ActivationMessageStatus.REJECT:
            self._last_ipc_safe_code = (
                "single_instance_activation_rejected"
            )
            self._finish_client(socket, response=_REJECT_MESSAGE)
            return
        try:
            closing = self._closing_probe()
        except Exception:
            closing = True
        if closing:
            self._last_ipc_safe_code = "single_instance_owner_busy"
            self._finish_client(socket, response=_BUSY_MESSAGE)
            return
        self._last_ipc_safe_code = "none"
        self._finish_client(socket, response=_ACK_MESSAGE)
        QTimer.singleShot(0, self.activation_requested.emit)

    def _respond(self, socket: QLocalSocket, response: bytes) -> None:
        socket.write(response)
        socket.flush()
        socket.disconnectFromServer()

    def _finish_client(
        self,
        socket: QLocalSocket,
        *,
        response: bytes | None = None,
        abort_socket: bool = False,
    ) -> None:
        session = self._clients.get(socket)
        if session is None:
            return
        session.terminal = True
        if response is not None:
            try:
                self._respond(socket, response)
            except Exception:
                abort_socket = True
                self._cleanup_safe_code = "single_instance_cleanup_failed"
        self._cleanup_client_session(
            session,
            abort_socket=abort_socket,
        )

    def _cleanup_client_session(
        self,
        session: _ClientSession,
        *,
        abort_socket: bool,
    ) -> bool:
        if session.cleanup_in_progress:
            return True
        session.cleanup_in_progress = True
        failed = False
        try:
            if not session.timer_cleaned:
                try:
                    session.timer.stop()
                    session.timer.deleteLater()
                except Exception:
                    failed = True
                else:
                    session.timer_cleaned = True
            if not session.socket_cleaned:
                try:
                    if abort_socket:
                        session.socket.abort()
                    session.socket.deleteLater()
                except Exception:
                    failed = True
                else:
                    session.socket_cleaned = True
            if session.timer_cleaned and session.socket_cleaned:
                self._clients.pop(session.socket, None)
        finally:
            session.cleanup_in_progress = False
        if failed:
            self._cleanup_safe_code = "single_instance_cleanup_failed"
        return not failed

    def _expire_client(self, socket: QLocalSocket) -> None:
        session = self._clients.get(socket)
        if session is None or session.terminal:
            return
        session.terminal = True
        session.timer.stop()
        self._last_ipc_safe_code = "single_instance_client_timeout"
        QTimer.singleShot(
            0,
            lambda current=socket: self._finish_client(
                current,
                abort_socket=True,
            ),
        )

    def _drop_client(self, socket: QLocalSocket) -> None:
        session = self._clients.get(socket)
        if session is None:
            return
        if session.buffer and not session.terminal:
            status = classify_activation_message(
                bytes(session.buffer),
                disconnected=True,
            )
            if status is ActivationMessageStatus.REJECT:
                self._last_ipc_safe_code = (
                    "single_instance_message_truncated"
                )
        self._cleanup_client_session(session, abort_socket=False)

    def _reject_untracked_client(self, socket: QLocalSocket) -> None:
        try:
            self._respond(socket, _REJECT_MESSAGE)
        except Exception:
            try:
                socket.abort()
            except Exception:
                self._cleanup_safe_code = (
                    "single_instance_cleanup_failed"
                )
        try:
            socket.deleteLater()
        except Exception:
            self._cleanup_safe_code = "single_instance_cleanup_failed"

    @Slot()
    def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        failed = False
        server = self._server
        if server is not None:
            try:
                server.close()
            except Exception:
                failed = True
            else:
                self._server = None
        for session in tuple(self._clients.values()):
            if not self._cleanup_client_session(
                session,
                abort_socket=True,
            ):
                failed = True
        lock = self._lock
        if (
            self._server is None
            and not self._clients
            and lock is not None
            and self._lock_held
        ):
            try:
                lock.unlock()
            except Exception:
                failed = True
            else:
                self._lock_held = False
        self._closed = (
            self._server is None
            and not self._clients
            and not self._lock_held
        )
        if failed or not self._closed:
            self._cleanup_safe_code = "single_instance_cleanup_failed"
        else:
            self._cleanup_safe_code = "none"


def create_production_single_instance(
    parent: QObject | None = None,
) -> SingleInstanceManager:
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    lock_file_path = Path(location) / _PRODUCTION_LOCK_FILENAME
    return SingleInstanceManager(
        lock_file_path,
        _PRODUCTION_SERVER_NAME,
        parent=parent,
    )
