from __future__ import annotations

import argparse
import configparser
import contextlib
import ctypes
import hashlib
import importlib.metadata as importlib_metadata
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as element_tree
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from dependency_walker_cache import validate_dependency_walker_cache

BUILD_RELATIVE_PATH = Path("build/windows-standalone")
THIRD_BUILD_TEMP_RELATIVE_PATH = Path(
    "build/standalone-third-build-temp"
)
RAW_DIST_RELATIVE_PATH = Path("packaging/deployment/pet_entry.dist")
FINAL_DIST_RELATIVE_PATH = Path("dist/ArkClaw.dist")
TRACKED_SPEC_RELATIVE_PATH = Path("packaging/pysidedeploy.spec")
BUILD_SPEC_NAME = "pysidedeploy.spec"
REPORT_NAME = "compilation-report.xml"
BUILD_REPORT_NAME = "build_report.json"
STDOUT_NAME = "pyside6-deploy.stdout.log"
STDERR_NAME = "pyside6-deploy.stderr.log"
ATTEMPT_GUARD_NAME = "build_attempt_started.marker"
DRY_RUN_WORKSPACE_RELATIVE_PATH = Path("build/standalone-dry-run")
DRY_RUN_INPUT_RELATIVE_PATH = Path("input/pet_entry.py")
DRY_RUN_SPEC_NAME = "pysidedeploy.spec"
DRY_RUN_REPORT_NAME = "compilation-report.xml"
DRY_RUN_STDOUT_NAME = "pyside6-deploy.stdout.log"
DRY_RUN_STDERR_NAME = "pyside6-deploy.stderr.log"
DRY_RUN_SNAPSHOT_NAME = "protected_snapshot_before.json"
PRODUCTION_ENTRY_RELATIVE_PATH = Path("packaging/pet_entry.py")
PROTECTED_ARTIFACT_RELATIVE_PATHS = (
    Path("dist"),
    Path("packaging/deployment"),
    BUILD_RELATIVE_PATH,
)
FIXED_QT_PLUGINS = ("platforms", "styles")
TIMEOUT_SECONDS = 90.0 * 60.0
ACTIVE_PROCESS_LIMIT = 128
MINIMUM_FREE_BYTES = 12 * 1024**3
PE_MACHINE_AMD64 = 0x8664
PE32_PLUS_MAGIC = 0x20B
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2
MAX_REPORT_BYTES = 64 * 1024 * 1024
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_MSG_ACTIVE_PROCESS_LIMIT = 3
JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO = 4
JOB_OBJECT_MSG_NEW_PROCESS = 6
JOB_OBJECT_MSG_EXIT_PROCESS = 7
JOB_OBJECT_MSG_ABNORMAL_EXIT_PROCESS = 8
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
STILL_ACTIVE = 259
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
TH32CS_SNAPPROCESS = 0x00000002

_SENSITIVE_ENVIRONMENT_MARKERS = (
    "API_KEY",
    "APIKEY",
    "AUTHORIZATION",
    "BEARER",
    "COOKIE",
    "CREDENTIAL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_BUILD_PROCESS_NAMES = frozenset(
    {
        "cl.exe",
        "depends.exe",
        "link.exe",
        "nuitka.cmd",
        "nuitka.exe",
        "pyside6-deploy.exe",
        "python.exe",
        "pythonw.exe",
    }
)


@dataclass(frozen=True, slots=True)
class BuildExecutionResult:
    started: bool
    job_configured: bool
    active_process_limit: int
    kill_on_job_close: bool
    exit_code: int | None
    timed_out: bool
    process_remaining: bool
    active_process_limit_hit: bool
    total_processes: int
    peak_active_processes: int
    stdout_sha256: str | None
    stdout_bytes: int
    stderr_sha256: str | None
    stderr_bytes: int
    safe_code: str


@dataclass(frozen=True, slots=True)
class BuildOutcome:
    completed: bool
    safe_code: str
    report: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DryRunWorkspaceOutcome:
    completed: bool
    safe_code: str


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
    ) -> BuildExecutionResult: ...


DiskFreeReader = Callable[[Path], int]
ProcessSnapshotter = Callable[[], Mapping[int, str]]
Clock = Callable[[], float]
EnvironmentValidator = Callable[[Path], bool]


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


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_digest_and_size(path: Path) -> tuple[str | None, int]:
    try:
        return _sha256_file(path), path.stat().st_size
    except OSError:
        return None, 0


def _utc_timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _default_disk_free(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def _is_sensitive_environment_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in _SENSITIVE_ENVIRONMENT_MARKERS)


