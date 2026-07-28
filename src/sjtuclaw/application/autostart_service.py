"""Framework-free ownership boundary for optional Windows autostart."""

from __future__ import annotations

import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

AUTOSTART_VALUE_NAME = "SJTUClaw"
AUTOSTART_ARGUMENT = "--startup"
REGISTRY_STRING_VALUE_TYPE = 1
_WINDOWS_REPARSE_POINT_ATTRIBUTE = 0x400
_MAX_AUTOSTART_COMMAND_LENGTH = 32_767


class AutostartStatus(StrEnum):
    """Safe UI-visible state of the fixed SJTUClaw startup registration."""

    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    ENABLED = "enabled"
    OCCUPIED = "occupied"
    OWNERSHIP_LOST = "ownership_lost"
    INVALID_EXECUTABLE = "invalid_executable"
    ERROR = "error"


_STATUS_DETAILS: dict[AutostartStatus, tuple[str, str]] = {
    AutostartStatus.UNAVAILABLE: (
        "autostart_unavailable",
        "Autostart is unavailable on this platform or runtime.",
    ),
    AutostartStatus.DISABLED: (
        "autostart_disabled",
        "SJTUClaw is not registered to start when you sign in.",
    ),
    AutostartStatus.ENABLED: (
        "autostart_enabled",
        "SJTUClaw is registered to start when you sign in.",
    ),
    AutostartStatus.OCCUPIED: (
        "autostart_entry_occupied",
        "The SJTUClaw startup entry is occupied by another value.",
    ),
    AutostartStatus.OWNERSHIP_LOST: (
        "autostart_ownership_lost",
        "The SJTUClaw startup entry changed outside this application.",
    ),
    AutostartStatus.INVALID_EXECUTABLE: (
        "autostart_invalid_executable",
        "Autostart is available only from the packaged SJTUClaw executable.",
    ),
    AutostartStatus.ERROR: (
        "autostart_backend_error",
        "The autostart setting could not be accessed safely.",
    ),
}


@dataclass(frozen=True, slots=True)
class AutostartSnapshot:
    """Non-sensitive state safe to send to Qt widgets."""

    status: AutostartStatus
    safe_code: str
    safe_message: str

    @classmethod
    def for_status(cls, status: AutostartStatus) -> AutostartSnapshot:
        safe_code, safe_message = _STATUS_DETAILS[status]
        return cls(status, safe_code, safe_message)

    @property
    def enabled(self) -> bool:
        return self.status is AutostartStatus.ENABLED

    @property
    def user_toggle_allowed(self) -> bool:
        return self.status in {
            AutostartStatus.DISABLED,
            AutostartStatus.ENABLED,
        }


@dataclass(frozen=True, slots=True)
class AutostartStoredValue:
    """Internal registry value whose command is excluded from repr."""

    value_type: int
    command: str | None = field(repr=False)


