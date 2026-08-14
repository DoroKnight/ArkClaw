from __future__ import annotations

import os
import stat
import sys
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from arkclaw.application.system.autostart_eligibility import (
    AutostartEligibilityReason,
)
from arkclaw.application.system.autostart_service import (
    AUTOSTART_ARGUMENT,
    AUTOSTART_VALUE_NAME,
    REGISTRY_STRING_VALUE_TYPE,
    AutostartService,
    AutostartStatus,
    AutostartStoredValue,
    _path_text_is_safe,
)
from arkclaw.bootstrap import autostart as autostart_bootstrap


class _FakeBackend:
    def __init__(
        self,
        value: AutostartStoredValue | None = None,
    ) -> None:
        self.value = value
        self.read_count = 0
        self.writes: list[str] = []
        self.delete_count = 0
        self.fail_read = False
        self.fail_write = False
        self.fail_delete = False
        self.replacement_after_write: AutostartStoredValue | None = None
        self.replacement_after_delete: AutostartStoredValue | None = None

    def read_value(self) -> AutostartStoredValue | None:
        self.read_count += 1
        if self.fail_read:
            raise OSError("unsafe-registry-value-never-display")
        return self.value

    def write_value(self, command: str) -> None:
        if self.fail_write:
            raise OSError("unsafe-registry-value-never-display")
        self.writes.append(command)
        self.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            command,
        )
        if self.replacement_after_write is not None:
            self.value = self.replacement_after_write

    def delete_value(self) -> None:
        if self.fail_delete:
            raise OSError("unsafe-registry-value-never-display")
        self.delete_count += 1
        self.value = self.replacement_after_delete


def _packaged_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "ArkClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    return executable


def _service(
    backend: _FakeBackend,
    executable: Path,
    *,
    packaged_runtime: bool = True,
) -> AutostartService:
    return AutostartService(
        backend,
        lambda: executable,
        platform_supported=True,
        packaged_runtime_probe=lambda: packaged_runtime,
    )