def sanitized_build_environment(
    source: Mapping[str, str],
    *,
    repository_root: Path,
) -> dict[str, str]:
    result = {
        name: value
        for name, value in source.items()
        if not _is_sensitive_environment_name(name)
        and name.casefold() not in {"pythonhome", "pythonpath"}
    }
    development_scripts = (
        repository_root / ".venv/Scripts"
    ).resolve(strict=False)
    packaging_scripts = (
        repository_root / ".venv-packaging/Scripts"
    ).resolve(strict=False)
    path_entries = []
    for entry in result.get("PATH", result.get("Path", "")).split(
        os.pathsep
    ):
        if not entry:
            continue
        try:
            if Path(entry).resolve(strict=False) == development_scripts:
                continue
        except OSError:
            continue
        path_entries.append(entry)
    result["PATH"] = os.pathsep.join(
        (os.fspath(packaging_scripts), *path_entries)
    )
    result.pop("Path", None)
    result.update(
        {
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "UV_OFFLINE": "1",
            "NUITKA_CACHE_DIR": os.fspath(
                repository_root / "build/nuitka-cache"
            ),
            "TEMP": os.fspath(
                repository_root / THIRD_BUILD_TEMP_RELATIVE_PATH
            ),
            "TMP": os.fspath(
                repository_root / THIRD_BUILD_TEMP_RELATIVE_PATH
            ),
            "TMPDIR": os.fspath(
                repository_root / THIRD_BUILD_TEMP_RELATIVE_PATH
            ),
            "VIRTUAL_ENV": os.fspath(
                repository_root / ".venv-packaging"
            ),
        }
    )
    return result


def _validate_packaging_environment(root: Path) -> bool:
    environment = (root / ".venv-packaging").resolve(strict=False)
    development = (root / ".venv").resolve(strict=False)
    expected_python = (
        environment / "Scripts/python.exe"
    ).resolve(strict=False)
    try:
        executable = Path(sys.executable).resolve(strict=True)
        prefix = Path(sys.prefix).resolve(strict=True)
        base_prefix = Path(sys.base_prefix).resolve(strict=True)
        versions = {
            name.casefold(): importlib_metadata.version(name)
            for name in ("openai", "PySide6", "Nuitka")
        }
        paths = tuple(
            Path(value).resolve(strict=False) for value in sys.path if value
        )
    except (OSError, importlib_metadata.PackageNotFoundError):
        return False
    return all(
        (
            executable == expected_python,
            prefix == environment,
            base_prefix != development,
            versions
            == {
                "openai": "2.48.0",
                "pyside6": "6.11.1",
                "nuitka": "4.0",
            },
            development / "Lib/site-packages" not in paths,
            (environment / "Scripts/pyside6-deploy.exe").is_file(),
            (
                environment
                / "Lib/site-packages/PySide6/plugins/platforms/qwindows.dll"
            ).is_file(),
            (
                environment
                / "Lib/site-packages/PySide6/plugins/styles"
            ).is_dir(),
        )
    )


def _manifest(directory: Path) -> dict[str, tuple[int, str]]:
    directory_stat = directory.lstat()
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or directory.is_symlink()
        or int(getattr(directory_stat, "st_file_attributes", 0))
        & FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError("standalone_manifest_root_invalid")
    result: dict[str, tuple[int, str]] = {}
    pending = [directory]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                entry_stat = path.lstat()
                is_reparse = bool(
                    int(
                        getattr(
                            entry_stat,
                            "st_file_attributes",
                            0,
                        )
                    )
                    & FILE_ATTRIBUTE_REPARSE_POINT
                )
                if path.is_symlink() or is_reparse:
                    raise OSError("standalone_manifest_link_rejected")
                if stat.S_ISDIR(entry_stat.st_mode):
                    pending.append(path)
                    continue
                if (
                    not stat.S_ISREG(entry_stat.st_mode)
                    or entry_stat.st_nlink != 1
                    or not entry.is_file(follow_symlinks=False)
                ):
                    raise OSError(
                        "standalone_manifest_non_regular_rejected"
                    )
                relative = path.relative_to(directory).as_posix()
                result[relative] = (
                    entry_stat.st_size,
                    _sha256_file(path),
                )
    return dict(sorted(result.items()))


def _path_snapshot(path: Path) -> dict[str, object]:
    if not os.path.lexists(path):
        return {"exists": False, "entries": {}}
    entries: dict[str, dict[str, object]] = {}
    pending = [(path, Path("."))]
    while pending:
        current, relative_root = pending.pop()
        result = current.lstat()
        is_reparse = current.is_symlink() or bool(
            int(getattr(result, "st_file_attributes", 0))
            & FILE_ATTRIBUTE_REPARSE_POINT
        )
        kind = (
            "directory"
            if stat.S_ISDIR(result.st_mode)
            else "file"
            if stat.S_ISREG(result.st_mode)
            else "other"
        )
        relative = relative_root.as_posix()
        record: dict[str, object] = {
            "kind": kind,
            "size": result.st_size,
            "mode": result.st_mode,
            "file_attributes": int(
                getattr(result, "st_file_attributes", 0)
            ),
            "hard_link_count": result.st_nlink,
            "reparse_point": is_reparse,
        }
        if kind == "file" and not is_reparse:
            record["sha256"] = _sha256_file(current)
        entries[relative] = record
        if kind == "directory" and not is_reparse:
            with os.scandir(current) as children:
                for child in children:
                    child_path = Path(child.path)
                    pending.append(
                        (
                            child_path,
                            relative_root / child.name,
                        )
                    )
    return {
        "exists": True,
        "entries": dict(sorted(entries.items())),
    }


