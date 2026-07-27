from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PACKAGING = _PROJECT_ROOT / "packaging"
_CACHE_PATH = _PACKAGING / "dependency_walker_cache.py"
_SMOKE_PATH = _PACKAGING / "dependency_walker_smoke.py"
_POWERSHELL_PATH = _PACKAGING / "run_dependency_walker_smoke.ps1"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_CACHE: Any = _load("dependency_walker_cache", _CACHE_PATH)
_SMOKE: Any = _load("_dependency_walker_smoke_test", _SMOKE_PATH)


def _minimal_pe(marker: bytes = b"") -> bytes:
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, 0x8664)
    struct.pack_into("<H", data, 0x84 + 16, 0xF0)
    struct.pack_into("<H", data, 0x84 + 20, 0x20B)
    data[0x200 : 0x200 + len(marker)] = marker
    return bytes(data)


def _prepare_root(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binaries = {
        "depends.exe": _minimal_pe(b"depends-exe"),
        "depends.dll": _minimal_pe(b"depends-dll"),
    }
    expected = {
        name: (len(payload), hashlib.sha256(payload).hexdigest())
        for name, payload in binaries.items()
    }
    monkeypatch.setattr(_CACHE, "EXPECTED_FILES", expected)
    monkeypatch.setattr(_SMOKE, "EXPECTED_FILES", expected)
    cache = root / _CACHE.CACHE_RELATIVE_PATH
    cache.mkdir(parents=True)
    for name, payload in binaries.items():
        (cache / name).write_bytes(payload)
    smoke = root / _SMOKE.SMOKE_RELATIVE_PATH
    smoke.mkdir(parents=True)
    (smoke / _SMOKE.PROBE_EXE_NAME).write_bytes(
        _minimal_pe(b"probe_dependency.dll")
    )
    (smoke / _SMOKE.PROBE_DLL_NAME).write_bytes(
        _minimal_pe(b"probe-dll")
    )


class _FakeRunner:
    def __init__(
        self,
        module: Any,
        *,
        result: Any | None = None,
        create_output: bool = True,
        create_marker: bool = False,
        sensitive_output: str = "",
    ) -> None:
        self._module = module
        self.result = result or _successful_execution(module)
        self.create_output = create_output
        self.create_marker = create_marker
        self.sensitive_output = sensitive_output
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        command: Any,
        *,
        working_directory: Path,
        environment: Any,
        timeout_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> Any:
        self.calls.append(tuple(command))
        assert environment["PATH"] == ""
        assert timeout_seconds == 30.0
        if self.create_output:
            Path(str(command[2])[3:]).write_text(
                "fake depends output",
                encoding="latin1",
            )
        stdout_path.write_text(self.sensitive_output, encoding="utf-8")
        stderr_path.write_text(self.sensitive_output, encoding="utf-8")
        if self.create_marker:
            (working_directory / self._module.MARKER_NAME).write_text(
                "executed",
                encoding="utf-8",
            )
        return self.result


def _successful_execution(module: Any) -> Any:
    return module.JobExecutionResult(
        started=True,
        job_configured=True,
        active_process_limit=1,
        kill_on_job_close=True,
        exit_code=0,
        timed_out=False,
        child_process_count=0,
        child_process_attempted=False,
        process_remaining=False,
        depends_dll_observed_loaded=False,
        stdout_sha256="0" * 64,
        stdout_bytes=0,
        stderr_sha256="0" * 64,
        stderr_bytes=0,
        safe_code="none",
    )


def _run(
    root: Path,
    runner: _FakeRunner,
    *,
    registry: Any = None,
    files: Any = None,
    parser: Any = None,
) -> Any:
    return _SMOKE.run_dependency_walker_smoke(
        root,
        runner=runner,
        registry_snapshotter=registry or (lambda: {"fixed": None}),
        file_snapshotter=files or (lambda: {"README.md": "same"}),
        output_parser=parser or (lambda path: ["probe_dependency.dll"]),
    )


def test_default_entry_is_inert() -> None:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_POWERSHELL_PATH),
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "safe_code=dependency_walker_execution_disabled\n"
    )


