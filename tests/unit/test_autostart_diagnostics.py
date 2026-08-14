from __future__ import annotations

import io
import json
import socket
from pathlib import Path
from typing import cast

import pytest

from arkclaw.application.system.autostart_eligibility import (
    AutostartEligibilityReason,
    AutostartEligibilityResult,
)
from arkclaw.application.system.autostart_service import (
    AutostartService,
    AutostartStatus,
)
from arkclaw.application.system.startup_mode import (
    AUTOSTART_DIAGNOSTIC_ARGUMENT,
)
from arkclaw.bootstrap import autostart_diagnostics
from arkclaw.presentation.qt import pet_application

_SENSITIVE_TEXT = (
    "unsafe-runtime-detail-never-display "
    "sk-test-never-use-this-value CredentialBlob"
)


class _ForbiddenBackend:
    def read_value(self) -> None:
        raise AssertionError(_SENSITIVE_TEXT)

    def write_value(self, command: str) -> None:
        del command
        raise AssertionError(_SENSITIVE_TEXT)

    def delete_value(self) -> None:
        raise AssertionError(_SENSITIVE_TEXT)


@pytest.mark.parametrize("reason", list(AutostartEligibilityReason))
def test_diagnostic_json_contains_only_fixed_schema(
    reason: AutostartEligibilityReason,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autostart_diagnostics,
        "diagnose_production_autostart_eligibility",
        lambda: AutostartEligibilityResult(reason),
    )
    stream = io.StringIO()

    exit_code = autostart_diagnostics.write_autostart_runtime_diagnostic(
        stream
    )

    assert exit_code == 0
    payload = json.loads(stream.getvalue())
    assert payload == {
        "autostart_runtime_diagnostic": True,
        "reason": reason.value,
        "safe_code": "autostart_runtime_diagnostic_complete",
        "schema_version": 1,
        "supported": reason is AutostartEligibilityReason.SUPPORTED,
    }
    assert _SENSITIVE_TEXT not in stream.getvalue()


def test_diagnostic_mode_constructs_no_qt_runtime_registry_or_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        calls.append("forbidden")
        raise AssertionError(_SENSITIVE_TEXT)

    monkeypatch.setattr(pet_application, "QApplication", forbidden)
    monkeypatch.setattr(
        pet_application,
        "create_production_single_instance",
        forbidden,
    )
    monkeypatch.setattr(
        pet_application,
        "create_production_autostart_service",
        forbidden,
    )
    monkeypatch.setattr(
        pet_application,
        "ProductionQtRuntimeCompositionRoot",
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
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(
        autostart_diagnostics,
        "diagnose_production_autostart_eligibility",
        lambda: AutostartEligibilityResult(
            AutostartEligibilityReason.MARKER_MISSING
        ),
    )

    exit_code = pet_application.main(
        ["ArkClaw.exe", AUTOSTART_DIAGNOSTIC_ARGUMENT]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["reason"] == "marker_missing"
    assert calls == []
    assert captured.err == ""
    assert _SENSITIVE_TEXT not in captured.out


def test_diagnostic_argument_must_be_the_only_option() -> None:
    assert autostart_diagnostics.is_autostart_runtime_diagnostic_requested(
        ["ArkClaw.exe", AUTOSTART_DIAGNOSTIC_ARGUMENT]
    )
    assert not autostart_diagnostics.is_autostart_runtime_diagnostic_requested(
        ["ArkClaw.exe"]
    )
    assert not autostart_diagnostics.is_autostart_runtime_diagnostic_requested(
        ["ArkClaw.exe", AUTOSTART_DIAGNOSTIC_ARGUMENT, "--startup"]
    )


def test_internal_reason_maps_to_existing_public_safe_state(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executable = tmp_path / "ArkClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    service = AutostartService(
        _ForbiddenBackend(),
        lambda: executable,
        platform_supported=True,
        eligibility_probe=lambda candidate: AutostartEligibilityResult(
            AutostartEligibilityReason.EXECUTABLE_PARENT_MISMATCH
        ),
    )

    snapshot = service.query()

    captured = capsys.readouterr()
    visible = "\n".join(
        (
            snapshot.safe_code,
            snapshot.safe_message,
            repr(snapshot),
            captured.out,
            captured.err,
            caplog.text,
        )
    )
    assert snapshot.status is AutostartStatus.INVALID_EXECUTABLE
    assert snapshot.safe_code == "autostart_invalid_executable"
    assert "executable_parent_mismatch" not in visible
    assert str(tmp_path) not in visible
    assert _SENSITIVE_TEXT not in visible


def test_invalid_internal_probe_result_fails_closed_without_leaking(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executable = tmp_path / "ArkClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    service = AutostartService(
        _ForbiddenBackend(),
        lambda: executable,
        platform_supported=True,
        eligibility_probe=lambda candidate: cast(
            AutostartEligibilityResult,
            object(),
        ),
    )

    snapshot = service.query()

    captured = capsys.readouterr()
    assert snapshot.status is AutostartStatus.INVALID_EXECUTABLE
    assert snapshot.safe_code == "autostart_invalid_executable"
    assert _SENSITIVE_TEXT not in repr(snapshot)
    assert captured.out == ""
    assert captured.err == ""
