from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SUPERVISOR_PATH = (
    _PROJECT_ROOT / "packaging/packaged_runtime_network_supervisor.ps1"
)
_POWERSHELL = Path(
    os.environ.get(
        "SYSTEMROOT",
        r"C:\Windows",
    )
) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def _script_text() -> str:
    return _SUPERVISOR_PATH.read_text(encoding="utf-8")


def test_supervisor_defaults_to_inert_success_without_runtime_evidence() -> None:
    evidence_root = _PROJECT_ROOT / "build/packaged-runtime-network-diagnostic"
    before = evidence_root.exists()

    completed = subprocess.run(
        [
            str(_POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SUPERVISOR_PATH),
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.strip() == (
        "packaged_runtime_supervisor=False "
        "safe_code=packaged_runtime_supervisor_disabled"
    )
    assert evidence_root.exists() is before


def test_supervisor_has_valid_powershell_ast() -> None:
    escaped_path = str(_SUPERVISOR_PATH).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped_path}',[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -ne 0) { exit 2 }"
    )

    completed = subprocess.run(
        [
            str(_POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""


def test_supervisor_uses_only_authoritative_tcp_sampler() -> None:
    source = _script_text()

    assert "Get-NetTCPConnection" in source
    assert "GetExtendedTcpTable" not in source
    assert "IP Helper" not in source
    assert "netstat" not in source.casefold()


def test_supervisor_keeps_raw_observations_and_summary_separate() -> None:
    source = _script_text()

    assert '"tcp-observations.json"' in source
    assert '"diagnostic-summary.json"' in source
    assert "$RawObservationPath" in source
    assert "$SummaryPath" in source


def test_supervisor_records_required_observation_counters() -> None:
    source = _script_text()
    required_fields = {
        "poll_count",
        "sample_count",
        "unique_endpoint_count",
        "bound_endpoint_count",
        "listen_endpoint_count",
        "established_endpoint_count",
        "loopback_endpoint_count",
        "external_endpoint_count",
        "unattributed_endpoint_count",
        "unique_flow_count",
    }

    for field in required_fields:
        assert field in source


def test_supervisor_requires_explicit_diagnostic_confirmation() -> None:
    source = _script_text()

    assert "[switch]$ConfirmDiagnostic" in source
    assert "diagnostic_confirmation_required" in source
    assert "packaged_runtime_diagnostic_confirmation_required" in source


def test_supervisor_has_one_fixed_packaged_executable_start_site() -> None:
    source = _script_text()

    assert source.count("$process.Start()") == 1
    assert '$ExecutablePath = Join-Path $DistRoot "SJTUClaw.exe"' in source
    assert "LaunchIndex" not in source
    assert "secondary" not in source.casefold()


def test_supervisor_contains_no_forbidden_launcher_commands() -> None:
    source = _script_text().casefold()

    for forbidden in (
        "start-process",
        "cmd.exe",
        "invoke-expression",
        "set-executionpolicy",
        "unblock-file",
        "setx",
    ):
        assert forbidden not in source


def test_supervisor_redirects_all_controlled_paths_inside_repository() -> None:
    source = _script_text()

    for name in (
        "TEMP",
        "TMP",
        "TMPDIR",
        "LOCALAPPDATA",
        "APPDATA",
        "HOME",
        "USERPROFILE",
    ):
        assert f"{name} = Join-Path $VerificationRoot" in source
    assert '$RepositoryRoot = "D:\\SJTUClaw"' in source


def test_supervisor_filters_sensitive_and_proxy_environment_names() -> None:
    source = _script_text()

    for marker in (
        "API_KEY",
        "AUTHORIZATION",
        "CREDENTIAL",
        "PASSWORD",
        "SECRET",
        "TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    ):
        assert f'"{marker}"' in source


def test_supervisor_never_serializes_process_environment_values() -> None:
    source = _script_text()

    assert source.count("environment_values_recorded = $false") >= 2
    assert "originalEntries | ConvertTo-Json" not in source
    assert "normalized | ConvertTo-Json" not in source


def test_supervisor_environment_test_does_not_create_executable() -> None:
    source = _script_text()
    environment_function = source.split(
        "function Invoke-EnvironmentTest",
        maxsplit=1,
    )[1].split(
        "function Invoke-PackagedDiagnostic",
        maxsplit=1,
    )[0]

    assert "$process.Start()" not in environment_function
    assert "executable_creation_count = 0" in environment_function
    assert "external_process_created = $false" in environment_function


def test_supervisor_diagnostic_schema_is_safe_and_fixed() -> None:
    source = _script_text()
    safe_fields = {
        "observer_authority",
        "process_exit_observed",
        "endpoints_disappeared_after_exit",
        "pid_reuse_detected",
        "gui_window_observed",
        "packaged_local_channel_verified",
        "safe_code",
    }

    for field in safe_fields:
        assert field in source
    assert "exception_message" not in source.casefold()
    assert "stacktrace" not in source.casefold()
    assert "authorization" not in json.dumps(
        {
            "raw": "tcp-observations.json",
            "summary": "diagnostic-summary.json",
        }
    ).casefold()