class AutostartBackend(Protocol):
    """Minimal fixed-value persistence port."""

    def read_value(self) -> AutostartStoredValue | None: ...

    def write_value(self, command: str) -> None: ...

    def delete_value(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AutostartOperationResult:
    """Result retaining the last safe UI state on backend failure."""

    success: bool
    snapshot: AutostartSnapshot
    safe_code: str
    safe_message: str

    @classmethod
    def completed(
        cls,
        snapshot: AutostartSnapshot,
    ) -> AutostartOperationResult:
        return cls(True, snapshot, "none", "")

    @classmethod
    def failed(
        cls,
        snapshot: AutostartSnapshot,
        safe_code: str,
        safe_message: str,
    ) -> AutostartOperationResult:
        return cls(False, snapshot, safe_code, safe_message)


ExecutableResolver = Callable[[], Path]
PackagedRuntimeProbe = Callable[[], bool]


def _path_text_is_safe(path_text: str) -> bool:
    return (
        not path_text.startswith("\\\\")
        and '"' not in path_text
        and not any(ord(character) < 32 for character in path_text)
    )


class AutostartService:
    """Own and verify one fixed per-user startup registration."""

    def __init__(
        self,
        backend: AutostartBackend | None,
        executable_resolver: ExecutableResolver,
        *,
        platform_supported: bool,
        packaged_runtime_probe: PackagedRuntimeProbe | None = None,
    ) -> None:
        self._backend = backend
        self._executable_resolver = executable_resolver
        self._platform_supported = platform_supported
        self._packaged_runtime_probe = (
            packaged_runtime_probe or (lambda: False)
        )
        self._ownership_confirmed = False
        self._ownership_lost = False
        self._snapshot = AutostartSnapshot.for_status(
            AutostartStatus.UNAVAILABLE
        )

    @property
    def snapshot(self) -> AutostartSnapshot:
        return self._snapshot

    def query(self) -> AutostartSnapshot:
        """Read and classify the fixed value without writing anything."""

        expected = self._expected_command()
        if expected is None:
            return self._snapshot
        stored = self._read_value()
        if isinstance(stored, _BackendFailure):
            return self._snapshot
        return self._classify(stored, expected)

    def set_enabled(self, enabled: bool) -> AutostartOperationResult:
        """Apply one explicit user choice and verify the resulting value."""

        previous = self._snapshot
        expected = self._expected_command()
        if expected is None:
            return AutostartOperationResult.failed(
                self._snapshot,
                self._snapshot.safe_code,
                self._snapshot.safe_message,
            )
        if self._ownership_lost:
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.OWNERSHIP_LOST
            )
            return AutostartOperationResult.failed(
                self._snapshot,
                self._snapshot.safe_code,
                self._snapshot.safe_message,
            )
        stored = self._read_value()
        if isinstance(stored, _BackendFailure):
            self._snapshot = previous
            return AutostartOperationResult.failed(
                previous,
                "autostart_backend_error",
                "The autostart setting could not be accessed safely.",
            )
        if enabled:
            return self._enable(previous, stored, expected)
        return self._disable(previous, stored, expected)

    def _expected_command(self) -> str | None:
        if not self._platform_supported or self._backend is None:
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.UNAVAILABLE
            )
            return None
        try:
            packaged_runtime = self._packaged_runtime_probe()
            executable = self._executable_resolver()
            resolved = executable.resolve(strict=True)
            metadata = executable.lstat()
        except Exception:
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.INVALID_EXECUTABLE
            )
            return None
        file_attributes = getattr(metadata, "st_file_attributes", 0)
        components = {part.casefold() for part in resolved.parts}
        resolved_text = str(resolved)
        command = f'"{resolved_text}" {AUTOSTART_ARGUMENT}'
        valid = (
            packaged_runtime is True
            and executable.is_absolute()
            and resolved == executable
            and stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and not executable.is_symlink()
            and not file_attributes & _WINDOWS_REPARSE_POINT_ATTRIBUTE
            and _path_text_is_safe(resolved_text)
            and resolved.name.casefold() == "sjtuclaw.exe"
            and resolved.suffix.casefold() == ".exe"
            and ".venv" not in components
            and ".venv-packaging" not in components
            and len(command) <= _MAX_AUTOSTART_COMMAND_LENGTH
        )
        if not valid:
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.INVALID_EXECUTABLE
            )
            return None
        return command

    def _read_value(
        self,
    ) -> AutostartStoredValue | _BackendFailure | None:
        assert self._backend is not None
        try:
            return self._backend.read_value()
        except Exception:
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.ERROR
            )
            return _BACKEND_FAILURE

    def _classify(
        self,
        stored: AutostartStoredValue | None,
        expected: str,
    ) -> AutostartSnapshot:
        if self._ownership_lost:
            status = AutostartStatus.OWNERSHIP_LOST
        elif stored is None:
            status = (
                AutostartStatus.OWNERSHIP_LOST
                if self._ownership_confirmed
                else AutostartStatus.DISABLED
            )
            if status is AutostartStatus.OWNERSHIP_LOST:
                self._ownership_lost = True
        elif (
            stored.value_type == REGISTRY_STRING_VALUE_TYPE
            and stored.command == expected
        ):
            self._ownership_confirmed = True
            status = AutostartStatus.ENABLED
        elif self._ownership_confirmed:
            self._ownership_lost = True
            status = AutostartStatus.OWNERSHIP_LOST
        else:
            status = AutostartStatus.OCCUPIED
        self._snapshot = AutostartSnapshot.for_status(status)
        return self._snapshot

    def _enable(
        self,
        previous: AutostartSnapshot,
        stored: AutostartStoredValue | None,
        expected: str,
    ) -> AutostartOperationResult:
        if stored is not None:
            snapshot = self._classify(stored, expected)
            if snapshot.status is AutostartStatus.ENABLED:
                return AutostartOperationResult.completed(snapshot)
            return AutostartOperationResult.failed(
                snapshot,
                snapshot.safe_code,
                snapshot.safe_message,
            )
        assert self._backend is not None
        try:
            self._backend.write_value(expected)
        except Exception:
            self._snapshot = previous
            return AutostartOperationResult.failed(
                previous,
                "autostart_write_failed",
                "The autostart setting could not be enabled safely.",
            )
        self._ownership_confirmed = True
        verified = self._read_value()
        if isinstance(verified, _BackendFailure):
            self._snapshot = previous
            return AutostartOperationResult.failed(
                previous,
                "autostart_write_verification_failed",
                "The autostart setting could not be verified safely.",
            )
        snapshot = self._classify(verified, expected)
        if snapshot.status is not AutostartStatus.ENABLED:
            return AutostartOperationResult.failed(
                snapshot,
                "autostart_write_verification_failed",
                "The autostart setting could not be verified safely.",
            )
        return AutostartOperationResult.completed(snapshot)

    def _disable(
        self,
        previous: AutostartSnapshot,
        stored: AutostartStoredValue | None,
        expected: str,
    ) -> AutostartOperationResult:
        if stored is None:
            snapshot = self._classify(None, expected)
            if snapshot.status is AutostartStatus.OWNERSHIP_LOST:
                return AutostartOperationResult.failed(
                    snapshot,
                    snapshot.safe_code,
                    snapshot.safe_message,
                )
            return AutostartOperationResult.completed(snapshot)
        if (
            stored.value_type != REGISTRY_STRING_VALUE_TYPE
            or stored.command != expected
        ):
            self._ownership_lost = True
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.OWNERSHIP_LOST
            )
            return AutostartOperationResult.failed(
                self._snapshot,
                self._snapshot.safe_code,
                self._snapshot.safe_message,
            )
        assert self._backend is not None
        try:
            self._backend.delete_value()
        except Exception:
            self._snapshot = previous
            return AutostartOperationResult.failed(
                previous,
                "autostart_delete_failed",
                "The autostart setting could not be disabled safely.",
            )
        verified = self._read_value()
        if isinstance(verified, _BackendFailure):
            self._snapshot = previous
            return AutostartOperationResult.failed(
                previous,
                "autostart_delete_verification_failed",
                "The autostart setting could not be verified safely.",
            )
        if verified is not None:
            self._ownership_lost = True
            self._snapshot = AutostartSnapshot.for_status(
                AutostartStatus.OWNERSHIP_LOST
            )
            return AutostartOperationResult.failed(
                self._snapshot,
                self._snapshot.safe_code,
                self._snapshot.safe_message,
            )
        self._ownership_confirmed = False
        self._ownership_lost = False
        snapshot = self._classify(None, expected)
        return AutostartOperationResult.completed(snapshot)


@dataclass(frozen=True, slots=True)
class _BackendFailure:
    pass


_BACKEND_FAILURE = _BackendFailure()