def test_query_is_read_only_and_defaults_to_disabled(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = _service(backend, _packaged_executable(tmp_path))

    snapshot = service.query()

    assert snapshot.status is AutostartStatus.DISABLED
    assert snapshot.enabled is False
    assert backend.read_count == 1
    assert backend.writes == []
    assert backend.delete_count == 0
    assert AUTOSTART_VALUE_NAME == "ArkClaw"


def test_unsupported_platform_is_unavailable_without_backend_access(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = AutostartService(
        backend,
        lambda: _packaged_executable(tmp_path),
        platform_supported=False,
    )

    snapshot = service.query()

    assert snapshot.status is AutostartStatus.UNAVAILABLE
    assert snapshot.user_toggle_allowed is False
    assert backend.read_count == 0
    assert backend.writes == []
    assert backend.delete_count == 0


def test_enable_writes_only_the_fixed_verified_command(
    tmp_path: Path,
) -> None:
    executable = _packaged_executable(tmp_path)
    backend = _FakeBackend()
    service = _service(backend, executable)
    assert service.query().status is AutostartStatus.DISABLED

    result = service.set_enabled(True)

    assert result.success is True
    assert result.snapshot.status is AutostartStatus.ENABLED
    assert backend.writes == [f'"{executable}" {AUTOSTART_ARGUMENT}']
    assert backend.read_count == 3
    assert backend.delete_count == 0


def test_occupied_value_is_neither_overwritten_nor_deleted(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend(
        AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            '"C:\\Other\\other.exe" --startup',
        )
    )
    service = _service(backend, _packaged_executable(tmp_path))

    snapshot = service.query()
    result = service.set_enabled(True)

    assert snapshot.status is AutostartStatus.OCCUPIED
    assert result.success is False
    assert result.snapshot.status is AutostartStatus.OCCUPIED
    assert result.safe_code == "autostart_entry_occupied"
    assert backend.writes == []
    assert backend.delete_count == 0
    assert "C:\\Other\\other.exe" not in repr(backend.value)


def test_disable_refuses_value_changed_after_ownership(
    tmp_path: Path,
) -> None:
    executable = _packaged_executable(tmp_path)
    backend = _FakeBackend()
    service = _service(backend, executable)
    assert service.set_enabled(True).success is True
    backend.value = AutostartStoredValue(
        REGISTRY_STRING_VALUE_TYPE,
        '"C:\\Other\\other.exe" --startup',
    )

    result = service.set_enabled(False)

    assert result.success is False
    assert result.snapshot.status is AutostartStatus.OWNERSHIP_LOST
    assert result.safe_code == "autostart_ownership_lost"
    assert backend.delete_count == 0


def test_write_failure_restores_last_determined_state(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = _service(backend, _packaged_executable(tmp_path))
    original = service.query()
    backend.fail_write = True

    result = service.set_enabled(True)

    assert result.success is False
    assert result.snapshot == original
    assert result.safe_code == "autostart_write_failed"
    combined = f"{result!r} {result.safe_message}"
    assert "unsafe-registry-value-never-display" not in combined


def test_write_success_with_external_replacement_loses_ownership(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    backend.replacement_after_write = AutostartStoredValue(
        REGISTRY_STRING_VALUE_TYPE,
        '"C:\\Other\\other.exe" --startup',
    )
    service = _service(backend, _packaged_executable(tmp_path))

    result = service.set_enabled(True)
    second = service.set_enabled(False)

    assert result.success is False
    assert result.snapshot.status is AutostartStatus.OWNERSHIP_LOST
    assert result.safe_code == "autostart_write_verification_failed"
    assert second.success is False
    assert second.safe_code == "autostart_ownership_lost"
    assert backend.delete_count == 0


def test_delete_failure_restores_enabled_state(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = _service(backend, _packaged_executable(tmp_path))
    assert service.set_enabled(True).success is True
    backend.fail_delete = True

    result = service.set_enabled(False)

    assert result.success is False
    assert result.snapshot.status is AutostartStatus.ENABLED
    assert result.safe_code == "autostart_delete_failed"
    assert backend.delete_count == 0


def test_external_replacement_is_reported_by_later_query(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = _service(backend, _packaged_executable(tmp_path))
    assert service.set_enabled(True).success is True
    backend.value = AutostartStoredValue(
        REGISTRY_STRING_VALUE_TYPE,
        '"C:\\Other\\other.exe" --startup',
    )

    snapshot = service.query()

    assert snapshot.status is AutostartStatus.OWNERSHIP_LOST
    assert backend.delete_count == 0
    assert backend.writes != []


def test_external_deletion_after_ownership_is_not_silently_disabled(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = _service(backend, _packaged_executable(tmp_path))
    assert service.set_enabled(True).success is True
    backend.value = None

    snapshot = service.query()
    result = service.set_enabled(False)

    assert snapshot.status is AutostartStatus.OWNERSHIP_LOST
    assert result.success is False
    assert result.safe_code == "autostart_ownership_lost"
    assert backend.delete_count == 0


def test_wrong_registry_type_is_occupied(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend(AutostartStoredValue(7, None))
    service = _service(backend, _packaged_executable(tmp_path))

    assert service.query().status is AutostartStatus.OCCUPIED
    assert backend.writes == []
    assert backend.delete_count == 0


def test_backend_read_failure_returns_only_safe_error(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    backend.fail_read = True
    service = _service(backend, _packaged_executable(tmp_path))

    snapshot = service.query()

    assert snapshot.status is AutostartStatus.ERROR
    assert snapshot.safe_code == "autostart_backend_error"
    assert "unsafe-registry-value-never-display" not in repr(snapshot)
    assert "unsafe-registry-value-never-display" not in snapshot.safe_message
    assert backend.writes == []
    assert backend.delete_count == 0


def test_non_packaged_executable_disables_registration(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"offline-placeholder")
    backend = _FakeBackend()
    service = _service(backend, python)

    snapshot = service.query()
    result = service.set_enabled(True)

    assert snapshot.status is AutostartStatus.INVALID_EXECUTABLE
    assert result.success is False
    assert result.safe_code == "autostart_invalid_executable"
    assert backend.read_count == 0
    assert backend.writes == []


def test_development_file_named_like_packaged_executable_is_rejected(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    service = _service(
        backend,
        _packaged_executable(tmp_path),
        packaged_runtime=False,
    )

    assert service.query().status is AutostartStatus.INVALID_EXECUTABLE
    assert backend.read_count == 0
    assert backend.writes == []


def test_packaged_runtime_probe_failure_is_safely_rejected(
    tmp_path: Path,
) -> None:
    executable = _packaged_executable(tmp_path)
    backend = _FakeBackend()

    def fail_probe() -> bool:
        raise OSError("unsafe-runtime-detail-never-display")

    service = AutostartService(
        backend,
        lambda: executable,
        platform_supported=True,
        packaged_runtime_probe=fail_probe,
    )

    snapshot = service.query()

    assert snapshot.status is AutostartStatus.INVALID_EXECUTABLE
    assert "unsafe-runtime-detail-never-display" not in repr(snapshot)
    assert backend.read_count == 0


def test_unicode_and_space_path_is_quoted_without_extra_arguments(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "桌宠 build"
    directory.mkdir()
    executable = _packaged_executable(directory)
    backend = _FakeBackend()
    service = _service(backend, executable)

    result = service.set_enabled(True)

    assert result.success is True
    assert backend.writes == [f'"{executable}" --startup']


def test_unsafe_command_path_text_is_rejected() -> None:
    assert not _path_text_is_safe(r"\\server\share\ArkClaw.exe")
    assert not _path_text_is_safe('"C:\\Apps\\ArkClaw.exe"')
    assert not _path_text_is_safe("C:\\Apps\\ArkClaw.exe\n--extra")
    assert _path_text_is_safe("C:\\Apps\\桌宠 ArkClaw.exe")


def test_command_over_fixed_length_limit_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arkclaw.application.system import autostart_service

    executable = _packaged_executable(tmp_path)
    backend = _FakeBackend()
    command = f'"{executable}" --startup'
    monkeypatch.setattr(
        autostart_service,
        "_MAX_AUTOSTART_COMMAND_LENGTH",
        len(command) - 1,
    )
    service = _service(backend, executable)

    assert service.query().status is AutostartStatus.INVALID_EXECUTABLE
    assert backend.read_count == 0


def test_nuitka_runtime_probe_rejects_source_forgery_and_onefile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _packaged_executable(tmp_path)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.delattr(
        autostart_bootstrap,
        "__compiled__",
        raising=False,
    )
    assert (
        autostart_bootstrap._is_supported_nuitka_standalone_runtime()
        is False
    )
    assert (
        autostart_bootstrap.diagnose_production_autostart_eligibility().reason
        is AutostartEligibilityReason.MARKER_MISSING
    )
    monkeypatch.setattr(
        autostart_bootstrap,
        "__compiled__",
        SimpleNamespace(
            standalone=True,
            onefile=False,
            containing_dir=str(tmp_path),
        ),
        raising=False,
    )
    assert (
        autostart_bootstrap._is_supported_nuitka_standalone_runtime()
        is False
    )
    assert (
        autostart_bootstrap.diagnose_production_autostart_eligibility().reason
        is AutostartEligibilityReason.MARKER_TYPE_MISMATCH
    )
    marker_type = namedtuple(
        "marker_type",
        "standalone onefile containing_dir",
    )
    marker_type.__name__ = "__nuitka_version__"
    monkeypatch.setattr(
        autostart_bootstrap,
        "__compiled__",
        marker_type(True, True, str(tmp_path)),
        raising=False,
    )
    assert (
        autostart_bootstrap._is_supported_nuitka_standalone_runtime()
        is False
    )
    assert (
        autostart_bootstrap.diagnose_production_autostart_eligibility().reason
        is AutostartEligibilityReason.ONEFILE_MODE_INVALID
    )
    monkeypatch.setattr(
        autostart_bootstrap,
        "__compiled__",
        marker_type(True, False, str(tmp_path.parent)),
    )
    assert (
        autostart_bootstrap._is_supported_nuitka_standalone_runtime()
        is True
    )
    assert (
        autostart_bootstrap.diagnose_production_autostart_eligibility().reason
        is AutostartEligibilityReason.SUPPORTED
    )


def test_packaged_diagnostic_includes_executable_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "wrong-name.exe"
    executable.write_bytes(b"offline-placeholder")
    marker_type = namedtuple(
        "marker_type",
        "standalone onefile containing_dir",
    )
    marker_type.__name__ = "__nuitka_version__"
    monkeypatch.setattr(
        autostart_bootstrap,
        "__compiled__",
        marker_type(
            standalone=True,
            onefile=False,
            containing_dir=str(tmp_path.parent),
        ),
        raising=False,
    )

    result = autostart_bootstrap.diagnose_production_autostart_eligibility(
        executable
    )

    assert result.reason is AutostartEligibilityReason.EXECUTABLE_NAME_INVALID


def test_source_virtual_environment_is_rejected(
    tmp_path: Path,
) -> None:
    executable = tmp_path / ".venv" / "ArkClaw.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"offline-placeholder")
    backend = _FakeBackend()
    service = _service(backend, executable)

    assert service.query().status is AutostartStatus.INVALID_EXECUTABLE
    assert backend.read_count == 0


def test_reparse_point_executable_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _packaged_executable(tmp_path)
    original = executable.lstat()
    reparse_metadata = SimpleNamespace(
        st_mode=stat.S_IFREG,
        st_nlink=original.st_nlink,
        st_file_attributes=0x400,
    )

    def fake_lstat(path: Path) -> os.stat_result:
        del path
        return cast(os.stat_result, reparse_metadata)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    backend = _FakeBackend()
    service = _service(backend, executable)

    assert service.query().status is AutostartStatus.INVALID_EXECUTABLE
    assert backend.read_count == 0


def test_delete_followed_by_external_replacement_loses_ownership(
    tmp_path: Path,
) -> None:
    executable = _packaged_executable(tmp_path)
    backend = _FakeBackend()
    service = _service(backend, executable)
    assert service.set_enabled(True).success is True
    expected = backend.value
    assert expected is not None
    backend.replacement_after_delete = expected

    result = service.set_enabled(False)
    second = service.set_enabled(False)

    assert result.success is False
    assert result.snapshot.status is AutostartStatus.OWNERSHIP_LOST
    assert result.safe_code == "autostart_ownership_lost"
    assert second.success is False
    assert second.safe_code == "autostart_ownership_lost"
    assert backend.delete_count == 1
    assert backend.value == expected


def test_ownership_loss_is_sticky_even_if_expected_value_returns(
    tmp_path: Path,
) -> None:
    executable = _packaged_executable(tmp_path)
    backend = _FakeBackend()
    service = _service(backend, executable)
    assert service.set_enabled(True).success is True
    expected = backend.value
    assert expected is not None
    backend.value = AutostartStoredValue(
        REGISTRY_STRING_VALUE_TYPE,
        '"C:\\Other\\other.exe" --startup',
    )
    assert service.query().status is AutostartStatus.OWNERSHIP_LOST
    backend.value = expected

    assert service.query().status is AutostartStatus.OWNERSHIP_LOST
    assert service.set_enabled(False).success is False
    assert backend.delete_count == 0


def test_abnormal_hard_link_executable_is_rejected(
    tmp_path: Path,
) -> None:
    executable = _packaged_executable(tmp_path)
    os.link(executable, tmp_path / "linked-copy.exe")
    backend = _FakeBackend()
    service = _service(backend, executable)

    assert service.query().status is AutostartStatus.INVALID_EXECUTABLE
    assert backend.read_count == 0
