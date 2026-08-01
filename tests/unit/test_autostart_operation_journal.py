from __future__ import annotations

import json
from pathlib import Path

import pytest

from sjtuclaw.application.autostart_operation_journal import (
    AutostartOperationContext,
    AutostartOperationEvent,
    AutostartOperationJournal,
    AutostartOperationJournalError,
    AutostartOperationOrigin,
    AutostartOperationRuntimeState,
)
from sjtuclaw.application.autostart_service import AutostartService
from sjtuclaw.presentation.qt.autostart_operation_diagnostics import (
    AutostartOperationDiagnosticArgumentError,
    prepare_autostart_operation_diagnostic_launch,
)


class _Backend:
    def __init__(self) -> None:
        self.value: object | None = None
        self.read_count = 0
        self.write_count = 0
        self.delete_count = 0

    def read_value(self) -> object | None:
        self.read_count += 1
        return self.value

    def write_value(self, command: str) -> None:
        from sjtuclaw.application.autostart_service import (
            REGISTRY_STRING_VALUE_TYPE,
            AutostartStoredValue,
        )

        self.write_count += 1
        self.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            command,
        )

    def delete_value(self) -> None:
        self.delete_count += 1
        self.value = None


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_journal_uses_exact_redacted_schema_and_monotonic_sequence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "operations.jsonl"
    journal = AutostartOperationJournal(path, "a" * 32)
    context = AutostartOperationContext(
        operation_id="operation-1",
        command_id="command-1",
        origin=AutostartOperationOrigin.SETTINGS_CHECKBOX,
        requested_enabled=True,
        controller_revision=7,
    )

    journal.record(
        AutostartOperationEvent.UI_REQUEST_ACCEPTED,
        context,
        runtime_state=AutostartOperationRuntimeState.GUI,
    )
    journal.record(
        AutostartOperationEvent.COMMAND_SUBMITTED,
        context,
        runtime_state=AutostartOperationRuntimeState.RUNTIME_READY,
    )

    events = _read_lines(path)
    assert [event["sequence"] for event in events] == [1, 2]
    assert set(events[0]) == {
        "schema_version",
        "sequence",
        "nonce",
        "event",
        "operation_id",
        "command_id",
        "origin",
        "requested_enabled",
        "controller_revision",
        "runtime_state",
        "result_code",
    }
    combined = path.read_text("utf-8")
    assert "C:\\" not in combined
    assert "--startup" not in combined
    assert "Authorization" not in combined
    assert not list(tmp_path.glob("*.part"))


def test_delete_is_blocked_when_entered_event_cannot_be_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast

    from sjtuclaw.application.autostart_service import AutostartBackend

    executable = tmp_path / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    backend = _Backend()
    journal = AutostartOperationJournal(tmp_path / "journal.jsonl", "b" * 32)
    service = AutostartService(
        cast(AutostartBackend, backend),
        lambda: executable,
        platform_supported=True,
        packaged_runtime_probe=lambda: True,
        operation_journal=journal,
    )
    context = AutostartOperationContext(
        operation_id="enable",
        command_id="enable-command",
        requested_enabled=True,
    )
    assert service.set_enabled(True, context).success

    original_record = journal.record

    def fail_on_delete(
        event: AutostartOperationEvent,
        *args: object,
        **kwargs: object,
    ) -> None:
        if event is AutostartOperationEvent.BACKEND_DELETE_ENTERED:
            raise AutostartOperationJournalError
        original_record(event, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(journal, "record", fail_on_delete)
    result = service.set_enabled(
        False,
        AutostartOperationContext(
            operation_id="disable",
            command_id="disable-command",
            requested_enabled=False,
        ),
    )

    assert not result.success
    assert result.safe_code == "autostart_diagnostic_journal_failed"
    assert backend.delete_count == 0


def test_external_delete_has_no_application_delete_event(
    tmp_path: Path,
) -> None:
    from typing import cast

    from sjtuclaw.application.autostart_service import AutostartBackend

    executable = tmp_path / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    backend = _Backend()
    path = tmp_path / "journal.jsonl"
    journal = AutostartOperationJournal(path, "c" * 32)
    service = AutostartService(
        cast(AutostartBackend, backend),
        lambda: executable,
        platform_supported=True,
        packaged_runtime_probe=lambda: True,
        operation_journal=journal,
    )
    assert service.set_enabled(
        True,
        AutostartOperationContext(requested_enabled=True),
    ).success

    backend.value = None
    service.query(AutostartOperationContext())

    names = [event["event"] for event in _read_lines(path)]
    assert AutostartOperationEvent.BACKEND_DELETE_ENTERED.value not in names
    assert AutostartOperationEvent.BACKEND_DELETE_COMPLETED.value not in names


def test_backend_delete_is_correlated_only_to_explicit_disable(
    tmp_path: Path,
) -> None:
    from typing import cast

    from sjtuclaw.application.autostart_service import AutostartBackend

    executable = tmp_path / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    backend = _Backend()
    path = tmp_path / "journal.jsonl"
    journal = AutostartOperationJournal(path, "e" * 32)
    service = AutostartService(
        cast(AutostartBackend, backend),
        lambda: executable,
        platform_supported=True,
        packaged_runtime_probe=lambda: True,
        operation_journal=journal,
    )
    enable = AutostartOperationContext(
        operation_id="enable-operation",
        command_id="enable-command",
        origin=AutostartOperationOrigin.SETTINGS_CHECKBOX,
        requested_enabled=True,
        controller_revision=1,
    )
    disable = AutostartOperationContext(
        operation_id="disable-operation",
        command_id="disable-command",
        origin=AutostartOperationOrigin.TRAY_ACTION,
        requested_enabled=False,
        controller_revision=2,
    )

    assert service.set_enabled(True, enable).success
    assert backend.delete_count == 0
    assert service.set_enabled(False, disable).success
    assert backend.delete_count == 1

    deletes = [
        event
        for event in _read_lines(path)
        if event["event"]
        in {
            AutostartOperationEvent.BACKEND_DELETE_ENTERED.value,
            AutostartOperationEvent.BACKEND_DELETE_COMPLETED.value,
        }
    ]
    assert len(deletes) == 2
    assert {event["operation_id"] for event in deletes} == {
        "disable-operation"
    }
    assert {event["command_id"] for event in deletes} == {
        "disable-command"
    }
    assert {event["requested_enabled"] for event in deletes} == {False}


def test_operation_diagnostic_is_default_off_and_exact_opt_in(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    (root / "build").mkdir(parents=True)
    executable = root / "dist" / "SJTUClaw.dist" / "SJTUClaw.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"offline-placeholder")

    normal = prepare_autostart_operation_diagnostic_launch(
        [str(executable)],
        executable=executable,
    )
    assert normal.journal is None
    assert not (root / "build" / "autostart-operation-journal").exists()

    diagnostic = prepare_autostart_operation_diagnostic_launch(
        [str(executable), "--diagnose-autostart-operations", "d" * 32],
        executable=executable,
    )
    assert diagnostic.arguments == (str(executable),)
    assert diagnostic.journal is not None

    with pytest.raises(AutostartOperationDiagnosticArgumentError):
        prepare_autostart_operation_diagnostic_launch(
            [str(executable), "--diagnose-autostart-operations", "bad"],
            executable=executable,
        )
