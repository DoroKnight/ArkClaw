"""Non-sensitive eligibility diagnostics for Windows autostart."""

from __future__ import annotations

import stat
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_WINDOWS_REPARSE_POINT_ATTRIBUTE = 0x400
MAX_AUTOSTART_COMMAND_LENGTH = 32_767


class AutostartEligibilityReason(StrEnum):
    """Fixed internal reasons that never retain paths or exception details."""

    MARKER_MISSING = "marker_missing"
    MARKER_TYPE_MISMATCH = "marker_type_mismatch"
    STANDALONE_MODE_INVALID = "standalone_mode_invalid"
    ONEFILE_MODE_INVALID = "onefile_mode_invalid"
    CONTAINING_DIR_INVALID = "containing_dir_invalid"
    EXECUTABLE_UNRESOLVABLE = "executable_unresolvable"
    EXECUTABLE_PARENT_MISMATCH = "executable_parent_mismatch"
    EXECUTABLE_NOT_ABSOLUTE = "executable_not_absolute"
    EXECUTABLE_PATH_MISMATCH = "executable_path_mismatch"
    EXECUTABLE_NOT_REGULAR = "executable_not_regular"
    EXECUTABLE_REPARSE_POINT = "executable_reparse_point"
    EXECUTABLE_HARDLINK_INVALID = "executable_hardlink_invalid"
    EXECUTABLE_NAME_INVALID = "executable_name_invalid"
    VIRTUAL_ENVIRONMENT_PATH_REJECTED = "virtual_environment_path_rejected"
    EXECUTABLE_PATH_UNSAFE = "executable_path_unsafe"
    COMMAND_LENGTH_INVALID = "command_length_invalid"
    SUPPORTED = "supported"


@dataclass(frozen=True, slots=True)
class AutostartEligibilityResult:
    """Immutable result safe for controlled diagnostic serialization."""

    reason: AutostartEligibilityReason

    @property
    def supported(self) -> bool:
        return self.reason is AutostartEligibilityReason.SUPPORTED


@dataclass(frozen=True, slots=True)
class NuitkaRuntimeFacts:
    """Path-free facts used by the pure Nuitka eligibility evaluator."""

    marker_present: bool
    marker_type_matches: bool
    standalone_mode: bool
    onefile_disabled: bool
    containing_dir_valid: bool
    executable_resolvable: bool
    executable_parent_matches: bool


@dataclass(frozen=True, slots=True)
class ExecutableFacts:
    """Path-free facts used by the pure executable eligibility evaluator."""

    executable_resolvable: bool
    executable_absolute: bool
    executable_matches_resolved: bool
    executable_regular: bool
    executable_reparse_point: bool
    executable_hardlink_valid: bool
    executable_name_valid: bool
    virtual_environment_path: bool
    executable_path_safe: bool
    command_length_valid: bool


def evaluate_nuitka_runtime(
    facts: NuitkaRuntimeFacts,
) -> AutostartEligibilityResult:
    """Map path-free Nuitka facts to one fixed fail-closed reason."""

    if not facts.marker_present:
        reason = AutostartEligibilityReason.MARKER_MISSING
    elif not facts.marker_type_matches:
        reason = AutostartEligibilityReason.MARKER_TYPE_MISMATCH
    elif not facts.standalone_mode:
        reason = AutostartEligibilityReason.STANDALONE_MODE_INVALID
    elif not facts.onefile_disabled:
        reason = AutostartEligibilityReason.ONEFILE_MODE_INVALID
    elif not facts.containing_dir_valid:
        reason = AutostartEligibilityReason.CONTAINING_DIR_INVALID
    elif not facts.executable_resolvable:
        reason = AutostartEligibilityReason.EXECUTABLE_UNRESOLVABLE
    elif not facts.executable_parent_matches:
        reason = AutostartEligibilityReason.EXECUTABLE_PARENT_MISMATCH
    else:
        reason = AutostartEligibilityReason.SUPPORTED
    return AutostartEligibilityResult(reason)