def protected_artifact_snapshot(
    repository_root: Path,
) -> dict[str, object]:
    root = repository_root.resolve(strict=True)
    return {
        relative.as_posix(): _path_snapshot(root / relative)
        for relative in PROTECTED_ARTIFACT_RELATIVE_PATHS
    }


def _write_bytes_exclusive(path: Path, data: bytes) -> bool:
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return path.read_bytes() == data
    except OSError:
        return False


def prepare_dry_run_workspace(
    repository_root: Path,
) -> DryRunWorkspaceOutcome:
    try:
        root = repository_root.resolve(strict=True)
        workspace = root / DRY_RUN_WORKSPACE_RELATIVE_PATH
        if os.path.lexists(workspace):
            return DryRunWorkspaceOutcome(
                False,
                "standalone_dry_run_workspace_occupied",
            )
        tracked_spec = root / TRACKED_SPEC_RELATIVE_PATH
        production_entry = root / PRODUCTION_ENTRY_RELATIVE_PATH
        tracked_spec_hash = _sha256_file(tracked_spec)
        production_entry_hash = _sha256_file(production_entry)
        protected = protected_artifact_snapshot(root)
        input_directory = workspace / "input"
        input_directory.mkdir(parents=True)
        (input_directory / "deployment").mkdir()
        (workspace / "dist").mkdir()
        copied_entry = workspace / DRY_RUN_INPUT_RELATIVE_PATH
        entry_data = production_entry.read_bytes()
        if (
            not _write_bytes_exclusive(copied_entry, entry_data)
            or _sha256_file(copied_entry) != production_entry_hash
        ):
            raise OSError("dry_run_entry_copy_failed")

        parser = configparser.ConfigParser(interpolation=None)
        with tracked_spec.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as stream:
            parser.read_file(stream)
        plugins = tuple(
            plugin.strip()
            for plugin in parser["qt"]["plugins"].split(",")
            if plugin.strip()
        )
        extra_args = parser["nuitka"]["extra_args"].split()
        report_arguments = [
            argument
            for argument in extra_args
            if argument.startswith("--report=")
        ]
        if (
            plugins != FIXED_QT_PLUGINS
            or len(report_arguments) != 1
            or any(
                argument.startswith("--include-qt-plugins=")
                for argument in extra_args
            )
        ):
            raise OSError("dry_run_spec_invalid")
        extra_args = [
            (
                "--report="
                f"{DRY_RUN_WORKSPACE_RELATIVE_PATH.as_posix()}/"
                f"{DRY_RUN_REPORT_NAME}"
                if argument.startswith("--report=")
                else argument
            )
            for argument in extra_args
        ]
        extra_args.append(
            f"--include-qt-plugins={','.join(FIXED_QT_PLUGINS)}"
        )
        parser["app"]["project_dir"] = "input"
        parser["app"]["input_file"] = (
            DRY_RUN_WORKSPACE_RELATIVE_PATH
            / DRY_RUN_INPUT_RELATIVE_PATH
        ).as_posix()
        parser["app"]["exec_directory"] = (
            DRY_RUN_WORKSPACE_RELATIVE_PATH / "dist"
        ).as_posix()
        parser["nuitka"]["extra_args"] = " ".join(extra_args)
        rendered = io.StringIO()
        parser.write(rendered, space_around_delimiters=True)
        rendered_bytes = rendered.getvalue().encode("utf-8")
        spec_path = workspace / DRY_RUN_SPEC_NAME
        if not _write_bytes_exclusive(spec_path, rendered_bytes):
            raise OSError("dry_run_spec_write_failed")
        rendered_text = rendered_bytes.decode("utf-8")
        forbidden_paths = (
            "packaging/deployment",
            "dist/ArkClaw.dist",
            "build/windows-standalone",
        )
        if any(value in rendered_text for value in forbidden_paths):
            raise OSError("dry_run_spec_not_isolated")
        metadata = {
            "schema_version": 1,
            "protected_artifacts": protected,
            "tracked_spec_sha256": tracked_spec_hash,
            "production_entry_sha256": production_entry_hash,
            "copied_entry_sha256": _sha256_file(copied_entry),
            "environment_values_recorded": False,
        }
        if not _atomic_write_json(
            workspace / DRY_RUN_SNAPSHOT_NAME,
            metadata,
        ):
            raise OSError("dry_run_snapshot_write_failed")
        return DryRunWorkspaceOutcome(True, "none")
    except (OSError, KeyError, configparser.Error):
        return DryRunWorkspaceOutcome(
            False,
            "standalone_dry_run_materialization_failed",
        )


