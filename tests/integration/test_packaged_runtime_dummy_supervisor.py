from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SUPERVISOR = (
    _PROJECT_ROOT / "packaging/packaged_runtime_network_supervisor.ps1"
)
_ATTEMPT_NAME = os.environ.get("SJTUCLAW_DUMMY_ATTEMPT", "attempt-01")
_ATTEMPT_ROOT = (
    _PROJECT_ROOT
    / "build/packaged-runtime-supervisor-recovery"
    / _ATTEMPT_NAME
)
_POWERSHELL = (
    Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)


@pytest.mark.skipif(
    os.environ.get("SJTUCLAW_RUN_DUMMY_SUPERVISOR") != "1",
    reason="Set SJTUCLAW_RUN_DUMMY_SUPERVISOR=1 for the one-shot Dummy lifecycle gate.",
)
def test_dummy_supervisor_lifecycle() -> None:
    assert _ATTEMPT_NAME in {f"attempt-{index:02d}" for index in range(1, 7)}
    assert not _ATTEMPT_ROOT.exists()

    completed = subprocess.run(
        [
            str(_POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SUPERVISOR),
            "-Mode",
            "Dummy",
            "-AttemptName",
            _ATTEMPT_NAME,
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert "supervisor_complete=true" in completed.stdout
    assert "safe_code=dummy_supervisor_lifecycle_verified" in completed.stdout

    checkpoint = json.loads(
        (_ATTEMPT_ROOT / "supervisor-checkpoint.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (_ATTEMPT_ROOT / "diagnostic-summary.json").read_text(encoding="utf-8")
    )
    raw_records = [
        json.loads(line)
        for line in (
            _ATTEMPT_ROOT / "tcp-observations.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line
    ]
    dummy_pid = json.loads(
        (_ATTEMPT_ROOT / "dummy-pid.json").read_text(encoding="utf-8")
    )["dummy_pid"]

    assert checkpoint["supervisor_phase"] == "completed"
    assert checkpoint["child_created"] is True
    assert checkpoint["child_running"] is False
    assert checkpoint["child_exit_observed"] is True
    assert checkpoint["terminal_summary_written"] is True
    assert checkpoint["successful_poll_count"] >= 3
    assert summary["safe_code"] == "dummy_supervisor_lifecycle_verified"
    assert summary["child_exit_code"] == 0
    assert summary["child_residual_process_count"] == 0
    assert summary["unique_endpoint_count"] == 0
    assert len(raw_records) >= 3
    assert all(record["sampler_success"] is True for record in raw_records)
    assert all(record["state"] == "empty" for record in raw_records)
    assert all(record["endpoint_key"] is None for record in raw_records)
    assert all(record["child_pid"] == dummy_pid for record in raw_records)
    assert not list(_ATTEMPT_ROOT.rglob("*.part"))
    residual_check = subprocess.run(
        [
            str(_POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f"if (Get-Process -Id {dummy_pid} "
                "-ErrorAction SilentlyContinue) { exit 2 }"
            ),
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert residual_check.returncode == 0
