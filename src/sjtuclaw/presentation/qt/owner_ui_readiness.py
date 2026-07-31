"""Opt-in, redacted checkpoints for packaged Owner UI readiness."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

OWNER_UI_DIAGNOSTIC_ARGUMENT: Final = "--diagnose-owner-ui-readiness"
_SCHEMA_VERSION: Final = 1
_NONCE_PATTERN: Final = re.compile(r"[0-9a-f]{32}")
_EVIDENCE_DIRECTORY_NAME: Final = "autostart-owner-ui-readiness"
_CHECKPOINT_FILENAME: Final = "checkpoint.json"
_PART_FILENAME: Final = "checkpoint.json.part"
_REPARSE_POINT_ATTRIBUTE: Final = 0x400


class OwnerStartupStage(StrEnum):
    """Ordered, non-sensitive stages reached by an Owner GUI process."""

    STARTED = "started"
    ARGUMENTS_VALIDATED = "arguments_validated"
    SINGLE_INSTANCE_OWNER = "single_instance_owner"
    COMPOSITION_ROOT_CREATED = "composition_root_created"
    RUNTIME_STARTING = "runtime_starting"
    PET_WINDOW_CREATED = "pet_window_created"
    SETTINGS_LOADED = "settings_loaded"
    PET_WINDOW_VISIBLE = "pet_window_visible"
    TRAY_CREATED = "tray_created"
    TRAY_VISIBLE = "tray_visible"
    RUNTIME_READY = "runtime_ready"
    APPLICATION_READY = "application_ready"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED_SAFE = "failed_safe"


class OwnerStartupFailure(StrEnum):
    """Fixed failure categories that never contain dynamic values."""

    NONE = "none"
    ARGUMENTS_INVALID = "arguments_invalid"
    SINGLE_INSTANCE_SECONDARY = "single_instance_secondary"
    SINGLE_INSTANCE_FAILED = "single_instance_failed"
    RUNTIME_NOT_READY = "runtime_not_ready"
    PET_WINDOW_NOT_CREATED = "pet_window_not_created"
    PET_WINDOW_NOT_VISIBLE = "pet_window_not_visible"
    PET_WINDOW_OUTSIDE_WORKSPACE = "pet_window_outside_workspace"
    SYSTEM_TRAY_UNAVAILABLE = "system_tray_unavailable"
    TRAY_NOT_CREATED = "tray_not_created"
    TRAY_NOT_VISIBLE = "tray_not_visible"
    APPLICATION_READY_MISSING = "application_ready_missing"
    CHECKPOINT_WRITE_FAILED = "checkpoint_write_failed"


_STAGE_ORDER: Final = {
    stage: index
    for index, stage in enumerate(
        (
            OwnerStartupStage.STARTED,
            OwnerStartupStage.ARGUMENTS_VALIDATED,
            OwnerStartupStage.SINGLE_INSTANCE_OWNER,
            OwnerStartupStage.COMPOSITION_ROOT_CREATED,
            OwnerStartupStage.RUNTIME_STARTING,
            OwnerStartupStage.PET_WINDOW_CREATED,
            OwnerStartupStage.SETTINGS_LOADED,
            OwnerStartupStage.PET_WINDOW_VISIBLE,
            OwnerStartupStage.TRAY_CREATED,
            OwnerStartupStage.TRAY_VISIBLE,
            OwnerStartupStage.RUNTIME_READY,
            OwnerStartupStage.APPLICATION_READY,
            OwnerStartupStage.CLOSING,
            OwnerStartupStage.CLOSED,
        ),
        start=1,
    )
}


class OwnerUiDiagnosticArgumentError(ValueError):
    """Raised for an invalid opt-in diagnostic invocation."""


@dataclass(frozen=True, slots=True)
class OwnerUiReadinessSnapshot:
    """Framework-independent readiness facts used by the T1 gate."""

    instance_owner: bool
    runtime_ready: bool
    pet_window_constructed: bool
    pet_window_visible: bool
    pet_window_in_workspace: bool
    tray_constructed: bool
    tray_available: bool
    tray_visible: bool
    application_ready: bool


def classify_owner_ui_readiness(
    snapshot: OwnerUiReadinessSnapshot,
) -> OwnerStartupFailure:
    """Return the first fixed readiness failure without dynamic details."""

    if not snapshot.instance_owner:
        return OwnerStartupFailure.SINGLE_INSTANCE_SECONDARY
    if not snapshot.runtime_ready:
        return OwnerStartupFailure.RUNTIME_NOT_READY
    if not snapshot.pet_window_constructed:
        return OwnerStartupFailure.PET_WINDOW_NOT_CREATED
    if not snapshot.pet_window_visible:
        return OwnerStartupFailure.PET_WINDOW_NOT_VISIBLE
    if not snapshot.pet_window_in_workspace:
        return OwnerStartupFailure.PET_WINDOW_OUTSIDE_WORKSPACE
    if not snapshot.tray_constructed:
        return OwnerStartupFailure.TRAY_NOT_CREATED
    if not snapshot.tray_available:
        return OwnerStartupFailure.SYSTEM_TRAY_UNAVAILABLE
    if not snapshot.tray_visible:
        return OwnerStartupFailure.TRAY_NOT_VISIBLE
    if not snapshot.application_ready:
        return OwnerStartupFailure.APPLICATION_READY_MISSING
    return OwnerStartupFailure.NONE


@dataclass(frozen=True, slots=True)
class OwnerUiDiagnosticLaunch:
    """Sanitized application arguments plus an optional recorder."""

    arguments: tuple[str, ...]
    recorder: OwnerUiCheckpointRecorder | None


class OwnerUiCheckpointRecorder:
    """Atomically persist an append-only-in-memory, redacted stage timeline."""

    def __init__(
        self,
        evidence_root: Path,
        session_nonce: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        replace: Callable[[str, str], None] = os.replace,
    ) -> None:
        if _NONCE_PATTERN.fullmatch(session_nonce) is None:
            raise OwnerUiDiagnosticArgumentError
        self._root = evidence_root
        self._nonce = session_nonce
        self._monotonic = monotonic
        self._replace = replace
        self._started_at = monotonic()
        self._events: list[dict[str, object]] = []
        self._last_order = 0
        self._terminal = False
        self._write_failed = False

    @property
    def last_stage(self) -> OwnerStartupStage | None:
        if not self._events:
            return None
        return OwnerStartupStage(str(self._events[-1]["stage"]))

    @property
    def write_failed(self) -> bool:
        return self._write_failed

    def record(
        self,
        stage: OwnerStartupStage,
        failure: OwnerStartupFailure = OwnerStartupFailure.NONE,
    ) -> bool:
        """Record a strictly forward stage, failing closed only for evidence."""

        if self._terminal or self._write_failed:
            return False
        if stage is OwnerStartupStage.FAILED_SAFE:
            if failure is OwnerStartupFailure.NONE:
                return False
        else:
            if failure is not OwnerStartupFailure.NONE:
                return False
            order = _STAGE_ORDER[stage]
            if order <= self._last_order:
                return False
            self._last_order = order
        sequence = len(self._events) + 1
        elapsed_milliseconds = max(
            0,
            round((self._monotonic() - self._started_at) * 1000),
        )
        event: dict[str, object] = {
            "elapsed_milliseconds": elapsed_milliseconds,
            "failure_category": failure.value,
            "sequence": sequence,
            "stage": stage.value,
        }
        self._events.append(event)
        try:
            self._write_checkpoint()
        except (OSError, TypeError, ValueError):
            self._events.pop()
            self._write_failed = True
            return False
        self._terminal = stage in {
            OwnerStartupStage.CLOSED,
            OwnerStartupStage.FAILED_SAFE,
        }
        return True

    def _write_checkpoint(self) -> None:
        document = {
            "events": self._events,
            "owner_ui_readiness_checkpoint": True,
            "schema_version": _SCHEMA_VERSION,
            "session_nonce": self._nonce,
            "value_text_recorded": False,
        }
        payload = json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        part_path = self._root / _PART_FILENAME
        checkpoint_path = self._root / _CHECKPOINT_FILENAME
        with part_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            self._replace(str(part_path), str(checkpoint_path))
        except BaseException:
            with suppress(OSError):
                part_path.unlink(missing_ok=True)
            raise


def prepare_owner_ui_diagnostic_launch(
    argv: Sequence[str],
    *,
    executable: Path | None = None,
) -> OwnerUiDiagnosticLaunch:
    """Parse the opt-in packaged diagnostic without reading external state."""

    arguments = tuple(argv)
    if OWNER_UI_DIAGNOSTIC_ARGUMENT not in arguments:
        return OwnerUiDiagnosticLaunch(arguments=arguments, recorder=None)
    if (
        len(arguments) != 3
        or arguments[1] != OWNER_UI_DIAGNOSTIC_ARGUMENT
        or _NONCE_PATTERN.fullmatch(arguments[2]) is None
    ):
        raise OwnerUiDiagnosticArgumentError
    executable_path = Path(sys.executable if executable is None else executable)
    repository_root = _repository_root_from_packaged_executable(executable_path)
    evidence_parent = repository_root / "build" / _EVIDENCE_DIRECTORY_NAME
    _ensure_safe_directory(evidence_parent, create=True)
    evidence_root = evidence_parent / arguments[2]
    if evidence_root.exists():
        raise OwnerUiDiagnosticArgumentError
    evidence_root.mkdir()
    _ensure_safe_directory(evidence_root, create=False)
    recorder = OwnerUiCheckpointRecorder(evidence_root, arguments[2])
    return OwnerUiDiagnosticLaunch(
        arguments=(arguments[0],),
        recorder=recorder,
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
        raise OwnerUiDiagnosticArgumentError
    repository_root = resolved.parent.parent.parent
    _ensure_safe_directory(repository_root, create=False)
    _ensure_safe_directory(repository_root / "build", create=False)
    return repository_root


def _ensure_safe_directory(path: Path, *, create: bool) -> None:
    if create:
        path.mkdir(parents=False, exist_ok=True)
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        raise OwnerUiDiagnosticArgumentError from None
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_point(path):
        raise OwnerUiDiagnosticArgumentError


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _REPARSE_POINT_ATTRIBUTE)