def finalize_dry_run_workspace(
    repository_root: Path,
) -> DryRunWorkspaceOutcome:
    try:
        root = repository_root.resolve(strict=True)
        workspace = root / DRY_RUN_WORKSPACE_RELATIVE_PATH
        snapshot_path = workspace / DRY_RUN_SNAPSHOT_NAME
        metadata = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("protected_artifacts")
            != protected_artifact_snapshot(root)
            or metadata.get("tracked_spec_sha256")
            != _sha256_file(root / TRACKED_SPEC_RELATIVE_PATH)
            or metadata.get("production_entry_sha256")
            != _sha256_file(root / PRODUCTION_ENTRY_RELATIVE_PATH)
        ):
            return DryRunWorkspaceOutcome(
                False,
                "standalone_dry_run_side_effect_detected",
            )
        allowed_files = {
            DRY_RUN_INPUT_RELATIVE_PATH.as_posix(),
            DRY_RUN_SPEC_NAME,
            DRY_RUN_STDOUT_NAME,
            DRY_RUN_STDERR_NAME,
            DRY_RUN_SNAPSHOT_NAME,
        }
        allowed_directories = {".", "input", "input/deployment", "dist"}
        snapshot = _path_snapshot(workspace)
        entries = snapshot.get("entries")
        if not isinstance(entries, dict):
            raise OSError("dry_run_workspace_invalid")
        for relative, raw_record in entries.items():
            if not isinstance(relative, str) or not isinstance(
                raw_record,
                dict,
            ):
                raise OSError("dry_run_workspace_invalid")
            kind = raw_record.get("kind")
            if (
                raw_record.get("reparse_point") is True
                or (
                    kind == "file"
                    and raw_record.get("hard_link_count") != 1
                )
                or (
                    kind == "file"
                    and relative not in allowed_files
                )
                or (
                    kind == "directory"
                    and relative not in allowed_directories
                )
                or kind not in {"file", "directory"}
            ):
                return DryRunWorkspaceOutcome(
                    False,
                    "standalone_dry_run_cleanup_failed",
                )
        for relative in sorted(
            allowed_files,
            key=lambda value: len(Path(value).parts),
            reverse=True,
        ):
            path = workspace / relative
            if path.exists():
                path.unlink()
        for relative in ("input/deployment", "dist", "input", "."):
            path = workspace if relative == "." else workspace / relative
            if path.exists():
                path.rmdir()
        if os.path.lexists(workspace):
            raise OSError("dry_run_workspace_remained")
        return DryRunWorkspaceOutcome(True, "none")
    except (OSError, ValueError, json.JSONDecodeError):
        return DryRunWorkspaceOutcome(
            False,
            "standalone_dry_run_cleanup_failed",
        )


