from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import importlib
import json
import os
import struct
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dependency_walker_cache import (
    CACHE_RELATIVE_PATH,
    EXPECTED_FILES,
    validate_dependency_walker_cache,
)

SMOKE_RELATIVE_PATH = Path("build/dependency-walker-smoke")
PROBE_EXE_NAME = "probe.exe"
PROBE_DLL_NAME = "probe_dependency.dll"
MARKER_NAME = "probe_executed.marker"
OUTPUT_NAME = "probe.depends"
DWP_NAME = "probe.dwp"
STDOUT_NAME = "depends.stdout"
STDERR_NAME = "depends.stderr"
REPORT_NAME = "smoke_report.json"
EXECUTION_GUARD_NAME = "execution_started.marker"
TIMEOUT_SECONDS = 30.0
MAX_PROBE_BYTES = 2 * 1024 * 1024
PE_MACHINE_AMD64 = 0x8664
PE32_PLUS_MAGIC = 0x20B

REGISTRY_PATHS = (
    r"Software\Dependency Walker",
    r"Software\Microsoft\Dependency Walker",
    r"Software\Microsoft\DependencyWalker",
)

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_MSG_ACTIVE_PROCESS_LIMIT = 3
JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO = 4
JOB_OBJECT_MSG_NEW_PROCESS = 6
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INFINITE_PROCESS_EXIT_CODE = 259
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
KNOWN_DEPENDENCY_WALKER_EXIT_FLAGS = {
    0x00000200: "required_implicit_or_forwarded_dependency_not_found",
}


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    started: bool
    job_configured: bool
    active_process_limit: int
    kill_on_job_close: bool
    exit_code: int | None
    timed_out: bool
    child_process_count: int
    child_process_attempted: bool
    process_remaining: bool
    depends_dll_observed_loaded: bool
    stdout_sha256: str | None
    stdout_bytes: int
    stderr_sha256: str | None
    stderr_bytes: int
    safe_code: str


@dataclass(frozen=True, slots=True)
class SmokeOutcome:
    completed: bool
    safe_code: str
    report: Mapping[str, object]


class ProcessRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        working_directory: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> JobExecutionResult: ...


RegistrySnapshotter = Callable[[], Mapping[str, str | None]]
FileSnapshotter = Callable[[], Mapping[str, str]]
OutputParser = Callable[[Path], Sequence[str]]


class _IOCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobObjectAssociateCompletionPort(ctypes.Structure):
    _fields_ = [
        ("CompletionKey", ctypes.c_void_p),
        ("CompletionPort", wintypes.HANDLE),
    ]


class _JobObjectBasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _ModuleEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_digest_and_size(path: Path) -> tuple[str | None, int]:
    try:
        return _sha256_file(path), path.stat().st_size
    except OSError:
        return None, 0


def _probe_is_amd64_pe32_plus(path: Path) -> bool:
    try:
        if path.stat().st_size > MAX_PROBE_BYTES:
            return False
        with path.open("rb") as stream:
            header = stream.read(4096)
        if len(header) < 0x100 or header[:2] != b"MZ":
            return False
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        return (
            pe_offset + 26 <= len(header)
            and header[pe_offset : pe_offset + 4] == b"PE\x00\x00"
            and struct.unpack_from("<H", header, pe_offset + 4)[0]
            == PE_MACHINE_AMD64
            and struct.unpack_from("<H", header, pe_offset + 24)[0]
            == PE32_PLUS_MAGIC
        )
    except (OSError, struct.error):
        return False


def _validate_probe(smoke_directory: Path) -> bool:
    probe = smoke_directory / PROBE_EXE_NAME
    dependency = smoke_directory / PROBE_DLL_NAME
    try:
        probe_data = probe.read_bytes()
        return (
            probe.is_file()
            and dependency.is_file()
            and _probe_is_amd64_pe32_plus(probe)
            and _probe_is_amd64_pe32_plus(dependency)
            and PROBE_DLL_NAME.encode("ascii") in probe_data.lower()
            and not (smoke_directory / MARKER_NAME).exists()
        )
    except OSError:
        return False


