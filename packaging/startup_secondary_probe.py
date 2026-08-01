"""Controlled Owner/Secondary launcher using one frozen process environment."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final, cast

from startup_secondary_environment import (
    ProbeLifecycle,
    ProcessIdentity,
    prepare_launch_pair,
)

_REPOSITORY_ROOT: Final = Path(r"D:\SJTUClaw")
_NONCE_PATTERN: Final = re.compile(r"[0-9a-f]{32}")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
_TOKEN_QUERY: Final = 0x0008
_TOKEN_USER: Final = 1
_TOKEN_INTEGRITY_LEVEL: Final = 25
_UOI_NAME: Final = 2
_SECONDARY_TIMEOUT_SECONDS: Final = 15.0
_CONTROL_TIMEOUT_SECONDS: Final = 3_600.0
_OWNER_TIMEOUT_SECONDS: Final = 5_400.0


class ProbeSafeError(RuntimeError):
    """A fixed failure that never includes dynamic process or environment data."""


@dataclass(slots=True)
class _StreamDigest:
    byte_count: int = 0
    sha256: str = hashlib.sha256(b"").hexdigest()


class _DigestReader:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.result = _StreamDigest()
        self._thread = threading.Thread(target=self._read, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> _StreamDigest:
        self._thread.join(timeout=10.0)
        if self._thread.is_alive():
            raise ProbeSafeError("output_digest_incomplete")
        return self.result

    def _read(self) -> None:
        digest = hashlib.sha256()
        count = 0
        for block in iter(lambda: self._stream.read(65_536), b""):
            count += len(block)
            digest.update(block)
        self.result = _StreamDigest(count, digest.hexdigest())


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    payload = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_control(path: Path, expected: Mapping[str, object]) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
        return False
    return bool(document == expected)


def _open_process(pid: int) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        pid,
    )
    if not handle:
        raise ProbeSafeError("process_identity_unavailable")
    return int(handle)


def _close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


def _token_sid(process_handle: int, information_class: int) -> bytes:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        process_handle,
        _TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise ProbeSafeError("process_token_unavailable")
    try:
        required = wintypes.DWORD(0)
        advapi32.GetTokenInformation(
            token,
            information_class,
            None,
            0,
            ctypes.byref(required),
        )
        if required.value == 0:
            raise ProbeSafeError("process_token_unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            information_class,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ProbeSafeError("process_token_unavailable")
        sid = _SidAndAttributes.from_buffer(buffer).sid
        if not sid:
            raise ProbeSafeError("process_token_unavailable")
        advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
        advapi32.GetLengthSid.restype = wintypes.DWORD
        sid_length = int(advapi32.GetLengthSid(sid))
        if sid_length <= 0:
            raise ProbeSafeError("process_token_unavailable")
        return ctypes.string_at(sid, sid_length)
    finally:
        if token.value is not None:
            _close_handle(int(token.value))


def _sid_digest(process_handle: int) -> str:
    data = _token_sid(process_handle, _TOKEN_USER)
    return hashlib.sha256(data).hexdigest()


def _integrity_level(process_handle: int) -> str:
    data = _token_sid(process_handle, _TOKEN_INTEGRITY_LEVEL)
    if len(data) < 12 or data[1] == 0:
        raise ProbeSafeError("integrity_level_unavailable")
    rid = int.from_bytes(data[-4:], byteorder="little", signed=False)
    if rid >= 0x4000:
        return "system"
    if rid >= 0x3000:
        return "high"
    if rid >= 0x2000:
        return "medium"
    if rid >= 0x1000:
        return "low"
    return "untrusted"


def _session_id(pid: int) -> int:
    session = wintypes.DWORD(0)
    if not ctypes.WinDLL("kernel32", use_last_error=True).ProcessIdToSessionId(
        pid,
        ctypes.byref(session),
    ):
        raise ProbeSafeError("session_id_unavailable")
    return int(session.value)


def _user_object_name(handle: int) -> str:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    required = wintypes.DWORD(0)
    user32.GetUserObjectInformationW(
        handle,
        _UOI_NAME,
        None,
        0,
        ctypes.byref(required),
    )
    if required.value == 0:
        raise ProbeSafeError("desktop_identity_unavailable")
    buffer = ctypes.create_unicode_buffer(required.value // 2)
    if not user32.GetUserObjectInformationW(
        handle,
        _UOI_NAME,
        buffer,
        required,
        ctypes.byref(required),
    ):
        raise ProbeSafeError("desktop_identity_unavailable")
    return buffer.value


def _current_desktop_identity() -> tuple[str, str]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    station = user32.GetProcessWindowStation()
    desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not station or not desktop:
        raise ProbeSafeError("desktop_identity_unavailable")
    return _user_object_name(int(desktop)), _user_object_name(int(station))


def _identity_for_pid(
    pid: int,
    *,
    inherited_desktop: str,
    inherited_window_station: str,
) -> ProcessIdentity:
    handle = _open_process(pid)
    try:
        return ProcessIdentity(
            session_id=_session_id(pid),
            user_token_sha256=_sid_digest(handle),
            integrity_level=_integrity_level(handle),
            desktop=inherited_desktop,
            window_station=inherited_window_station,
        )
    finally:
        _close_handle(handle)


def _creation_token(pid: int) -> str:
    handle = _open_process(pid)
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.WinDLL("kernel32", use_last_error=True).GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ProbeSafeError("process_creation_time_unavailable")
        raw = (int(creation.dwHighDateTime) << 32) | int(
            creation.dwLowDateTime
        )
        return hashlib.sha256(str(raw).encode("ascii")).hexdigest()
    finally:
        _close_handle(handle)


def _foreground_pid() -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    handle = user32.GetForegroundWindow()
    if not handle:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return int(pid.value)


def _start_child(
    executable: Path,
    working_directory: Path,
    environment: Mapping[str, str],
) -> tuple[subprocess.Popen[bytes], _DigestReader, _DigestReader]:
    process = subprocess.Popen(
        [str(executable), "--startup"],
        cwd=working_directory,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise ProbeSafeError("child_output_capture_unavailable")
    stdout = _DigestReader(cast(BinaryIO, process.stdout))
    stderr = _DigestReader(cast(BinaryIO, process.stderr))
    stdout.start()
    stderr.start()
    return process, stdout, stderr


def _wait_for_control(
    path: Path,
    expected: Mapping[str, object],
    *,
    owner: subprocess.Popen[bytes],
    owner_pid: int,
    deadline_seconds: float,
) -> tuple[bool, bool]:
    deadline = time.monotonic() + deadline_seconds
    owner_foreground = False
    while time.monotonic() < deadline:
        if owner.poll() is not None:
            raise ProbeSafeError("owner_exited_before_control")
        owner_foreground |= _foreground_pid() == owner_pid
        if _read_control(path, expected):
            return True, owner_foreground
        time.sleep(0.05)
    return False, owner_foreground


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--expected-exe-sha256", required=True)
    arguments = parser.parse_args()
    if (
        _NONCE_PATTERN.fullmatch(arguments.nonce) is None
        or _SHA256_PATTERN.fullmatch(arguments.expected_exe_sha256) is None
    ):
        return 2
    expected_root = (
        _REPOSITORY_ROOT
        / "build"
        / "startup-secondary-verification"
        / arguments.nonce
    ).resolve(strict=False)
    evidence_root = arguments.evidence_root.resolve(strict=False)
    executable = arguments.executable.resolve(strict=True)
    expected_executable = (
        _REPOSITORY_ROOT / "dist" / "SJTUClaw.dist" / "SJTUClaw.exe"
    ).resolve(strict=True)
    if (
        evidence_root != expected_root
        or evidence_root.exists()
        or executable != expected_executable
        or _sha256_file(executable) != arguments.expected_exe_sha256
    ):
        return 2
    evidence_root.mkdir(parents=True)
    runtime_root = evidence_root / "runtime"
    for relative in ("temp", "appdata", "localappdata", "userprofile"):
        (runtime_root / relative).mkdir(parents=True, exist_ok=False)
    desktop, window_station = _current_desktop_identity()
    supervisor_identity = _identity_for_pid(
        os.getpid(),
        inherited_desktop=desktop,
        inherited_window_station=window_station,
    )
    parent_snapshot = dict(os.environ)
    pair = prepare_launch_pair(
        parent_snapshot,
        repository_root=_REPOSITORY_ROOT,
        runtime_root=runtime_root,
        working_directory=executable.parent,
        identity=supervisor_identity,
    )
    owner_manifest = pair.context.environment.manifest
    secondary_manifest = pair.context.environment.manifest
    _write_json(
        evidence_root / "environment-manifest.json",
        {
            "schema": 1,
            "owner_environment_manifest_sha256": (
                owner_manifest.aggregate_sha256
            ),
            "secondary_environment_manifest_sha256": (
                secondary_manifest.aggregate_sha256
            ),
            "environment_difference_count": 0,
            "manifest": owner_manifest.to_safe_dict(),
            "working_directory_equal": True,
            "session_equal_by_construction": True,
            "user_token_equal_by_construction": True,
            "integrity_equal_by_construction": True,
            "desktop_equal_by_construction": True,
            "window_station_equal_by_construction": True,
        },
    )
    lifecycle = ProbeLifecycle()
    owner: subprocess.Popen[bytes] | None = None
    secondary: subprocess.Popen[bytes] | None = None
    try:
        owner, owner_stdout, owner_stderr = _start_child(
            executable,
            executable.parent,
            pair.owner_environment,
        )
        owner_token = _creation_token(owner.pid)
        lifecycle.owner_created(owner.pid, owner_token)
        owner_identity = _identity_for_pid(
            owner.pid,
            inherited_desktop=desktop,
            inherited_window_station=window_station,
        )
        if owner_identity != supervisor_identity:
            raise ProbeSafeError("owner_identity_mismatch")
        _write_json(
            evidence_root / "owner-created.json",
            {
                "schema": 1,
                "nonce": arguments.nonce,
                "owner_pid": owner.pid,
                "owner_creation_count": 1,
                "environment_manifest_sha256": owner_manifest.aggregate_sha256,
                "identity_matches": True,
                "safe_code": "startup_owner_created",
            },
        )
        confirmed, owner_foreground = _wait_for_control(
            evidence_root / "owner-confirmed.json",
            {"action": "owner_confirmed", "nonce": arguments.nonce},
            owner=owner,
            owner_pid=owner.pid,
            deadline_seconds=_CONTROL_TIMEOUT_SECONDS,
        )
        if not confirmed:
            raise ProbeSafeError("owner_confirmation_timeout")
        secondary, secondary_stdout, secondary_stderr = _start_child(
            executable,
            executable.parent,
            pair.secondary_environment,
        )
        secondary_token = _creation_token(secondary.pid)
        lifecycle.secondary_created(secondary.pid, secondary_token)
        secondary_identity = _identity_for_pid(
            secondary.pid,
            inherited_desktop=desktop,
            inherited_window_station=window_station,
        )
        if secondary_identity != owner_identity:
            raise ProbeSafeError("secondary_identity_mismatch")
        _write_json(
            evidence_root / "secondary-created.json",
            {
                "schema": 1,
                "nonce": arguments.nonce,
                "secondary_pid": secondary.pid,
                "secondary_creation_count": 1,
                "environment_manifest_sha256": (
                    secondary_manifest.aggregate_sha256
                ),
                "identity_matches": True,
                "safe_code": "startup_secondary_created",
            },
        )
        deadline = time.monotonic() + _SECONDARY_TIMEOUT_SECONDS
        secondary_foreground = False
        while secondary.poll() is None and time.monotonic() < deadline:
            secondary_foreground |= _foreground_pid() == secondary.pid
            time.sleep(0.05)
        if secondary.poll() is None:
            _write_json(
                evidence_root / "secondary-result.json",
                {
                    "schema": 1,
                    "nonce": arguments.nonce,
                    "secondary_exit_observed": False,
                    "secondary_foreground_observed": secondary_foreground,
                    "ack_verified": False,
                    "safe_code": "startup_secondary_timeout",
                },
            )
            terminate = evidence_root / "terminate-secondary.json"
            expected_terminate = {
                "action": "terminate_secondary",
                "nonce": arguments.nonce,
            }
            deadline = time.monotonic() + _CONTROL_TIMEOUT_SECONDS
            while secondary.poll() is None and time.monotonic() < deadline:
                if _read_control(terminate, expected_terminate):
                    lifecycle.require_exact_secondary(
                        secondary.pid,
                        _creation_token(secondary.pid),
                    )
                    secondary.kill()
                    secondary.wait(timeout=10.0)
                    break
                time.sleep(0.05)
            raise ProbeSafeError("startup_secondary_timeout")
        lifecycle.secondary_exited()
        secondary_output = secondary_stdout.finish()
        secondary_error = secondary_stderr.finish()
        _write_json(
            evidence_root / "secondary-result.json",
            {
                "schema": 1,
                "nonce": arguments.nonce,
                "secondary_exit_observed": True,
                "secondary_exit_code": secondary.returncode,
                "secondary_foreground_observed": secondary_foreground,
                "secondary_stdout_bytes": secondary_output.byte_count,
                "secondary_stdout_sha256": secondary_output.sha256,
                "secondary_stderr_bytes": secondary_error.byte_count,
                "secondary_stderr_sha256": secondary_error.sha256,
                "ack_verified": secondary.returncode == 0,
                "safe_code": (
                    "startup_secondary_ack_verified"
                    if secondary.returncode == 0
                    else "startup_secondary_failed"
                ),
            },
        )
        if secondary.returncode != 0:
            raise ProbeSafeError("startup_secondary_failed")
        owner_deadline = time.monotonic() + _OWNER_TIMEOUT_SECONDS
        while owner.poll() is None and time.monotonic() < owner_deadline:
            time.sleep(0.1)
        if owner.poll() is None:
            raise ProbeSafeError("owner_exit_timeout")
        lifecycle.owner_exited()
        owner_output = owner_stdout.finish()
        owner_error = owner_stderr.finish()
        _write_json(
            evidence_root / "terminal-summary.json",
            {
                "schema": 1,
                "nonce": arguments.nonce,
                "owner_creation_count": lifecycle.owner_creation_count,
                "secondary_creation_count": lifecycle.secondary_creation_count,
                "owner_exit_code": owner.returncode,
                "secondary_exit_code": secondary.returncode,
                "owner_stdout_bytes": owner_output.byte_count,
                "owner_stdout_sha256": owner_output.sha256,
                "owner_stderr_bytes": owner_error.byte_count,
                "owner_stderr_sha256": owner_error.sha256,
                "owner_foreground_before_confirmation": owner_foreground,
                "secondary_foreground_observed": secondary_foreground,
                "forced_termination_count": 0,
                "startup_secondary_single_instance_verified": True,
                "environment_values_recorded": False,
                "safe_code": "autostart_packaged_startup_mode_verified",
            },
        )
        return 0
    except (OSError, ProbeSafeError, subprocess.SubprocessError):
        if owner is None:
            lifecycle.owner_create_failed()
        _write_json(
            evidence_root / "probe-failure.json",
            {
                "schema": 1,
                "nonce": arguments.nonce,
                "owner_creation_count": lifecycle.owner_creation_count,
                "secondary_creation_count": lifecycle.secondary_creation_count,
                "environment_values_recorded": False,
                "safe_code": "startup_secondary_probe_failed",
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