def test_success_requires_every_bounded_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    runner = _FakeRunner(_SMOKE)

    outcome = _run(tmp_path, runner)

    assert outcome.completed
    assert outcome.safe_code == "standalone_build_authorization_required"
    assert len(runner.calls) == 1
    command = runner.calls[0]
    assert command[1:] == (
        "-c",
        f"-ot{tmp_path / _SMOKE.SMOKE_RELATIVE_PATH / _SMOKE.OUTPUT_NAME}",
        f"-d:{tmp_path / _SMOKE.SMOKE_RELATIVE_PATH / _SMOKE.DWP_NAME}",
        "-f1",
        "-pa1",
        "-ps1",
        os.fspath(
            tmp_path
            / _SMOKE.SMOKE_RELATIVE_PATH
            / _SMOKE.PROBE_EXE_NAME
        ),
    )
    report = json.loads(
        (
            tmp_path
            / _SMOKE.SMOKE_RELATIVE_PATH
            / _SMOKE.REPORT_NAME
        ).read_text(encoding="utf-8")
    )
    assert report["host_execution"] is True
    assert report["windows_sandbox"] is False
    assert report["hard_network_isolation"] is False
    assert report["probe_executed"] is False
    assert report["expected_dependency_found"] is True


def test_pb_argument_is_rejected_before_runner() -> None:
    command = (
        "depends.exe",
        "-c",
        "-otfixed",
        "-d:fixed",
        "-f1",
        "-pb",
        "-ps1",
        "probe.exe",
    )

    assert _SMOKE._validate_command(command) is False


def test_job_setup_failure_reports_zero_started_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    result = _SMOKE._empty_execution_result(
        "dependency_walker_job_object_failed"
    )
    runner = _FakeRunner(_SMOKE, result=result, create_output=False)

    outcome = _run(tmp_path, runner)

    assert not outcome.completed
    assert outcome.safe_code == "dependency_walker_job_object_failed"
    assert outcome.report["host_execution"] is False


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        (
            {"child_process_count": 1, "child_process_attempted": True},
            "dependency_walker_child_process_rejected",
        ),
        (
            {"timed_out": True, "process_remaining": False},
            "dependency_walker_process_timeout",
        ),
        (
            {"timed_out": True, "process_remaining": True},
            "dependency_walker_process_timeout",
        ),
    ],
)
def test_job_failures_are_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, object],
    expected: str,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    result = replace(_successful_execution(_SMOKE), **updates)

    outcome = _run(tmp_path, _FakeRunner(_SMOKE, result=result))

    assert not outcome.completed
    assert outcome.safe_code == expected


def test_missing_output_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)

    outcome = _run(
        tmp_path,
        _FakeRunner(_SMOKE, create_output=False),
    )

    assert outcome.safe_code == "dependency_walker_output_missing"


def test_output_parse_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    sensitive = "secret-opaque-output-never-log"

    def fail_parser(path: Path) -> list[str]:
        raise ValueError(sensitive, path)

    outcome = _run(
        tmp_path,
        _FakeRunner(_SMOKE, sensitive_output=sensitive),
        parser=fail_parser,
    )
    serialized = json.dumps(outcome.report)

    assert outcome.safe_code == "dependency_walker_output_invalid"
    assert sensitive not in serialized
    assert sensitive not in repr(outcome)


def test_runner_exception_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    sensitive = "sensitive-runner-body"

    class RaisingRunner:
        def run(self, *args: object, **kwargs: object) -> Any:
            del args, kwargs
            raise OSError(sensitive)

    outcome = _SMOKE.run_dependency_walker_smoke(
        tmp_path,
        runner=RaisingRunner(),
        registry_snapshotter=lambda: {"fixed": None},
        file_snapshotter=lambda: {"README.md": "same"},
        output_parser=lambda path: ["probe_dependency.dll"],
    )
    serialized = json.dumps(outcome.report)

    assert outcome.safe_code == "dependency_walker_job_object_failed"
    assert sensitive not in serialized
    assert sensitive not in repr(outcome)


def test_probe_marker_is_a_hard_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)

    outcome = _run(
        tmp_path,
        _FakeRunner(_SMOKE, create_marker=True),
    )

    assert outcome.safe_code == "dependency_walker_probe_executed"
    assert outcome.report["probe_executed"] is True