def _atomic_write_text(path: Path, content: str) -> bool:
    if path.exists() or path.is_symlink():
        return False
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    created = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, path)
        created = False
        return True
    except OSError:
        return False
    finally:
        if created:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: object) -> bool:
    return _atomic_write_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _default_output_parser(path: Path) -> Sequence[str]:
    module = importlib.import_module("nuitka.freezer.DependsExe")
    parser = module.parseDependsExeOutput
    parsed = parser(os.fspath(path))
    return tuple(sorted(os.path.basename(item).casefold() for item in parsed))


def _registry_value_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (list, tuple)):
        return "\0".join(str(item) for item in value).encode(
            "utf-8",
            errors="replace",
        )
    return str(value).encode("utf-8", errors="replace")


def _hash_registry_key(winreg: Any, key: object) -> str:
    digest = hashlib.sha256()
    value_index = 0
    while True:
        try:
            name, value, value_type = winreg.EnumValue(key, value_index)
        except OSError:
            break
        digest.update(str(name).encode("utf-8", errors="replace"))
        digest.update(struct.pack("<I", int(value_type)))
        digest.update(_registry_value_bytes(value))
        value_index += 1
    subkeys: list[str] = []
    subkey_index = 0
    while True:
        try:
            subkeys.append(str(winreg.EnumKey(key, subkey_index)))
        except OSError:
            break
        subkey_index += 1
    for subkey_name in sorted(subkeys, key=str.casefold):
        digest.update(subkey_name.encode("utf-8", errors="replace"))
        with winreg.OpenKey(key, subkey_name) as subkey:
            digest.update(_hash_registry_key(winreg, subkey).encode("ascii"))
    return digest.hexdigest()


def _default_registry_snapshot() -> Mapping[str, str | None]:
    if sys.platform != "win32":
        return {path: None for path in REGISTRY_PATHS}
    import winreg

    result: dict[str, str | None] = {}
    for path in REGISTRY_PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                result[path] = _hash_registry_key(winreg, key)
        except FileNotFoundError:
            result[path] = None
        except OSError:
            result[path] = "unavailable"
    return result


def _default_file_snapshot(repository_root: Path) -> Mapping[str, str]:
    result: dict[str, str] = {}
    excluded_top = {".git", ".venv"}
    excluded_build = {
        "dependency-walker-smoke",
        "nuitka-cache",
        "tool-quarantine",
    }
    for current, directories, files in os.walk(repository_root):
        current_path = Path(current)
        try:
            relative_current = current_path.relative_to(repository_root)
        except ValueError:
            continue
        if not relative_current.parts:
            directories[:] = [
                name for name in directories if name not in excluded_top
            ]
        elif relative_current == Path("build"):
            directories[:] = [
                name for name in directories if name not in excluded_build
            ]
        directories[:] = [
            name
            for name in directories
            if not (current_path / name).is_symlink()
        ]
        for name in files:
            path = current_path / name
            if path.is_symlink():
                continue
            try:
                relative = path.relative_to(repository_root).as_posix()
                result[relative] = _sha256_file(path)
            except OSError:
                result[relative] = "unavailable"
    return result


def _exit_code_interpretation(exit_code: int | None) -> dict[str, object]:
    if exit_code is None:
        return {
            "raw": None,
            "set_bit_masks": [],
            "meaning": "process_exit_unavailable",
        }
    unsigned = exit_code & 0xFFFFFFFF
    bits = [
        f"0x{1 << index:08X}"
        for index in range(32)
        if unsigned & (1 << index)
    ]
    semantics = [
        {
            "mask": mask,
            "meaning": KNOWN_DEPENDENCY_WALKER_EXIT_FLAGS.get(
                int(mask, 16),
                "unclassified_dependency_walker_flag",
            ),
        }
        for mask in bits
    ]
    return {
        "raw": exit_code,
        "unsigned": unsigned,
        "set_bit_masks": bits,
        "set_bit_semantics": semantics,
        "meaning": (
            "no_dependency_walker_exit_flags"
            if not bits
            else "dependency_walker_bit_flags_present"
        ),
    }


def _safe_command_report() -> list[str]:
    return [
        "depends.exe",
        "-c",
        "-ot<smoke>/probe.depends",
        "-d:<smoke>/probe.dwp",
        "-f1",
        "-pa1",
        "-ps1",
        "<smoke>/probe.exe",
    ]


