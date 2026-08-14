"""Opt-in packaged Owner setup for the redacted autostart journal."""

from __future__ import annotations

import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from arkclaw.application.autostart_operation_journal import (
    AutostartOperationJournal,
)

AUTOSTART_OPERATION_DIAGNOSTIC_ARGUMENT: Final = (
    "--diagnose-autostart-operations"
)
_NONCE_PATTERN: Final = re.compile(r"[0-9a-f]{32}")
_EVIDENCE_DIRECTORY_NAME: Final = "autostart-operation-journal"
_JOURNAL_FILENAME: Final = "operations.jsonl"
_REPARSE_POINT_ATTRIBUTE: Final = 0x400


class AutostartOperationDiagnosticArgumentError(ValueError):
    """Raised when the opt-in operation diagnostic is not exact and safe."""


@dataclass(frozen=True, slots=True)
class AutostartOperationDiagnosticLaunch:
    """Sanitized application arguments and optional diagnostic journal."""

    arguments: tuple[str, ...]
    journal: AutostartOperationJournal | None


def prepare_autostart_operation_diagnostic_launch(
    argv: Sequence[str],
    *,
    executable: Path | None = None,
) -> AutostartOperationDiagnosticLaunch:
    """Create a new repository-local journal only for an exact opt-in."""

    arguments = tuple(argv)
    if AUTOSTART_OPERATION_DIAGNOSTIC_ARGUMENT not in arguments:
        return AutostartOperationDiagnosticLaunch(arguments, None)
    if (
        len(arguments) != 3
        or arguments[1] != AUTOSTART_OPERATION_DIAGNOSTIC_ARGUMENT
        or _NONCE_PATTERN.fullmatch(arguments[2]) is None
    ):
        raise AutostartOperationDiagnosticArgumentError
    executable_path = Path(sys.executable if executable is None else executable)
    root = _repository_root_from_packaged_executable(executable_path)
    parent = root / "build" / _EVIDENCE_DIRECTORY_NAME
    _ensure_safe_directory(parent, create=True)
    evidence = parent / arguments[2]
    if evidence.exists():
        raise AutostartOperationDiagnosticArgumentError
    evidence.mkdir()
    _ensure_safe_directory(evidence, create=False)
    return AutostartOperationDiagnosticLaunch(
        (arguments[0],),
        AutostartOperationJournal(
            evidence / _JOURNAL_FILENAME,
            arguments[2],
        ),
    )


def _repository_root_from_packaged_executable(executable: Path) -> Path:
    resolved = executable.resolve(strict=True)
    if (
        not resolved.is_file()
        or resolved.suffix.casefold() != ".exe"
        or not resolved.parent.name.casefold().endswith(".dist")
        or resolved.parent.parent.name.casefold() != "dist"
        or _is_reparse_point(resolved)
    ):
        raise AutostartOperationDiagnosticArgumentError
    root = resolved.parent.parent.parent
    _ensure_safe_directory(root, create=False)
    _ensure_safe_directory(root / "build", create=False)
    return root


def _ensure_safe_directory(path: Path, *, create: bool) -> None:
    if create:
        path.mkdir(parents=False, exist_ok=True)
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise AutostartOperationDiagnosticArgumentError from None
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_point(path):
        raise AutostartOperationDiagnosticArgumentError


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _REPARSE_POINT_ATTRIBUTE)
