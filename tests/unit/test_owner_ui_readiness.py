from __future__ import annotations

import json
from pathlib import Path

import pytest

from arkclaw.presentation.qt.owner_ui_readiness import (
    OWNER_UI_DIAGNOSTIC_ARGUMENT,
    OwnerStartupFailure,
    OwnerStartupStage,
    OwnerUiCheckpointRecorder,
    OwnerUiDiagnosticArgumentError,
    OwnerUiReadinessSnapshot,
    classify_owner_ui_readiness,
    prepare_owner_ui_diagnostic_launch,
)

_NONCE = "0123456789abcdef0123456789abcdef"
_SENSITIVE_TEXT = "sk-test-never-use-this-value CredentialBlob"


class _FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _snapshot(**changes: bool) -> OwnerUiReadinessSnapshot:
    values = {
        "instance_owner": True,
        "runtime_ready": True,
        "pet_window_constructed": True,
        "pet_window_visible": True,
        "pet_window_in_workspace": True,
        "tray_constructed": True,
        "tray_available": True,
        "tray_visible": True,
        "application_ready": True,
    }
    values.update(changes)
    return OwnerUiReadinessSnapshot(**values)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"instance_owner": False},
            OwnerStartupFailure.SINGLE_INSTANCE_SECONDARY,
        ),
        (
            {"runtime_ready": False},
            OwnerStartupFailure.RUNTIME_NOT_READY,
        ),
        (
            {"pet_window_constructed": False},
            OwnerStartupFailure.PET_WINDOW_NOT_CREATED,
        ),
        (
            {"pet_window_visible": False},
            OwnerStartupFailure.PET_WINDOW_NOT_VISIBLE,
        ),
        (
            {"pet_window_in_workspace": False},
            OwnerStartupFailure.PET_WINDOW_OUTSIDE_WORKSPACE,
        ),
        (
            {"tray_constructed": False},
            OwnerStartupFailure.TRAY_NOT_CREATED,
        ),
        (
            {"tray_available": False},
            OwnerStartupFailure.SYSTEM_TRAY_UNAVAILABLE,
        ),
        (
            {"tray_visible": False},
            OwnerStartupFailure.TRAY_NOT_VISIBLE,
        ),
        (
            {"application_ready": False},
            OwnerStartupFailure.APPLICATION_READY_MISSING,
        ),
        ({}, OwnerStartupFailure.NONE),
    ],
)
def test_readiness_classification_is_fixed_and_ordered(
    changes: dict[str, bool],
    expected: OwnerStartupFailure,
) -> None:
    assert classify_owner_ui_readiness(_snapshot(**changes)) is expected


def test_checkpoint_is_atomic_redacted_and_monotonic(
    tmp_path: Path,
) -> None:
    clock = _FakeClock()
    recorder = OwnerUiCheckpointRecorder(
        tmp_path,
        _NONCE,
        monotonic=clock,
    )

    assert recorder.record(OwnerStartupStage.STARTED)
    clock.advance(0.25)
    assert recorder.record(OwnerStartupStage.ARGUMENTS_VALIDATED)
    checkpoint = tmp_path / "checkpoint.json"
    document = json.loads(checkpoint.read_text(encoding="utf-8"))

    assert document == {
        "events": [
            {
                "elapsed_milliseconds": 0,
                "failure_category": "none",
                "sequence": 1,
                "stage": "started",
            },
            {
                "elapsed_milliseconds": 250,
                "failure_category": "none",
                "sequence": 2,
                "stage": "arguments_validated",
            },
        ],
        "owner_ui_readiness_checkpoint": True,
        "schema_version": 1,
        "session_nonce": _NONCE,
        "value_text_recorded": False,
    }
    assert not (tmp_path / "checkpoint.json.part").exists()
    assert _SENSITIVE_TEXT not in checkpoint.read_text(encoding="utf-8")