def test_registry_change_reports_only_fixed_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    snapshots = iter(
        [
            {r"Software\Dependency Walker": None},
            {r"Software\Dependency Walker": "hash"},
        ]
    )

    outcome = _run(
        tmp_path,
        _FakeRunner(_SMOKE),
        registry=lambda: next(snapshots),
    )

    assert outcome.safe_code == "dependency_walker_registry_changed"
    assert outcome.report["changed_registry_paths"] == [
        r"Software\Dependency Walker"
    ]


def test_unexpected_file_change_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    snapshots = iter(
        [
            {"README.md": "before"},
            {"README.md": "after"},
        ]
    )

    outcome = _run(
        tmp_path,
        _FakeRunner(_SMOKE),
        files=lambda: next(snapshots),
    )

    assert outcome.safe_code == "dependency_walker_unexpected_file_change"
    assert outcome.report["unexpected_file_paths"] == ["README.md"]


def test_expected_dependency_is_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)

    outcome = _run(
        tmp_path,
        _FakeRunner(_SMOKE),
        parser=lambda path: ["kernel32.dll"],
    )

    assert outcome.safe_code == (
        "dependency_walker_expected_dependency_missing"
    )


def test_post_execution_hash_change_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    cache_exe = (
        tmp_path
        / _CACHE.CACHE_RELATIVE_PATH
        / "depends.exe"
    )

    class MutatingRunner(_FakeRunner):
        def run(
            self,
            command: Any,
            *,
            working_directory: Path,
            environment: Any,
            timeout_seconds: float,
            stdout_path: Path,
            stderr_path: Path,
        ) -> Any:
            result = super().run(
                command,
                working_directory=working_directory,
                environment=environment,
                timeout_seconds=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            cache_exe.write_bytes(b"changed")
            return result

    outcome = _run(tmp_path, MutatingRunner(_SMOKE))

    assert outcome.safe_code == "dependency_walker_post_hash_invalid"
    assert outcome.report["post_execution_hash_valid"] is False


def test_exit_code_is_reported_as_independent_bit_masks() -> None:
    interpretation = _SMOKE._exit_code_interpretation(5)

    assert interpretation["raw"] == 5
    assert interpretation["set_bit_masks"] == [
        "0x00000001",
        "0x00000004",
    ]
    assert interpretation["set_bit_semantics"] == [
        {
            "mask": "0x00000001",
            "meaning": "unclassified_dependency_walker_flag",
        },
        {
            "mask": "0x00000004",
            "meaning": "unclassified_dependency_walker_flag",
        },
    ]
    assert interpretation["meaning"] == (
        "dependency_walker_bit_flags_present"
    )


def test_observed_missing_dependency_exit_flag_has_fixed_semantics() -> None:
    interpretation = _SMOKE._exit_code_interpretation(0x200)

    assert interpretation["set_bit_semantics"] == [
        {
            "mask": "0x00000200",
            "meaning": (
                "required_implicit_or_forwarded_dependency_not_found"
            ),
        }
    ]


def test_execution_guard_prevents_a_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_root(tmp_path, monkeypatch)
    runner = _FakeRunner(_SMOKE)

    first = _run(tmp_path, runner)
    second = _run(tmp_path, runner)

    assert first.completed
    assert second.safe_code == (
        "dependency_walker_execution_already_attempted"
    )
    assert len(runner.calls) == 1


def test_source_uses_native_job_object_without_shell_execution() -> None:
    text = _SMOKE_PATH.read_text(encoding="utf-8")
    casefolded = text.casefold()

    assert "CreateJobObjectW" in text
    assert "AssignProcessToJobObject" in text
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in text
    assert "JOB_OBJECT_LIMIT_ACTIVE_PROCESS" in text
    assert "CreateProcessW" in text
    assert "CREATE_SUSPENDED" in text
    assert "shell=true" not in casefolded
    assert "cmd.exe" not in casefolded
    assert "start-process" not in casefolded
    assert "asyncio" not in casefolded
    assert "socket" not in casefolded
    assert "requests" not in casefolded