def evaluate_executable(
    runtime: AutostartEligibilityResult,
    facts: ExecutableFacts,
) -> AutostartEligibilityResult:
    """Map path-free executable facts without weakening runtime rejection."""

    if not runtime.supported:
        return runtime
    if not facts.executable_resolvable:
        reason = AutostartEligibilityReason.EXECUTABLE_UNRESOLVABLE
    elif not facts.executable_absolute:
        reason = AutostartEligibilityReason.EXECUTABLE_NOT_ABSOLUTE
    elif not facts.executable_matches_resolved:
        reason = AutostartEligibilityReason.EXECUTABLE_PATH_MISMATCH
    elif facts.executable_reparse_point:
        reason = AutostartEligibilityReason.EXECUTABLE_REPARSE_POINT
    elif not facts.executable_regular:
        reason = AutostartEligibilityReason.EXECUTABLE_NOT_REGULAR
    elif not facts.executable_hardlink_valid:
        reason = AutostartEligibilityReason.EXECUTABLE_HARDLINK_INVALID
    elif not facts.executable_name_valid:
        reason = AutostartEligibilityReason.EXECUTABLE_NAME_INVALID
    elif facts.virtual_environment_path:
        reason = AutostartEligibilityReason.VIRTUAL_ENVIRONMENT_PATH_REJECTED
    elif not facts.executable_path_safe:
        reason = AutostartEligibilityReason.EXECUTABLE_PATH_UNSAFE
    elif not facts.command_length_valid:
        reason = AutostartEligibilityReason.COMMAND_LENGTH_INVALID
    else:
        reason = AutostartEligibilityReason.SUPPORTED
    return AutostartEligibilityResult(reason)


def _path_text_is_safe(path_text: str) -> bool:
    return (
        not path_text.startswith("\\\\")
        and '"' not in path_text
        and not any(ord(character) < 32 for character in path_text)
    )


def inspect_nuitka_runtime(
    marker: object | None,
    executable: Path,
) -> AutostartEligibilityResult:
    """Inspect live runtime values while retaining only path-free facts."""

    marker_present = marker is not None
    marker_type_matches = (
        marker_present and type(marker).__name__ == "__nuitka_version__"
    )
    standalone_value: object | None = None
    onefile_value: object | None = None
    containing_dir: object | None = None
    if marker_type_matches:
        with suppress(Exception):
            standalone_value = getattr(marker, "standalone", None)
        with suppress(Exception):
            onefile_value = getattr(marker, "onefile", None)
        with suppress(Exception):
            containing_dir = getattr(marker, "containing_dir", None)
    standalone_mode = standalone_value is True
    onefile_disabled = onefile_value is False
    containing_dir_valid = isinstance(containing_dir, str)
    executable_resolvable = False
    executable_parent_matches = False
    resolved_executable: Path | None = None
    resolved_containing_dir: Path | None = None
    if isinstance(containing_dir, str):
        try:
            resolved_containing_dir = Path(containing_dir).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            containing_dir_valid = False
    try:
        resolved_executable = executable.resolve(strict=True)
        executable_resolvable = True
    except (OSError, RuntimeError, ValueError):
        pass
    if (
        resolved_executable is not None
        and resolved_containing_dir is not None
    ):
        executable_parent_matches = (
            resolved_executable.parent == resolved_containing_dir
        )
    return evaluate_nuitka_runtime(
        NuitkaRuntimeFacts(
            marker_present=marker_present,
            marker_type_matches=marker_type_matches,
            standalone_mode=standalone_mode,
            onefile_disabled=onefile_disabled,
            containing_dir_valid=containing_dir_valid,
            executable_resolvable=executable_resolvable,
            executable_parent_matches=executable_parent_matches,
        )
    )


def inspect_autostart_executable(
    executable: Path,
    runtime: AutostartEligibilityResult,
    *,
    command_length: int,
    maximum_command_length: int,
) -> AutostartEligibilityResult:
    """Inspect one executable while retaining no path or metadata values."""

    try:
        resolved = executable.resolve(strict=True)
        metadata = executable.lstat()
    except (OSError, RuntimeError, ValueError):
        return evaluate_executable(
            runtime,
            ExecutableFacts(
                executable_resolvable=False,
                executable_absolute=False,
                executable_matches_resolved=False,
                executable_regular=False,
                executable_reparse_point=False,
                executable_hardlink_valid=False,
                executable_name_valid=False,
                virtual_environment_path=False,
                executable_path_safe=False,
                command_length_valid=False,
            ),
        )
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    components = {part.casefold() for part in resolved.parts}
    return evaluate_executable(
        runtime,
        ExecutableFacts(
            executable_resolvable=True,
            executable_absolute=executable.is_absolute(),
            executable_matches_resolved=resolved == executable,
            executable_regular=stat.S_ISREG(metadata.st_mode),
            executable_reparse_point=bool(
                file_attributes & _WINDOWS_REPARSE_POINT_ATTRIBUTE
            ),
            executable_hardlink_valid=metadata.st_nlink == 1,
            executable_name_valid=(
                resolved.name.casefold() == "sjtuclaw.exe"
                and resolved.suffix.casefold() == ".exe"
            ),
            virtual_environment_path=(
                ".venv" in components or ".venv-packaging" in components
            ),
            executable_path_safe=_path_text_is_safe(str(resolved)),
            command_length_valid=command_length <= maximum_command_length,
        ),
    )
