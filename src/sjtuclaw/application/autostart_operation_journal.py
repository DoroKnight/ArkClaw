"""Redacted, opt-in causal journal for autostart operations."""

from __future__ import annotations

import json
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

_SCHEMA_VERSION: Final = 1
_PART_SUFFIX: Final = ".part"


class AutostartOperationOrigin(StrEnum):
    """Fixed origins that never contain widget or path details."""

    SETTINGS_CHECKBOX = "settings_checkbox"
    TRAY_ACTION = "tray_action"
    PET_MENU_ACTION = "pet_menu_action"
    STARTUP_QUERY = "startup_query"
    STATE_REFRESH = "state_refresh"
    SHUTDOWN = "shutdown"
    UNKNOWN = "unknown"


class AutostartOperationEvent(StrEnum):
    """Fixed causal events permitted in the diagnostic journal."""

    UI_REQUEST_ACCEPTED = "ui_request_accepted"
    UI_REQUEST_REJECTED = "ui_request_rejected"
    COMMAND_SUBMITTED = "command_submitted"
    RUNTIME_COMMAND_ACCEPTED = "runtime_command_accepted"
    SERVICE_ENABLE_ENTERED = "service_enable_entered"
    SERVICE_DISABLE_ENTERED = "service_disable_entered"
    BACKEND_READ_ENTERED = "backend_read_entered"
    BACKEND_WRITE_ENTERED = "backend_write_entered"
    BACKEND_WRITE_COMPLETED = "backend_write_completed"
    BACKEND_DELETE_ENTERED = "backend_delete_entered"
    BACKEND_DELETE_COMPLETED = "backend_delete_completed"
    READBACK_COMPLETED = "readback_completed"
    COMMAND_COMPLETED = "command_completed"
    COMMAND_FAILED = "command_failed"
    SNAPSHOT_PUBLISHED = "snapshot_published"
    STALE_RESULT_IGNORED = "stale_result_ignored"
    CONTROLLER_CLOSING = "controller_closing"
    APPLICATION_CLOSING = "application_closing"


class AutostartOperationRuntimeState(StrEnum):
    """Coarse fixed execution boundaries safe for evidence."""

    GUI = "gui"
    RUNTIME_READY = "runtime_ready"
    RUNTIME_CLOSING = "runtime_closing"
    RUNTIME_THREAD = "runtime_thread"
    SERVICE = "service"
    APPLICATION = "application"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AutostartOperationContext:
    """Non-sensitive identifiers shared across every operation boundary."""

    operation_id: str = ""
    command_id: str = ""
    origin: AutostartOperationOrigin = AutostartOperationOrigin.UNKNOWN
    requested_enabled: bool | None = None
    controller_revision: int = 0


class AutostartOperationJournalError(RuntimeError):
    """Fixed exception raised when durable diagnostic evidence fails."""

    def __init__(self) -> None:
        super().__init__("The autostart operation journal failed safely.")


class AutostartOperationJournal:
    """Atomically persist an append-only-in-memory JSON-lines timeline."""

    def __init__(self, path: Path, nonce: str) -> None:
        self._path = path
        self._nonce = nonce
        self._events: list[bytes] = []
        self._lock = threading.Lock()
        self._failed = False

    @property
    def failed(self) -> bool:
        return self._failed

    def record(
        self,
        event: AutostartOperationEvent,
        context: AutostartOperationContext | None = None,
        *,
        runtime_state: AutostartOperationRuntimeState = (
            AutostartOperationRuntimeState.UNKNOWN
        ),
        result_code: str = "none",
    ) -> None:
        """Persist one fixed-schema event before returning to the caller."""

        with self._lock:
            if self._failed:
                raise AutostartOperationJournalError
            sequence = len(self._events) + 1
            actual_context = context or AutostartOperationContext()
            document: dict[str, object] = {
                "schema_version": _SCHEMA_VERSION,
                "sequence": sequence,
                "nonce": self._nonce,
                "event": event.value,
                "operation_id": actual_context.operation_id,
                "command_id": actual_context.command_id,
                "origin": actual_context.origin.value,
                "requested_enabled": actual_context.requested_enabled,
                "controller_revision": actual_context.controller_revision,
                "runtime_state": runtime_state.value,
                "result_code": result_code,
            }
            line = json.dumps(
                document,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8") + b"\n"
            self._events.append(line)
            try:
                self._write_all()
            except (OSError, TypeError, ValueError):
                self._events.pop()
                self._failed = True
                raise AutostartOperationJournalError from None

    def _write_all(self) -> None:
        part = self._path.with_name(self._path.name + _PART_SUFFIX)
        with part.open("xb") as stream:
            for line in self._events:
                stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(part, self._path)
        except BaseException:
            with suppress(OSError):
                part.unlink(missing_ok=True)
            raise