def _is_amd64_gui_executable(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(4096)
        if len(header) < 0x100 or header[:2] != b"MZ":
            return False
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        optional = pe_offset + 24
        return (
            optional + 72 <= len(header)
            and header[pe_offset : pe_offset + 4] == b"PE\0\0"
            and struct.unpack_from("<H", header, pe_offset + 4)[0]
            == PE_MACHINE_AMD64
            and struct.unpack_from("<H", header, optional)[0]
            == PE32_PLUS_MAGIC
            and struct.unpack_from("<H", header, optional + 68)[0]
            == IMAGE_SUBSYSTEM_WINDOWS_GUI
        )
    except (OSError, struct.error):
        return False


def _atomic_write_json(path: Path, payload: object) -> bool:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                (
                    json.dumps(
                        payload,
                        ensure_ascii=True,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _materialize_spec(source: Path, destination: Path) -> bool:
    try:
        parser = configparser.ConfigParser(interpolation=None)
        with source.open("r", encoding="utf-8", newline="") as stream:
            parser.read_file(stream)
        plugins = tuple(
            plugin.strip()
            for plugin in parser["qt"]["plugins"].split(",")
            if plugin.strip()
        )
        extra_args = parser["nuitka"]["extra_args"].split()
        if (
            plugins != FIXED_QT_PLUGINS
            or any(
                argument.startswith("--include-qt-plugins=")
                for argument in extra_args
            )
        ):
            return False
        extra_args.append(
            f"--include-qt-plugins={','.join(FIXED_QT_PLUGINS)}"
        )
        parser["nuitka"]["extra_args"] = " ".join(extra_args)
        rendered = io.StringIO()
        parser.write(rendered, space_around_delimiters=True)
        data = rendered.getvalue().encode("utf-8")
        with destination.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return destination.read_bytes() == data
    except OSError:
        return False


def _logs_contain_download_or_install_prompt(paths: Sequence[Path]) -> bool:
    markers = (
        b"proceed? [y/n]",
        b"downloading ",
        b"installing package:",
        b"pip install ",
        b"assume-yes-for-downloads",
    )
    for path in paths:
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    lowered = chunk.lower()
                    if any(marker in lowered for marker in markers):
                        return True
        except OSError:
            return True
    return False


def _postconditions(
    root: Path,
    *,
    original_spec_hash: str,
) -> tuple[bool, dict[str, object]]:
    report = root / BUILD_RELATIVE_PATH / REPORT_NAME
    raw_dist = root / RAW_DIST_RELATIVE_PATH
    final_dist = root / FINAL_DIST_RELATIVE_PATH
    executable = final_dist / "ArkClaw.exe"
    report_parseable = False
    try:
        if report.stat().st_size <= MAX_REPORT_BYTES:
            element_tree.parse(report)
            report_parseable = True
    except (OSError, element_tree.ParseError):
        report_parseable = False
    try:
        raw_manifest = _manifest(raw_dist) if raw_dist.is_dir() else {}
        final_manifest = _manifest(final_dist) if final_dist.is_dir() else {}
    except OSError:
        raw_manifest = {}
        final_manifest = {}
    spec_hash_unchanged = False
    with contextlib.suppress(OSError):
        spec_hash_unchanged = (
            _sha256_file(root / TRACKED_SPEC_RELATIVE_PATH)
            == original_spec_hash
        )
    details: dict[str, object] = {
        "compilation_report_present": report.is_file(),
        "compilation_report_parseable": report_parseable,
        "raw_dist_present": raw_dist.is_dir(),
        "final_dist_present": final_dist.is_dir(),
        "final_executable_present": executable.is_file(),
        "final_executable_amd64_gui": _is_amd64_gui_executable(executable),
        "raw_final_manifest_equal": bool(raw_manifest)
        and raw_manifest == final_manifest,
        "raw_file_count": len(raw_manifest),
        "final_file_count": len(final_manifest),
        "tracked_spec_hash_unchanged": spec_hash_unchanged,
    }
    return all(
        (
            details["compilation_report_present"],
            details["compilation_report_parseable"],
            details["raw_dist_present"],
            details["final_dist_present"],
            details["final_executable_present"],
            details["final_executable_amd64_gui"],
            details["raw_final_manifest_equal"],
            details["tracked_spec_hash_unchanged"],
        )
    ), details


def _safe_command(root: Path) -> tuple[str, ...]:
    return (
        os.fspath(
            root / ".venv-packaging/Scripts/pyside6-deploy.exe"
        ),
        "--config-file",
        os.fspath(root / BUILD_RELATIVE_PATH / BUILD_SPEC_NAME),
        "--mode",
        "standalone",
        "--nuitka-version",
        "4.0",
        "--keep-deployment-files",
    )


def _safe_command_report() -> list[str]:
    return [
        "pyside6-deploy.exe",
        "--config-file",
        "<build>/pysidedeploy.spec",
        "--mode",
        "standalone",
        "--nuitka-version",
        "4.0",
        "--keep-deployment-files",
    ]


def _validate_command(command: Sequence[str], root: Path) -> bool:
    expected = _safe_command(root)
    return (
        tuple(command) == expected
        and "--onefile" not in command
        and "--assume-yes-for-downloads" not in command
        and "--force" not in command
    )


def _empty_execution_result(
    safe_code: str,
    *,
    job_configured: bool = False,
) -> BuildExecutionResult:
    return BuildExecutionResult(
        started=False,
        job_configured=job_configured,
        active_process_limit=(
            ACTIVE_PROCESS_LIMIT if job_configured else 0
        ),
        kill_on_job_close=job_configured,
        exit_code=None,
        timed_out=False,
        process_remaining=False,
        active_process_limit_hit=False,
        total_processes=0,
        peak_active_processes=0,
        stdout_sha256=None,
        stdout_bytes=0,
        stderr_sha256=None,
        stderr_bytes=0,
        safe_code=safe_code,
    )


def _select_failure_code(
    execution: BuildExecutionResult,
    *,
    postconditions_valid: bool,
    unexpected_processes: Sequence[str],
    prompt_detected: bool,
) -> str:
    if not execution.job_configured or not execution.started:
        return execution.safe_code
    if execution.timed_out:
        return "standalone_build_timeout"
    if execution.process_remaining or unexpected_processes:
        return "standalone_build_failed"
    if execution.active_process_limit_hit:
        return "standalone_build_failed"
    if execution.exit_code != 0 or prompt_detected:
        return "standalone_build_failed"
    if not postconditions_valid:
        return "standalone_postcondition_failed"
    return "none"


def run_standalone_build(
    repository_root: Path,
    *,
    runner: ProcessRunner,
    environment: Mapping[str, str],
    disk_free_reader: DiskFreeReader = _default_disk_free,
    process_snapshotter: ProcessSnapshotter | None = None,
    monotonic: Clock = time.monotonic,
    environment_validator: EnvironmentValidator = (
        _validate_packaging_environment
    ),
) -> BuildOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return BuildOutcome(False, "standalone_toolchain_invalid", {})
    if not environment_validator(root):
        return BuildOutcome(False, "standalone_toolchain_invalid", {})
    protected_paths = (
        root / "dist",
        root / "packaging/deployment",
        root / BUILD_RELATIVE_PATH,
    )
    if any(path.exists() or path.is_symlink() for path in protected_paths):
        return BuildOutcome(False, "standalone_output_occupied", {})
    try:
        free_before = disk_free_reader(root)
    except OSError:
        return BuildOutcome(False, "standalone_disk_space_insufficient", {})
    if free_before < MINIMUM_FREE_BYTES:
        return BuildOutcome(False, "standalone_disk_space_insufficient", {})
    if not validate_dependency_walker_cache(root).completed:
        return BuildOutcome(False, "standalone_toolchain_invalid", {})
    tracked_spec = root / TRACKED_SPEC_RELATIVE_PATH
    deploy = root / ".venv-packaging/Scripts/pyside6-deploy.exe"
    if not tracked_spec.is_file() or not deploy.is_file():
        return BuildOutcome(False, "standalone_toolchain_invalid", {})
    try:
        original_spec_hash = _sha256_file(tracked_spec)
    except OSError:
        return BuildOutcome(False, "standalone_toolchain_invalid", {})

    build_dir = root / BUILD_RELATIVE_PATH
    try:
        build_dir.mkdir(parents=True)
    except OSError:
        return BuildOutcome(False, "standalone_build_failed", {})
    guard = build_dir / ATTEMPT_GUARD_NAME
    try:
        with guard.open("xb") as stream:
            stream.write(b"standalone_build_attempt_started=True\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        return BuildOutcome(False, "standalone_build_failed", {})
    if not _materialize_spec(tracked_spec, build_dir / BUILD_SPEC_NAME):
        return BuildOutcome(False, "standalone_build_failed", {})

    stdout_path = build_dir / STDOUT_NAME
    stderr_path = build_dir / STDERR_NAME
    command = _safe_command(root)
    if not _validate_command(command, root):
        return BuildOutcome(False, "standalone_toolchain_invalid", {})
    snapshotter = process_snapshotter or _default_process_snapshot
    try:
        processes_before = dict(snapshotter())
    except OSError:
        return BuildOutcome(False, "standalone_build_failed", {})
    started_utc = _utc_timestamp()
    started = monotonic()
    try:
        execution = runner.run(
            command,
            working_directory=root,
            environment=sanitized_build_environment(
                environment,
                repository_root=root,
            ),
            timeout_seconds=TIMEOUT_SECONDS,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except Exception:
        execution = _empty_execution_result("standalone_build_failed")
    ended = monotonic()
    ended_utc = _utc_timestamp()
    try:
        processes_after = dict(snapshotter())
    except OSError:
        processes_after = {-1: "process_snapshot_unavailable"}
    unexpected_processes = sorted(
        {
            name.casefold()
            for pid, name in processes_after.items()
            if pid not in processes_before
            and name.casefold() in _BUILD_PROCESS_NAMES
        }
    )
    postconditions_valid, postconditions = _postconditions(
        root,
        original_spec_hash=original_spec_hash,
    )
    prompt_detected = _logs_contain_download_or_install_prompt(
        (stdout_path, stderr_path)
    )
    try:
        free_after = disk_free_reader(root)
    except OSError:
        free_after = -1
    post_cache_valid = validate_dependency_walker_cache(root).completed
    safe_code = _select_failure_code(
        execution,
        postconditions_valid=postconditions_valid and post_cache_valid,
        unexpected_processes=unexpected_processes,
        prompt_detected=prompt_detected,
    )
    completed = safe_code == "none"
    report: dict[str, object] = {
        "schema_version": 1,
        "standalone_build": completed,
        "safe_code": safe_code,
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "duration_seconds": round(max(0.0, ended - started), 3),
        "disk_free_before_bytes": free_before,
        "disk_free_after_bytes": free_after,
        "disk_consumed_bytes": (
            max(0, free_before - free_after) if free_after >= 0 else None
        ),
        "command": _safe_command_report(),
        "timeout_seconds": TIMEOUT_SECONDS,
        "hard_network_isolation": False,
        "stdin_closed": True,
        "environment_secret_names_removed": True,
        "offline_environment": {
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "UV_OFFLINE": "1",
        },
        "automatic_retry": False,
        "attempt_guard_created": guard.is_file(),
        "execution": asdict(execution),
        "unexpected_build_processes": unexpected_processes,
        "download_or_install_prompt_detected": prompt_detected,
        "dependency_walker_cache_valid_after_build": post_cache_valid,
        "postconditions": postconditions,
        "tracked_spec_sha256_before": original_spec_hash,
        "tracked_spec_sha256_after": (
            _sha256_file(tracked_spec) if tracked_spec.is_file() else None
        ),
        "raw_process_output_recorded_in_public_output": False,
        "network_accessed_by_harness": False,
        "credential_manager_accessed": False,
        "packaged_executable_executed": False,
    }
    if not _atomic_write_json(build_dir / BUILD_REPORT_NAME, report):
        return BuildOutcome(
            False,
            "standalone_build_failed",
            report,
        )
    return BuildOutcome(completed, safe_code, report)


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

    def _accounting(self, job: int) -> tuple[int, int]:
        info = _JobObjectBasicAccountingInformation()
        if not self._kernel32.QueryInformationJobObject(
            job,
            1,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return 0, ACTIVE_PROCESS_LIMIT
        return int(info.TotalProcesses), int(info.ActiveProcesses)

    def _drain_messages(
        self,
        port: int,
        *,
        active: int,
        peak: int,
        limit_hit: bool,
    ) -> tuple[int, int, bool]:
        for _ in range(1024):
            message = wintypes.DWORD()
            completion_key = ctypes.c_size_t()
            overlapped = ctypes.c_void_p()
            if not self._kernel32.GetQueuedCompletionStatus(
                port,
                ctypes.byref(message),
                ctypes.byref(completion_key),
                ctypes.byref(overlapped),
                0,
            ):
                break
            if message.value == JOB_OBJECT_MSG_NEW_PROCESS:
                active += 1
                peak = max(peak, active)
            elif message.value in (
                JOB_OBJECT_MSG_EXIT_PROCESS,
                JOB_OBJECT_MSG_ABNORMAL_EXIT_PROCESS,
            ):
                active = max(0, active - 1)
            elif message.value == JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO:
                active = 0
            elif message.value == JOB_OBJECT_MSG_ACTIVE_PROCESS_LIMIT:
                limit_hit = True
        return active, peak, limit_hit

    def run(
        self,
        command: Sequence[str],
        *,
        working_directory: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> BuildExecutionResult:
        if not _validate_command(command, working_directory):
            return _empty_execution_result("standalone_toolchain_invalid")
        kernel32 = self._kernel32
        job: int | None = None
        port: int | None = None
        process_handle: int | None = None
        thread_handle: int | None = None
        stdin_handle: int | None = None
        stdout_handle: int | None = None
        stderr_handle: int | None = None
        started = False
        timed_out = False
        remaining = False
        limit_hit = False
        exit_code: int | None = None
        total_processes = 0
        active_count = 0
        peak_active = 0
        try:
            raw_job = kernel32.CreateJobObjectW(None, None)
            if not raw_job:
                return _empty_execution_result(
                    "standalone_build_failed"
                )
            job = int(raw_job)
            raw_port = kernel32.CreateIoCompletionPort(
                INVALID_HANDLE_VALUE,
                None,
                0,
                1,
            )
            if not raw_port:
                return _empty_execution_result(
                    "standalone_build_failed"
                )
            port = int(raw_port)
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
                    "standalone_build_failed"
                )
            limits = _JobObjectExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            limits.BasicLimitInformation.ActiveProcessLimit = (
                ACTIVE_PROCESS_LIMIT
            )
            if not kernel32.SetInformationJobObject(
                job,
                9,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                return _empty_execution_result(
                    "standalone_build_failed"
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
                    f"{name}={environment[name]}"
                    for name in sorted(environment, key=str.casefold)
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
                    "standalone_build_failed",
                    job_configured=True,
                )
            process_handle = int(process_info.hProcess)
            thread_handle = int(process_info.hThread)
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                kernel32.TerminateProcess(process_handle, 0xFFFFFFFF)
                return _empty_execution_result(
                    "standalone_build_failed",
                    job_configured=True,
                )
            if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                kernel32.TerminateJobObject(job, 0xFFFFFFFF)
                return _empty_execution_result(
                    "standalone_build_failed",
                    job_configured=True,
                )
            started = True
            self._close(thread_handle)
            thread_handle = None
            deadline = time.monotonic() + timeout_seconds
            root_exited = False
            while True:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    timed_out = True
                    break
                wait_ms = max(1, min(250, int(remaining_time * 1000)))
                wait_result = kernel32.WaitForSingleObject(
                    process_handle,
                    wait_ms,
                )
                if wait_result == WAIT_OBJECT_0:
                    root_exited = True
                elif wait_result != WAIT_TIMEOUT:
                    timed_out = True
                    break
                active_count, peak_active, limit_hit = self._drain_messages(
                    port,
                    active=active_count,
                    peak=peak_active,
                    limit_hit=limit_hit,
                )
                total, active = self._accounting(job)
                total_processes = max(total_processes, total)
                peak_active = max(peak_active, active)
                if root_exited and active == 0:
                    break
            if timed_out or limit_hit:
                kernel32.TerminateJobObject(job, 0xFFFFFFFF)
                terminate_deadline = time.monotonic() + 10.0
                while time.monotonic() < terminate_deadline:
                    _, active = self._accounting(job)
                    if active == 0:
                        break
                    time.sleep(0.05)
            _, active = self._accounting(job)
            remaining = active != 0
            exit_value = wintypes.DWORD(STILL_ACTIVE)
            if (
                kernel32.GetExitCodeProcess(
                    process_handle,
                    ctypes.byref(exit_value),
                )
                and exit_value.value != STILL_ACTIVE
            ):
                exit_code = ctypes.c_int32(exit_value.value).value
            self._close(stdin_handle)
            stdin_handle = None
            self._close(stdout_handle)
            stdout_handle = None
            self._close(stderr_handle)
            stderr_handle = None
            stdout_hash, stdout_bytes = _file_digest_and_size(stdout_path)
            stderr_hash, stderr_bytes = _file_digest_and_size(stderr_path)
            return BuildExecutionResult(
                started=started,
                job_configured=True,
                active_process_limit=ACTIVE_PROCESS_LIMIT,
                kill_on_job_close=True,
                exit_code=exit_code,
                timed_out=timed_out,
                process_remaining=remaining,
                active_process_limit_hit=limit_hit,
                total_processes=total_processes,
                peak_active_processes=peak_active,
                stdout_sha256=stdout_hash,
                stdout_bytes=stdout_bytes,
                stderr_sha256=stderr_hash,
                stderr_bytes=stderr_bytes,
                safe_code=(
                    "standalone_build_timeout"
                    if timed_out
                    else "none"
                ),
            )
        except OSError:
            return _empty_execution_result("standalone_build_failed")
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


def _default_process_snapshot() -> Mapping[int, str]:
    if sys.platform != "win32":
        return {}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError("process_snapshot_unavailable")
    result: dict[int, str] = {}
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise OSError("process_snapshot_unavailable")
        while True:
            result[int(entry.th32ProcessID)] = str(entry.szExeFile)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one controlled standalone build."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--confirm-build", action="store_true")
    mode.add_argument(
        "--prepare-dry-run-workspace",
        action="store_true",
    )
    mode.add_argument(
        "--finalize-dry-run-workspace",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.prepare_dry_run_workspace:
        root = Path(__file__).resolve().parents[1]
        try:
            dry_run_outcome = prepare_dry_run_workspace(root)
        except Exception:
            print("safe_code=standalone_dry_run_materialization_failed")
            return 2
        print(f"safe_code={dry_run_outcome.safe_code}")
        return 0 if dry_run_outcome.completed else 2
    if arguments.finalize_dry_run_workspace:
        root = Path(__file__).resolve().parents[1]
        try:
            dry_run_outcome = finalize_dry_run_workspace(root)
        except Exception:
            print("safe_code=standalone_dry_run_cleanup_failed")
            return 2
        print(f"safe_code={dry_run_outcome.safe_code}")
        return 0 if dry_run_outcome.completed else 2
    if not arguments.confirm_build:
        print("safe_code=standalone_build_disabled")
        return 0
    root = Path(__file__).resolve().parents[1]
    try:
        build_outcome = run_standalone_build(
            root,
            runner=WindowsJobObjectRunner(),
            environment=os.environ,
        )
    except Exception:
        print("safe_code=standalone_build_failed")
        return 2
    report = build_outcome.report
    execution = report.get("execution", {})
    postconditions = report.get("postconditions", {})
    if isinstance(execution, Mapping) and isinstance(postconditions, Mapping):
        print(
            " ".join(
                (
                    "standalone_build="
                    f"{str(build_outcome.completed).lower()}",
                    "attempts=1",
                    "job_configured="
                    f"{str(execution.get('job_configured', False)).lower()}",
                    "peak_processes="
                    f"{execution.get('peak_active_processes', 0)}",
                    "pyside_deploy_exit_code="
                    f"{execution.get('exit_code')}",
                    "postconditions_valid="
                    f"{str(all(bool(value) for value in postconditions.values())).lower()}",
                    "hard_network_isolation=false",
                    "packaged_executable_executed=false",
                )
            )
        )
        print(
            " ".join(
                (
                    f"stdout_sha256={execution.get('stdout_sha256')}",
                    f"stdout_bytes={execution.get('stdout_bytes', 0)}",
                    f"stderr_sha256={execution.get('stderr_sha256')}",
                    f"stderr_bytes={execution.get('stderr_bytes', 0)}",
                )
            )
        )
    print(f"safe_code={build_outcome.safe_code}")
    return 0 if build_outcome.completed else 2


if __name__ == "__main__":
    sys.exit(main())