def test_checkpoint_rejects_duplicate_reverse_and_post_terminal_stages(
    tmp_path: Path,
) -> None:
    recorder = OwnerUiCheckpointRecorder(tmp_path, _NONCE)

    assert recorder.record(OwnerStartupStage.STARTED)
    assert recorder.record(OwnerStartupStage.RUNTIME_STARTING)
    assert not recorder.record(OwnerStartupStage.RUNTIME_STARTING)
    assert not recorder.record(OwnerStartupStage.ARGUMENTS_VALIDATED)
    assert recorder.record(
        OwnerStartupStage.FAILED_SAFE,
        OwnerStartupFailure.RUNTIME_NOT_READY,
    )
    assert not recorder.record(OwnerStartupStage.APPLICATION_READY)


def test_checkpoint_write_failure_is_contained_and_removes_part(
    tmp_path: Path,
) -> None:
    def fail_replace(source: str, destination: str) -> None:
        del source, destination
        raise OSError(_SENSITIVE_TEXT)

    recorder = OwnerUiCheckpointRecorder(
        tmp_path,
        _NONCE,
        replace=fail_replace,
    )

    assert not recorder.record(OwnerStartupStage.STARTED)
    assert recorder.write_failed
    assert recorder.last_stage is None
    assert not (tmp_path / "checkpoint.json").exists()
    assert not (tmp_path / "checkpoint.json.part").exists()


@pytest.mark.parametrize(
    "nonce",
    [
        "",
        "0" * 31,
        "0" * 33,
        "G" * 32,
        _SENSITIVE_TEXT,
    ],
)
def test_checkpoint_rejects_invalid_or_stale_nonce(
    tmp_path: Path,
    nonce: str,
) -> None:
    with pytest.raises(OwnerUiDiagnosticArgumentError):
        OwnerUiCheckpointRecorder(tmp_path, nonce)


def test_default_launch_is_inert() -> None:
    launch = prepare_owner_ui_diagnostic_launch(["ArkClaw.exe"])

    assert launch.arguments == ("ArkClaw.exe",)
    assert launch.recorder is None


def test_packaged_launch_creates_one_isolated_session(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    executable = repository / "dist" / "ArkClaw.dist" / "ArkClaw.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    (repository / "build").mkdir()

    launch = prepare_owner_ui_diagnostic_launch(
        ["ArkClaw.exe", OWNER_UI_DIAGNOSTIC_ARGUMENT, _NONCE],
        executable=executable,
    )

    assert launch.arguments == ("ArkClaw.exe",)
    assert launch.recorder is not None
    assert launch.recorder.record(OwnerStartupStage.STARTED)
    evidence_root = (
        repository / "build" / "autostart-owner-ui-readiness" / _NONCE
    )
    assert (evidence_root / "checkpoint.json").is_file()
    assert not (evidence_root / "checkpoint.json.part").exists()


def test_packaged_launch_rejects_reuse_and_extra_arguments(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    executable = repository / "dist" / "ArkClaw.dist" / "ArkClaw.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    (repository / "build").mkdir()
    arguments = ["ArkClaw.exe", OWNER_UI_DIAGNOSTIC_ARGUMENT, _NONCE]
    prepare_owner_ui_diagnostic_launch(arguments, executable=executable)

    with pytest.raises(OwnerUiDiagnosticArgumentError):
        prepare_owner_ui_diagnostic_launch(arguments, executable=executable)
    with pytest.raises(OwnerUiDiagnosticArgumentError):
        prepare_owner_ui_diagnostic_launch(
            [*arguments, "--startup"],
            executable=executable,
        )


def test_diagnostic_never_serializes_dynamic_failure_text(
    tmp_path: Path,
) -> None:
    recorder = OwnerUiCheckpointRecorder(tmp_path, _NONCE)

    assert recorder.record(OwnerStartupStage.STARTED)
    assert recorder.record(
        OwnerStartupStage.FAILED_SAFE,
        OwnerStartupFailure.SYSTEM_TRAY_UNAVAILABLE,
    )
    rendered = (tmp_path / "checkpoint.json").read_text(encoding="utf-8")

    assert _SENSITIVE_TEXT not in rendered
    assert "system_tray_unavailable" in rendered
    assert set(json.loads(rendered)) == {
        "events",
        "owner_ui_readiness_checkpoint",
        "schema_version",
        "session_nonce",
        "value_text_recorded",
    }