def _validate_command(command: Sequence[str]) -> bool:
    lowered = tuple(argument.casefold() for argument in command)
    return (
        len(command) == 8
        and lowered[1] == "-c"
        and lowered[4:] == ("-f1", "-pa1", "-ps1", lowered[7])
        and not any(
            argument == "-pb"
            or argument.startswith("-pb:")
            or argument == "/pb"
            or argument.startswith("/pb:")
            for argument in lowered
        )
    )


def run_dependency_walker_smoke(
    repository_root: Path,
    *,
    runner: ProcessRunner,
    registry_snapshotter: RegistrySnapshotter = _default_registry_snapshot,
    file_snapshotter: FileSnapshotter | None = None,
    output_parser: OutputParser = _default_output_parser,
) -> SmokeOutcome:
    root = repository_root.resolve(strict=True)
    smoke_directory = root / SMOKE_RELATIVE_PATH
    cache_directory = root / CACHE_RELATIVE_PATH
    report_path = smoke_directory / REPORT_NAME
    guard_path = smoke_directory / EXECUTION_GUARD_NAME
    if report_path.exists() or guard_path.exists():
        return SmokeOutcome(
            False,
            "dependency_walker_execution_already_attempted",
            {},
        )
    cache = validate_dependency_walker_cache(root)
    if not cache.completed:
        return SmokeOutcome(False, "dependency_walker_cache_invalid", {})
    if not _validate_probe(smoke_directory):
        return SmokeOutcome(False, "dependency_walker_probe_invalid", {})

    output_path = smoke_directory / OUTPUT_NAME
    dwp_path = smoke_directory / DWP_NAME
    stdout_path = smoke_directory / STDOUT_NAME
    stderr_path = smoke_directory / STDERR_NAME
    if any(
        path.exists() or path.is_symlink()
        for path in (output_path, dwp_path, stdout_path, stderr_path)
    ):
        return SmokeOutcome(False, "dependency_walker_smoke_occupied", {})

    command = (
        os.fspath(cache_directory / "depends.exe"),
        "-c",
        f"-ot{output_path}",
        f"-d:{dwp_path}",
        "-f1",
        "-pa1",
        "-ps1",
        os.fspath(smoke_directory / PROBE_EXE_NAME),
    )
    if not _validate_command(command):
        return SmokeOutcome(False, "dependency_walker_command_rejected", {})
    dwp_content = f"SxS\nUserDir {smoke_directory}\n"
    if not _atomic_write_text(dwp_path, dwp_content):
        return SmokeOutcome(False, "dependency_walker_dwp_write_failed", {})

    snapshot_files = file_snapshotter or (
        lambda: _default_file_snapshot(root)
    )
    try:
        registry_before = dict(registry_snapshotter())
        files_before = dict(snapshot_files())
    except Exception:
        return SmokeOutcome(
            False,
            "dependency_walker_snapshot_unavailable",
            {},
        )
    if (
        "unavailable" in registry_before.values()
        or "unavailable" in files_before.values()
    ):
        return SmokeOutcome(
            False,
            "dependency_walker_snapshot_unavailable",
            {},
        )
    if not _atomic_write_text(guard_path, "execution_started=True\n"):
        return SmokeOutcome(False, "dependency_walker_execution_guard_failed", {})

    environment = {
        "PATH": "",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        "TEMP": os.fspath(smoke_directory),
        "TMP": os.fspath(smoke_directory),
    }
    try:
        execution = runner.run(
            command,
            working_directory=smoke_directory,
            environment=environment,
            timeout_seconds=TIMEOUT_SECONDS,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except Exception:
        execution = _empty_execution_result(
            "dependency_walker_job_object_failed"
        )

    output_created = output_path.is_file()
    output_parsed = False
    parsed_dependencies: tuple[str, ...] = ()
    if output_created:
        try:
            parsed_dependencies = tuple(output_parser(output_path))
            output_parsed = True
        except Exception:
            output_parsed = False
    expected_dependency_found = (
        PROBE_DLL_NAME.casefold() in parsed_dependencies
    )
    probe_executed = (smoke_directory / MARKER_NAME).exists()
    try:
        registry_after = dict(registry_snapshotter())
        files_after = dict(snapshot_files())
    except Exception:
        registry_after = dict(registry_before)
        registry_after["snapshot"] = "unavailable"
        files_after = dict(files_before)
        files_after["snapshot"] = "unavailable"
    changed_registry = sorted(
        path
        for path in set(registry_before) | set(registry_after)
        if registry_before.get(path) != registry_after.get(path)
    )
    unexpected_files = sorted(
        path
        for path in set(files_before) | set(files_after)
        if files_before.get(path) != files_after.get(path)
    )
    post_cache = validate_dependency_walker_cache(root)
    cache_exe_hash_valid = (
        post_cache.completed
        and _sha256_file(cache_directory / "depends.exe")
        == EXPECTED_FILES["depends.exe"][1]
    )
    cache_dll_hash_valid = (
        post_cache.completed
        and _sha256_file(cache_directory / "depends.dll")
        == EXPECTED_FILES["depends.dll"][1]
    )
    success = all(
        (
            execution.started,
            execution.job_configured,
            execution.active_process_limit == 1,
            execution.kill_on_job_close,
            not execution.timed_out,
            execution.child_process_count == 0,
            not execution.child_process_attempted,
            not execution.process_remaining,
            not probe_executed,
            output_created,
            output_parsed,
            expected_dependency_found,
            not changed_registry,
            not unexpected_files,
            cache_exe_hash_valid,
            cache_dll_hash_valid,
        )
    )
    safe_code = (
        "standalone_build_authorization_required"
        if success
        else _select_failure_code(
            execution,
            probe_executed=probe_executed,
            output_created=output_created,
            output_parsed=output_parsed,
            expected_dependency_found=expected_dependency_found,
            registry_changed=bool(changed_registry),
            unexpected_files=bool(unexpected_files),
            post_hash_valid=cache_exe_hash_valid and cache_dll_hash_valid,
        )
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "dependency_walker_smoke": success,
        "safe_code": safe_code,
        "host_execution": execution.started,
        "windows_sandbox": False,
        "hard_network_isolation": False,
        "command_arguments": _safe_command_report(),
        "path_environment_empty": True,
        "stdin_closed": True,
        "timeout_seconds": TIMEOUT_SECONDS,
        "job_object": {
            "configured": execution.job_configured,
            "kill_on_job_close": execution.kill_on_job_close,
            "active_process_limit": execution.active_process_limit,
        },
        "exit_code": _exit_code_interpretation(execution.exit_code),
        "cache_exe_hash_valid": cache_exe_hash_valid,
        "cache_dll_hash_valid": cache_dll_hash_valid,
        "child_process_count": execution.child_process_count,
        "child_process_attempted": execution.child_process_attempted,
        "probe_executed": probe_executed,
        "output_created": output_created,
        "output_parsed": output_parsed,
        "expected_dependency_found": expected_dependency_found,
        "parsed_dependency_basenames": sorted(set(parsed_dependencies)),
        "registry_changed": bool(changed_registry),
        "changed_registry_paths": changed_registry,
        "registry_snapshot_scope": list(REGISTRY_PATHS),
        "unexpected_files": len(unexpected_files),
        "unexpected_file_paths": unexpected_files,
        "file_snapshot_scope": "repository_except_fixed_ignored_tool_directories",
        "process_timeout": execution.timed_out,
        "depends_process_remaining": execution.process_remaining,
        "depends_dll_observed_loaded": (
            execution.depends_dll_observed_loaded
        ),
        "post_execution_hash_valid": (
            cache_exe_hash_valid and cache_dll_hash_valid
        ),
        "stdout_sha256": execution.stdout_sha256,
        "stdout_bytes": execution.stdout_bytes,
        "stderr_sha256": execution.stderr_sha256,
        "stderr_bytes": execution.stderr_bytes,
        "raw_process_output_recorded": False,
        "network_accessed_by_harness": False,
        "credential_manager_accessed": False,
        "standalone_build_started": False,
    }
    if not _atomic_write_json(report_path, report):
        return SmokeOutcome(
            False,
            "dependency_walker_smoke_report_failed",
            report,
        )
    return SmokeOutcome(success, safe_code, report)


def _select_failure_code(
    execution: JobExecutionResult,
    *,
    probe_executed: bool,
    output_created: bool,
    output_parsed: bool,
    expected_dependency_found: bool,
    registry_changed: bool,
    unexpected_files: bool,
    post_hash_valid: bool,
) -> str:
    if not execution.job_configured or not execution.started:
        return execution.safe_code
    if execution.child_process_count or execution.child_process_attempted:
        return "dependency_walker_child_process_rejected"
    if execution.timed_out or execution.process_remaining:
        return "dependency_walker_process_timeout"
    if probe_executed:
        return "dependency_walker_probe_executed"
    if registry_changed:
        return "dependency_walker_registry_changed"
    if unexpected_files:
        return "dependency_walker_unexpected_file_change"
    if not output_created:
        return "dependency_walker_output_missing"
    if not output_parsed:
        return "dependency_walker_output_invalid"
    if not expected_dependency_found:
        return "dependency_walker_expected_dependency_missing"
    if not post_hash_valid:
        return "dependency_walker_post_hash_invalid"
    return execution.safe_code


class WindowsJobObjectRunner:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("windows_job_object_unavailable")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateIoCompletionPort.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.c_size_t,
            wintypes.DWORD,
        ]
        kernel32.CreateIoCompletionPort.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SecurityAttributes),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfo),
            ctypes.POINTER(_ProcessInformation),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetQueuedCompletionStatus.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.DWORD,
        ]
        kernel32.GetQueuedCompletionStatus.restype = wintypes.BOOL
        kernel32.Module32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ModuleEntry32),
        ]
        kernel32.Module32FirstW.restype = wintypes.BOOL
        kernel32.Module32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ModuleEntry32),
        ]
        kernel32.Module32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

    def _close(self, handle: int | None) -> None:
        if handle not in (None, 0, INVALID_HANDLE_VALUE):
            self._kernel32.CloseHandle(handle)

    def _create_inheritable_file(
        self,
        path: Path,
        access: int,
        creation_disposition: int,
    ) -> int:
        security = _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes),
            None,
            True,
        )
        handle = self._kernel32.CreateFileW(
            os.fspath(path),
            access,
            0x00000001,
            ctypes.byref(security),
            creation_disposition,
            0x00000080,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            raise OSError("standard_stream_unavailable")
        return int(handle)

    def _observe_module(self, process_id: int, expected: str) -> bool:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32,
            process_id,
        )
        if snapshot == INVALID_HANDLE_VALUE:
            return False
        try:
            entry = _ModuleEntry32()
            entry.dwSize = ctypes.sizeof(_ModuleEntry32)
            if not self._kernel32.Module32FirstW(
                snapshot,
                ctypes.byref(entry),
            ):
                return False
            while True:
                if str(entry.szModule).casefold() == expected.casefold():
                    return True
                if not self._kernel32.Module32NextW(
                    snapshot,
                    ctypes.byref(entry),
                ):
                    return False
        finally:
            self._close(int(snapshot))

    def _drain_job_messages(self, port: int) -> tuple[int, bool]:
        new_processes = 0
        active_limit = False
        for _ in range(128):
            message = wintypes.DWORD()
            completion_key = ctypes.c_size_t()
            overlapped = ctypes.c_void_p()
            completed = self._kernel32.GetQueuedCompletionStatus(
                port,
                ctypes.byref(message),
                ctypes.byref(completion_key),
                ctypes.byref(overlapped),
                0,
            )
            if not completed:
                break
            if message.value == JOB_OBJECT_MSG_NEW_PROCESS:
                new_processes += 1
            elif message.value == JOB_OBJECT_MSG_ACTIVE_PROCESS_LIMIT:
                active_limit = True
            elif message.value == JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO:
                continue
        return max(0, new_processes - 1), active_limit

    def run(
        self,
        command: Sequence[str],
        *,
        working_directory: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> JobExecutionResult:
        if not _validate_command(command):
            return _empty_execution_result(
                "dependency_walker_command_rejected"
            )
        kernel32 = self._kernel32
        job: int | None = None
        port: int | None = None
        process_handle: int | None = None
        thread_handle: int | None = None
        stdin_handle: int | None = None
        stdout_handle: int | None = None
        stderr_handle: int | None = None
        process_started = False
        timed_out = False
        process_remaining = False
        dll_observed = False
        exit_code: int | None = None
        child_count = 0
        child_attempted = False
        try:
            job_handle = kernel32.CreateJobObjectW(None, None)
            if not job_handle:
                return _empty_execution_result(
                    "dependency_walker_job_object_failed"
                )
            job = int(job_handle)
            port_handle = kernel32.CreateIoCompletionPort(
                INVALID_HANDLE_VALUE,
                None,
                0,
                1,
            )
            if not port_handle:
                return _empty_execution_result(
                    "dependency_walker_job_object_failed"
                )
            port = int(port_handle)
            association = _JobObjectAssociateCompletionPort(
                ctypes.c_void_p(1),
                port,
            )
            if not kernel32.SetInformationJobObject(
                job,
                7,
                ctypes.byref(association),
                ctypes.sizeof(association),
            ):
                return _empty_execution_result(
                    "dependency_walker_job_object_failed"
                )
            limits = _JobObjectExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            limits.BasicLimitInformation.ActiveProcessLimit = 1
            if not kernel32.SetInformationJobObject(
                job,
                9,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                return _empty_execution_result(
                    "dependency_walker_job_object_failed"
                )

            stdin_handle = self._create_inheritable_file(
                Path("NUL"),
                0x80000000,
                3,
            )
            stdout_handle = self._create_inheritable_file(
                stdout_path,
                0x40000000,
                1,
            )
            stderr_handle = self._create_inheritable_file(
                stderr_path,
                0x40000000,
                1,
            )
            startup = _StartupInfo()
            startup.cb = ctypes.sizeof(_StartupInfo)
            startup.dwFlags = STARTF_USESTDHANDLES
            startup.hStdInput = stdin_handle
            startup.hStdOutput = stdout_handle
            startup.hStdError = stderr_handle
            process_info = _ProcessInformation()
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(list(command))
            )
            environment_block = ctypes.create_unicode_buffer(
                "\0".join(
                    f"{key}={environment[key]}"
                    for key in sorted(environment, key=str.casefold)
                )
                + "\0\0"
            )
            created = kernel32.CreateProcessW(
                command[0],
                command_line,
                None,
                None,
                True,
                CREATE_SUSPENDED
                | CREATE_NO_WINDOW
                | CREATE_UNICODE_ENVIRONMENT,
                ctypes.cast(environment_block, ctypes.c_void_p),
                os.fspath(working_directory),
                ctypes.byref(startup),
                ctypes.byref(process_info),
            )
            if not created:
                return _empty_execution_result(
                    "dependency_walker_process_start_failed",
                    job_configured=True,
                )
            process_handle = int(process_info.hProcess)
            thread_handle = int(process_info.hThread)
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                kernel32.TerminateProcess(process_handle, 0xFFFFFFFF)
                return _empty_execution_result(
                    "dependency_walker_job_assignment_failed",
                    job_configured=True,
                )
            if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                kernel32.TerminateJobObject(job, 0xFFFFFFFF)
                return _empty_execution_result(
                    "dependency_walker_process_resume_failed",
                    job_configured=True,
                )
            process_started = True
            self._close(thread_handle)
            thread_handle = None
            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                wait_ms = max(1, min(25, int(remaining * 1000)))
                wait_result = kernel32.WaitForSingleObject(
                    process_handle,
                    wait_ms,
                )
                dll_observed = dll_observed or self._observe_module(
                    int(process_info.dwProcessId),
                    "depends.dll",
                )
                if wait_result == WAIT_OBJECT_0:
                    break
                if wait_result != WAIT_TIMEOUT:
                    timed_out = True
                    break
            if timed_out:
                kernel32.TerminateJobObject(job, 0xFFFFFFFF)
                process_remaining = (
                    kernel32.WaitForSingleObject(process_handle, 5000)
                    != WAIT_OBJECT_0
                )
            exit_value = wintypes.DWORD(INFINITE_PROCESS_EXIT_CODE)
            if (
                kernel32.GetExitCodeProcess(
                    process_handle,
                    ctypes.byref(exit_value),
                )
                and exit_value.value != INFINITE_PROCESS_EXIT_CODE
            ):
                exit_code = ctypes.c_int32(exit_value.value).value
            child_count, child_attempted = self._drain_job_messages(port)
            accounting = _JobObjectBasicAccountingInformation()
            if kernel32.QueryInformationJobObject(
                job,
                1,
                ctypes.byref(accounting),
                ctypes.sizeof(accounting),
                None,
            ):
                child_count = max(
                    child_count,
                    max(0, int(accounting.TotalProcesses) - 1),
                )
            self._close(stdin_handle)
            stdin_handle = None
            self._close(stdout_handle)
            stdout_handle = None
            self._close(stderr_handle)
            stderr_handle = None
            stdout_hash, stdout_bytes = _file_digest_and_size(stdout_path)
            stderr_hash, stderr_bytes = _file_digest_and_size(stderr_path)
            return JobExecutionResult(
                started=process_started,
                job_configured=True,
                active_process_limit=1,
                kill_on_job_close=True,
                exit_code=exit_code,
                timed_out=timed_out,
                child_process_count=child_count,
                child_process_attempted=child_attempted,
                process_remaining=process_remaining,
                depends_dll_observed_loaded=dll_observed,
                stdout_sha256=stdout_hash,
                stdout_bytes=stdout_bytes,
                stderr_sha256=stderr_hash,
                stderr_bytes=stderr_bytes,
                safe_code=(
                    "none"
                    if not timed_out
                    else "dependency_walker_process_timeout"
                ),
            )
        except OSError:
            return _empty_execution_result(
                "dependency_walker_job_object_failed"
            )
        finally:
            if job is not None:
                kernel32.TerminateJobObject(job, 0xFFFFFFFF)
            self._close(thread_handle)
            self._close(process_handle)
            self._close(stdin_handle)
            self._close(stdout_handle)
            self._close(stderr_handle)
            self._close(port)
            self._close(job)


def _empty_execution_result(
    safe_code: str,
    *,
    job_configured: bool = False,
) -> JobExecutionResult:
    return JobExecutionResult(
        started=False,
        job_configured=job_configured,
        active_process_limit=1 if job_configured else 0,
        kill_on_job_close=job_configured,
        exit_code=None,
        timed_out=False,
        child_process_count=0,
        child_process_attempted=False,
        process_remaining=False,
        depends_dll_observed_loaded=False,
        stdout_sha256=None,
        stdout_bytes=0,
        stderr_sha256=None,
        stderr_bytes=0,
        safe_code=safe_code,
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one bounded Dependency Walker host smoke."
    )
    parser.add_argument("--confirm-execution", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.confirm_execution:
        print("safe_code=dependency_walker_execution_disabled")
        return 0
    repository_root = Path(__file__).resolve().parents[1]
    try:
        runner = WindowsJobObjectRunner()
        outcome = run_dependency_walker_smoke(
            repository_root,
            runner=runner,
        )
    except Exception:
        print("safe_code=dependency_walker_smoke_failed")
        return 2
    report = outcome.report
    fields = {
        "dependency_walker_smoke": report.get(
            "dependency_walker_smoke",
            False,
        ),
        "cache_exe_hash_valid": report.get(
            "cache_exe_hash_valid",
            False,
        ),
        "cache_dll_hash_valid": report.get(
            "cache_dll_hash_valid",
            False,
        ),
        "child_process_count": report.get("child_process_count", 0),
        "probe_executed": report.get("probe_executed", False),
        "output_created": report.get("output_created", False),
        "output_parsed": report.get("output_parsed", False),
        "expected_dependency_found": report.get(
            "expected_dependency_found",
            False,
        ),
        "registry_changed": report.get("registry_changed", False),
        "unexpected_files": report.get("unexpected_files", 0),
        "process_timeout": report.get("process_timeout", False),
        "depends_process_remaining": report.get(
            "depends_process_remaining",
            False,
        ),
        "post_execution_hash_valid": report.get(
            "post_execution_hash_valid",
            False,
        ),
    }
    print(
        " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in fields.items()
        )
    )
    print(f"safe_code={outcome.safe_code}")
    return 0 if outcome.completed else 2


if __name__ == "__main__":
    sys.exit(main())
