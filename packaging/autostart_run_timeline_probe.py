"""Strict timeline observer for the fixed SJTUClaw HKCU Run value.

The default entry point is inert. Real registry observation requires the
explicit ``--confirm-real-registry`` flag and always targets the one fixed
SJTUClaw value. Registry value text and exception details are never persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypeGuard

SCHEMA_VERSION = 2
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "SJTUClaw"
AUTOSTART_ARGUMENT = "--startup"
REGISTRY_STRING_VALUE_TYPE = 1
POLL_INTERVAL_SECONDS = 0.2
READY_UNARMED_TIMEOUT_SECONDS = 60 * 60
ACTIVE_TIMEOUT_SECONDS = 90 * 60
STAGE_LEASE_SECONDS = 30 * 60
TOTAL_RUNTIME_SECONDS = 3 * 60 * 60
EXPECTED_EXECUTABLE_RELATIVE_PATH = Path("dist/SJTUClaw.dist/SJTUClaw.exe")
EVIDENCE_PARENT_RELATIVE_PATH = Path("build/autostart-run-timeline-probes")
OWNER_UI_EVIDENCE_PARENT_RELATIVE_PATH = Path(
    "build/autostart-owner-ui-readiness"
)
OWNER_UI_CHECKPOINT_MAX_BYTES = 64 * 1024
MAX_EVIDENCE_PATH_LENGTH = 240
PHASES = (
    "T0",
    "T1",
    "T2-before-enable",
    "T3-after-enable",
    "T4",
    "T5",
    "T6",
    "T7-before-shutdown",
    "T8-after-process-exit",
    "T9-final",
)
PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}


class TimelineProbeError(RuntimeError):
    """Fixed-message probe failure without registry or path disclosure."""


class TimelineCoordinationError(TimelineProbeError):
    """Fixed safe-code coordination failure."""

    def __init__(self, safe_code: str, message: str) -> None:
        super().__init__(message)
        self.safe_code = safe_code


class FixedValueState(StrEnum):
    """Safe classification that never contains registry value text."""

    ABSENT = "absent"
    OWNED = "owned"
    OCCUPIED = "occupied"
    READ_ERROR = "read_error"


class ProbeLifecycleState(StrEnum):
    """Explicit observer lifecycle independent from Owner and supervisor."""

    INITIALIZING = "initializing"
    READY_UNARMED = "ready_unarmed"
    ARMED = "armed"
    OBSERVING = "observing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class OwnerTerminalState(StrEnum):
    """Safe Owner status without paths or process command lines."""

    NOT_REGISTERED = "not_registered"
    RUNNING = "running"
    EXITED = "exited"
    IDENTITY_LOST = "identity_lost"


@dataclass(frozen=True, slots=True)
class ControlMessage:
    """Strict, nonce-bound, revisioned phase transition."""

    schema_version: int
    session_nonce: str
    revision: int
    expected_previous_phase: str | None
    phase: str
    stop: bool
    abort: bool


@dataclass(frozen=True, slots=True)
class OwnerRegistration:
    """Owner PID plus immutable process creation identity."""

    schema_version: int
    session_nonce: str
    process_id: int
    process_identity: str


@dataclass(frozen=True, slots=True)
class CoordinationCheckpoint:
    """Non-sensitive state shared with the independent supervisor."""

    schema_version: int
    lifecycle_state: str
    current_phase: str
    revision: int
    active_budget_started: bool
    owner_terminal_state: str
    observer_terminal_state: str
    supervisor_terminal_state: str
    owner_safe_exit_required: bool
    safe_code: str
    value_text_recorded: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceTreeManifest:
    """Deterministic archive manifest without file contents."""

    entries: tuple[tuple[str, int, str], ...]
    file_count: int
    total_size: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class SafeValueObservation:
    """Non-sensitive result of one exact fixed-value query."""

    state: FixedValueState
    present: bool
    owned: bool
    type_valid: bool
    length: int
    sha256: str | None
    query_error: bool

    @classmethod
    def absent(cls) -> SafeValueObservation:
        return cls(FixedValueState.ABSENT, False, False, False, 0, None, False)

    @classmethod
    def read_error(cls) -> SafeValueObservation:
        return cls(
            FixedValueState.READ_ERROR,
            False,
            False,
            False,
            0,
            None,
            True,
        )

    @classmethod
    def from_stored_value(
        cls,
        value: object,
        value_type: object,
        expected_command: str,
    ) -> SafeValueObservation:
        normalized_type = (
            value_type
            if isinstance(value_type, int) and not isinstance(value_type, bool)
            else -1
        )
        type_valid = normalized_type == REGISTRY_STRING_VALUE_TYPE
        if not isinstance(value, str):
            return cls(
                FixedValueState.OCCUPIED,
                True,
                False,
                type_valid,
                0,
                None,
                False,
            )
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        owned = type_valid and value == expected_command
        return cls(
            FixedValueState.OWNED if owned else FixedValueState.OCCUPIED,
            True,
            owned,
            type_valid,
            len(value),
            digest,
            False,
        )


@dataclass(frozen=True, slots=True)
class TimelineRecord:
    """One allowed state transition or named phase snapshot."""

    schema_version: int
    sequence: int
    phase: str
    process_running: bool
    present: bool
    owned: bool
    type_valid: bool
    length: int
    sha256: str | None
    query_error: bool
    transition: str
    value_text_recorded: bool = False
    other_value_enumeration_count: int = 0
    startup_approved_access_count: int = 0


@dataclass(frozen=True, slots=True)
class TimelineSummary:
    """Terminal non-sensitive summary frozen before optional cleanup."""

    schema_version: int
    autostart_run_timeline_probe: bool
    safe_code: str
    query_count: int
    record_count: int
    first_present_sequence: int | None
    first_owned_sequence: int | None
    first_absent_after_owned_sequence: int | None
    first_absent_after_owned_phase: str | None
    process_exit_sequence: int | None
    owner_exit_observed_sequence: int | None
    accepted_phase: str
    disappearance_interval: str | None
    phase_states: Mapping[str, str]
    lifecycle_state: str = ProbeLifecycleState.FAILED
    observer_terminal_state: str = "failed"
    owner_terminal_state: str = OwnerTerminalState.NOT_REGISTERED
    supervisor_terminal_state: str = "independent"
    owner_safe_exit_required: bool = False
    final_revision: int = 0
    observer_registry_write_count: int = 0
    observer_registry_delete_count: int = 0
    value_text_recorded: bool = False
    other_value_enumeration_count: int = 0
    startup_approved_access_count: int = 0


class ValueReader(Protocol):
    def __call__(self, expected_command: str) -> SafeValueObservation: ...


class ProcessProbe(Protocol):
    def __call__(self, process_id: int) -> bool: ...


class ProcessIdentityProbe(Protocol):
    def __call__(self, process_id: int) -> str | None: ...


class ProbeCoordinator:
    """Pure lifecycle, revision, nonce, and deadline coordinator."""

    def __init__(
        self,
        session_nonce: str,
        started_at: float,
        *,
        ready_timeout_seconds: float = READY_UNARMED_TIMEOUT_SECONDS,
        active_timeout_seconds: float = ACTIVE_TIMEOUT_SECONDS,
        stage_lease_seconds: float = STAGE_LEASE_SECONDS,
        total_timeout_seconds: float = TOTAL_RUNTIME_SECONDS,
    ) -> None:
        if not _valid_session_nonce(session_nonce):
            raise TimelineCoordinationError(
                "autostart_timeline_nonce_mismatch",
                "The timeline session nonce is invalid.",
            )
        self.session_nonce = session_nonce
        self.started_at = started_at
        self.ready_timeout_seconds = ready_timeout_seconds
        self.active_timeout_seconds = active_timeout_seconds
        self.stage_lease_seconds = stage_lease_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.lifecycle_state = ProbeLifecycleState.INITIALIZING
        self.current_phase = "T0"
        self.revision = 0
        self.ready_at: float | None = None
        self.active_started_at: float | None = None
        self.stage_lease_started_at: float | None = None
        self.owner_registration: OwnerRegistration | None = None
        self.owner_terminal_state = OwnerTerminalState.NOT_REGISTERED
        self.safe_code = "none"

    def mark_ready(self, now: float) -> None:
        if self.lifecycle_state is not ProbeLifecycleState.INITIALIZING:
            raise TimelineCoordinationError(
                "autostart_timeline_lifecycle_invalid",
                "The timeline lifecycle transition is invalid.",
            )
        self.ready_at = now
        self.lifecycle_state = ProbeLifecycleState.READY_UNARMED

    def register_owner(self, registration: OwnerRegistration) -> None:
        if registration.session_nonce != self.session_nonce:
            raise TimelineCoordinationError(
                "autostart_timeline_nonce_mismatch",
                "The timeline session nonce is invalid.",
            )
        if self.owner_registration == registration:
            return
        if self.lifecycle_state is not ProbeLifecycleState.READY_UNARMED:
            raise TimelineCoordinationError(
                "autostart_timeline_owner_registration_invalid",
                "Owner registration is no longer allowed.",
            )
        if self.owner_registration is not None:
            raise TimelineCoordinationError(
                "autostart_timeline_owner_registration_invalid",
                "Owner process data is invalid.",
            )
        self.owner_registration = registration
        self.owner_terminal_state = OwnerTerminalState.RUNNING

    def accept_control(
        self,
        message: ControlMessage,
        now: float,
        *,
        current_process_identity: str | None,
    ) -> None:
        if self.lifecycle_state in {
            ProbeLifecycleState.COMPLETED,
            ProbeLifecycleState.FAILED,
            ProbeLifecycleState.FINALIZING,
        }:
            raise TimelineCoordinationError(
                "autostart_timeline_lifecycle_invalid",
                "The timeline observer is finalizing.",
            )
        if message.session_nonce != self.session_nonce:
            raise TimelineCoordinationError(
                "autostart_timeline_nonce_mismatch",
                "The timeline session nonce is invalid.",
            )
        if message.revision != self.revision + 1:
            raise TimelineCoordinationError(
                "autostart_timeline_control_revision_invalid",
                "The timeline control revision is invalid.",
            )
        if message.expected_previous_phase != self.current_phase:
            raise TimelineCoordinationError(
                "autostart_timeline_control_sequence_invalid",
                "The timeline control sequence is invalid.",
            )
        if message.abort:
            if message.phase != self.current_phase or message.stop:
                raise TimelineCoordinationError(
                    "autostart_timeline_abort_invalid",
                    "The timeline abort request is invalid.",
                )
            self.revision = message.revision
            self.stage_lease_started_at = now
            self.safe_code = "autostart_timeline_probe_aborted"
            self.lifecycle_state = ProbeLifecycleState.FINALIZING
            return
        expected_index = PHASE_INDEX[self.current_phase] + 1
        if expected_index >= len(PHASES) or message.phase != PHASES[expected_index]:
            raise TimelineCoordinationError(
                "autostart_timeline_control_sequence_invalid",
                "The timeline control sequence is invalid.",
            )
        if message.stop != (message.phase == "T9-final"):
            raise TimelineCoordinationError(
                "autostart_timeline_stop_invalid",
                "The timeline stop request is invalid.",
            )
        if message.phase == "T1":
            registration = self.owner_registration
            if registration is None:
                raise TimelineCoordinationError(
                    "autostart_timeline_owner_missing",
                    "The timeline Owner is not registered.",
                )
            if current_process_identity is None:
                self.owner_terminal_state = OwnerTerminalState.EXITED
                raise TimelineCoordinationError(
                    "autostart_timeline_owner_exited_early",
                    "The timeline Owner exited too early.",
                )
            if current_process_identity != registration.process_identity:
                self.owner_terminal_state = OwnerTerminalState.IDENTITY_LOST
                raise TimelineCoordinationError(
                    "autostart_timeline_owner_identity_lost",
                    "The timeline Owner identity changed.",
                )
            self.lifecycle_state = ProbeLifecycleState.ARMED
            self.active_started_at = now
        self.current_phase = message.phase
        self.revision = message.revision
        self.stage_lease_started_at = now
        if message.phase == "T9-final":
            self.lifecycle_state = ProbeLifecycleState.FINALIZING
        elif message.phase == "T1":
            self.lifecycle_state = ProbeLifecycleState.ARMED
        else:
            self.lifecycle_state = ProbeLifecycleState.OBSERVING

    def begin_observing(self) -> None:
        if self.lifecycle_state is not ProbeLifecycleState.ARMED:
            raise TimelineCoordinationError(
                "autostart_timeline_lifecycle_invalid",
                "The timeline lifecycle transition is invalid.",
            )
        self.lifecycle_state = ProbeLifecycleState.OBSERVING

    def observe_owner_identity(self, identity: str | None) -> str | None:
        registration = self.owner_registration
        if registration is None:
            return None
        if identity == registration.process_identity:
            self.owner_terminal_state = OwnerTerminalState.RUNNING
            return None
        if identity is not None:
            self.owner_terminal_state = OwnerTerminalState.IDENTITY_LOST
            return "autostart_timeline_owner_identity_lost"
        self.owner_terminal_state = OwnerTerminalState.EXITED
        if PHASE_INDEX[self.current_phase] < PHASE_INDEX["T7-before-shutdown"]:
            return "autostart_timeline_owner_exited_early"
        return None

    def timeout_code(self, now: float) -> str | None:
        if now - self.started_at >= self.total_timeout_seconds:
            return "autostart_timeline_total_timeout"
        if self.lifecycle_state is ProbeLifecycleState.READY_UNARMED:
            ready_at = self.ready_at
            if ready_at is None:
                raise TimelineCoordinationError(
                    "autostart_timeline_lifecycle_invalid",
                    "The timeline lifecycle state is invalid.",
                )
            if now - ready_at >= self.ready_timeout_seconds:
                return "autostart_timeline_ready_timeout"
            return None
        if self.lifecycle_state in {
            ProbeLifecycleState.ARMED,
            ProbeLifecycleState.OBSERVING,
        }:
            active_started_at = self.active_started_at
            lease_started_at = self.stage_lease_started_at
            if active_started_at is None or lease_started_at is None:
                raise TimelineCoordinationError(
                    "autostart_timeline_lifecycle_invalid",
                    "The timeline lifecycle state is invalid.",
                )
            if now - active_started_at >= self.active_timeout_seconds:
                return "autostart_timeline_active_timeout"
            if now - lease_started_at >= self.stage_lease_seconds:
                return "autostart_timeline_stage_timeout"
        return None

    def fail(self, safe_code: str) -> None:
        self.safe_code = safe_code
        self.lifecycle_state = ProbeLifecycleState.FAILED

    def complete(self) -> None:
        self.safe_code = "autostart_run_value_timeline_verified"
        self.lifecycle_state = ProbeLifecycleState.COMPLETED

    def checkpoint(self) -> CoordinationCheckpoint:
        owner_running = self.owner_terminal_state is OwnerTerminalState.RUNNING
        if self.lifecycle_state is ProbeLifecycleState.COMPLETED:
            observer_terminal = "completed"
        elif self.lifecycle_state is ProbeLifecycleState.FAILED:
            observer_terminal = "failed"
        else:
            observer_terminal = "running"
        supervisor_terminal = (
            "awaiting_owner_safe_exit"
            if self.lifecycle_state is ProbeLifecycleState.FAILED and owner_running
            else "independent"
        )
        return CoordinationCheckpoint(
            schema_version=SCHEMA_VERSION,
            lifecycle_state=self.lifecycle_state,
            current_phase=self.current_phase,
            revision=self.revision,
            active_budget_started=self.active_started_at is not None,
            owner_terminal_state=self.owner_terminal_state,
            observer_terminal_state=observer_terminal,
            supervisor_terminal_state=supervisor_terminal,
            owner_safe_exit_required=(
                self.lifecycle_state is ProbeLifecycleState.FAILED and owner_running
            ),
            safe_code=self.safe_code,
        )


class TimelineTracker:
    """Pure state reducer for deterministic registry timeline tests."""

    def __init__(self) -> None:
        self.records: list[TimelineRecord] = []
        self.query_count = 0
        self.first_present_sequence: int | None = None
        self.first_owned_sequence: int | None = None
        self.first_absent_after_owned_sequence: int | None = None
        self.process_exit_sequence: int | None = None
        self._last_signature: tuple[object, ...] | None = None
        self._last_phase: str | None = None
        self._last_process_running = False
        self._phase_states: dict[str, FixedValueState] = {}

    def observe(
        self,
        phase: str,
        process_running: bool,
        observation: SafeValueObservation,
    ) -> TimelineRecord | None:
        if phase not in PHASES:
            raise TimelineProbeError("The timeline phase is invalid.")
        self.query_count += 1
        signature = (
            observation.state,
            observation.present,
            observation.owned,
            observation.type_valid,
            observation.length,
            observation.sha256,
            observation.query_error,
            process_running,
        )
        phase_changed = phase != self._last_phase
        state_changed = signature != self._last_signature
        if not phase_changed and not state_changed:
            return None
        sequence = len(self.records) + 1
        transition = self._transition(
            observation,
            process_running,
            phase_changed=phase_changed,
        )
        record = TimelineRecord(
            schema_version=SCHEMA_VERSION,
            sequence=sequence,
            phase=phase,
            process_running=process_running,
            present=observation.present,
            owned=observation.owned,
            type_valid=observation.type_valid,
            length=observation.length,
            sha256=observation.sha256,
            query_error=observation.query_error,
            transition=transition,
        )
        self.records.append(record)
        self._phase_states[phase] = observation.state
        if observation.present and self.first_present_sequence is None:
            self.first_present_sequence = sequence
        if observation.owned and self.first_owned_sequence is None:
            self.first_owned_sequence = sequence
        if (
            self.first_owned_sequence is not None
            and not observation.present
            and self.first_absent_after_owned_sequence is None
        ):
            self.first_absent_after_owned_sequence = sequence
        if (
            self._last_process_running
            and not process_running
            and self.process_exit_sequence is None
        ):
            self.process_exit_sequence = sequence
        self._last_signature = signature
        self._last_phase = phase
        self._last_process_running = process_running
        return record

    def summarize(
        self,
        *,
        timed_out: bool = False,
        safe_code_override: str | None = None,
        checkpoint: CoordinationCheckpoint | None = None,
    ) -> TimelineSummary:
        states = [record for record in self.records]
        if safe_code_override is not None:
            safe_code = safe_code_override
        elif timed_out:
            safe_code = "autostart_timeline_probe_timeout"
        elif any(record.query_error for record in states):
            safe_code = "autostart_timeline_probe_read_failed"
        elif any(record.present and not record.owned for record in states):
            safe_code = "autostart_ownership_lost"
        elif self.first_owned_sequence is None:
            safe_code = "autostart_value_never_persisted"
        elif self.first_absent_after_owned_sequence is not None:
            safe_code = self._removal_safe_code()
        elif self._required_terminal_phases_owned():
            safe_code = "autostart_run_value_timeline_verified"
        else:
            safe_code = "autostart_timeline_probe_incomplete"
        coordination = checkpoint or CoordinationCheckpoint(
            schema_version=SCHEMA_VERSION,
            lifecycle_state=ProbeLifecycleState.FAILED,
            current_phase=self._last_phase or "T0",
            revision=0,
            active_budget_started=False,
            owner_terminal_state=OwnerTerminalState.NOT_REGISTERED,
            observer_terminal_state="failed",
            supervisor_terminal_state="independent",
            owner_safe_exit_required=False,
            safe_code=safe_code,
        )
        absence_record = self._first_absent_after_owned_record()
        return TimelineSummary(
            schema_version=SCHEMA_VERSION,
            autostart_run_timeline_probe=True,
            safe_code=safe_code,
            query_count=self.query_count,
            record_count=len(self.records),
            first_present_sequence=self.first_present_sequence,
            first_owned_sequence=self.first_owned_sequence,
            first_absent_after_owned_sequence=(
                self.first_absent_after_owned_sequence
            ),
            first_absent_after_owned_phase=(
                absence_record.phase if absence_record is not None else None
            ),
            process_exit_sequence=self.process_exit_sequence,
            owner_exit_observed_sequence=self.process_exit_sequence,
            accepted_phase=self._last_phase or "T0",
            disappearance_interval=self._disappearance_interval(),
            phase_states={
                phase: state.value
                for phase, state in sorted(self._phase_states.items())
            },
            lifecycle_state=coordination.lifecycle_state,
            observer_terminal_state=coordination.observer_terminal_state,
            owner_terminal_state=coordination.owner_terminal_state,
            supervisor_terminal_state=coordination.supervisor_terminal_state,
            owner_safe_exit_required=coordination.owner_safe_exit_required,
            final_revision=coordination.revision,
        )

    def _transition(
        self,
        observation: SafeValueObservation,
        process_running: bool,
        *,
        phase_changed: bool,
    ) -> str:
        if self._last_signature is None:
            return f"initial_{observation.state.value}"
        if self._last_process_running and not process_running:
            return "process_exited"
        if not self._last_process_running and process_running:
            return "process_started"
        previous_state = self._last_signature[0]
        if previous_state != observation.state:
            return f"value_{previous_state}_to_{observation.state.value}"
        if phase_changed:
            return "phase_snapshot"
        return "value_metadata_changed"

    def _first_absent_after_owned_record(self) -> TimelineRecord | None:
        sequence = self.first_absent_after_owned_sequence
        return None if sequence is None else self.records[sequence - 1]

    def _removal_safe_code(self) -> str:
        record = self._first_absent_after_owned_record()
        if record is None:
            raise TimelineProbeError("The timeline removal state is invalid.")
        if (
            self.process_exit_sequence is not None
            and self.process_exit_sequence <= record.sequence
        ):
            return "autostart_value_removed_after_process_exit"
        if (
            record.phase == "T7-before-shutdown"
            and record.process_running
        ):
            return "autostart_value_removed_during_shutdown"
        if record.phase in {
            "T3-after-enable",
            "T4",
            "T5",
            "T6",
        } and record.process_running:
            return "autostart_value_removed_during_runtime"
        return "autostart_timeline_probe_incomplete"

    def _disappearance_interval(self) -> str | None:
        sequence = self.first_absent_after_owned_sequence
        if sequence is None:
            return None
        record = self.records[sequence - 1]
        if not record.process_running:
            return "after_process_exit"
        previous_phases = [
            item.phase for item in self.records[: sequence - 1] if item.owned
        ]
        last_owned_phase = (
            previous_phases[-1] if previous_phases else "T2-before-enable"
        )
        return f"{last_owned_phase}_to_{record.phase}"

    def _required_terminal_phases_owned(self) -> bool:
        return all(
            self._phase_states.get(phase) is FixedValueState.OWNED
            for phase in (
                "T3-after-enable",
                "T4",
                "T5",
                "T6",
                "T7-before-shutdown",
                "T8-after-process-exit",
                "T9-final",
            )
        )


def query_fixed_run_value(expected_command: str) -> SafeValueObservation:
    """Query only the fixed value without enumeration or mutation."""

    if sys.platform != "win32":
        return SafeValueObservation.read_error()
    try:
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                access=winreg.KEY_QUERY_VALUE,
            )
        except FileNotFoundError:
            return SafeValueObservation.absent()
        with key:
            try:
                value, value_type = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                return SafeValueObservation.absent()
    except OSError:
        return SafeValueObservation.read_error()
    return SafeValueObservation.from_stored_value(
        value,
        value_type,
        expected_command,
    )


def _write_json_atomically(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.part")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                document,
                stream,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        raise TimelineProbeError(
            "Timeline evidence could not be written safely."
        ) from None
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _valid_session_nonce(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 32
        and value == value.casefold()
        and all(character in "0123456789abcdef" for character in value)
    )


def _control_document(message: ControlMessage) -> dict[str, object]:
    return asdict(message)


def _read_control(path: Path) -> ControlMessage:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TimelineProbeError("Timeline control data is invalid.") from None
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "session_nonce",
        "revision",
        "expected_previous_phase",
        "phase",
        "stop",
        "abort",
    }:
        raise TimelineProbeError("Timeline control data is invalid.")
    nonce = document.get("session_nonce")
    revision = document.get("revision")
    previous = document.get("expected_previous_phase")
    phase = document.get("phase")
    stop = document.get("stop")
    abort = document.get("abort")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or not _valid_session_nonce(nonce)
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
        or (previous is not None and previous not in PHASES)
        or not isinstance(phase, str)
        or phase not in PHASES
        or not isinstance(stop, bool)
        or not isinstance(abort, bool)
    ):
        raise TimelineProbeError("Timeline control data is invalid.")
    return ControlMessage(
        schema_version=SCHEMA_VERSION,
        session_nonce=nonce,
        revision=revision,
        expected_previous_phase=previous,
        phase=phase,
        stop=stop,
        abort=abort,
    )


def _read_owner_registration(path: Path) -> OwnerRegistration | None:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TimelineProbeError("Owner process data is invalid.") from None
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "session_nonce",
        "process_id",
        "process_identity",
    }:
        raise TimelineProbeError("Owner process data is invalid.")
    nonce = document.get("session_nonce")
    process_id = document.get("process_id")
    process_identity = document.get("process_identity")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or not _valid_session_nonce(nonce)
        or not isinstance(process_id, int)
        or isinstance(process_id, bool)
        or process_id <= 0
        or not isinstance(process_identity, str)
        or len(process_identity) != 16
        or process_identity != process_identity.casefold()
        or any(
            character not in "0123456789abcdef"
            for character in process_identity
        )
    ):
        raise TimelineProbeError("Owner process data is invalid.")
    return OwnerRegistration(
        schema_version=SCHEMA_VERSION,
        session_nonce=nonce,
        process_id=process_id,
        process_identity=process_identity,
    )


def _process_is_running(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _process_identity(process_id: int) -> str | None:
    """Return the Windows process creation FILETIME without opening its image."""

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [
            ("low", wintypes.DWORD),
            ("high", wintypes.DWORD),
        ]

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    get_process_times = kernel32.GetProcessTimes
    get_process_times.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    get_process_times.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = open_process(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        return None
    try:
        created = FileTime()
        exited = FileTime()
        kernel = FileTime()
        user = FileTime()
        if not get_process_times(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        creation_value = (int(created.high) << 32) | int(created.low)
        return f"{creation_value:016x}"
    finally:
        close_handle(handle)


def _repository_root() -> Path:
    return Path(__file__).resolve(strict=True).parents[1]


def _is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    return bool(int(getattr(metadata, "st_file_attributes", 0)) & 0x400)


def _allowed_evidence_parent() -> Path:
    return (
        _repository_root() / EVIDENCE_PARENT_RELATIVE_PATH
    ).resolve(strict=False)


def _validated_evidence_root(
    raw_path: str,
    *,
    must_exist: bool,
) -> Path:
    if (
        not raw_path
        or len(raw_path) > MAX_EVIDENCE_PATH_LENGTH
        or raw_path.startswith(("\\\\", "//"))
        or any(ord(character) < 32 for character in raw_path)
        or ".." in raw_path.replace("\\", "/").split("/")
    ):
        raise TimelineProbeError("The timeline evidence path is invalid.")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise TimelineProbeError("The timeline evidence path is invalid.")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except OSError:
        raise TimelineProbeError(
            "The timeline evidence path is invalid."
        ) from None
    allowed_parent = _allowed_evidence_parent()
    if (
        resolved.parent != allowed_parent
        or resolved.drive.casefold() != allowed_parent.drive.casefold()
        or not resolved.name
        or len(resolved.name) > 96
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in resolved.name
        )
    ):
        raise TimelineProbeError("The timeline evidence path is invalid.")
    build_root = allowed_parent.parent
    if (
        not build_root.is_dir()
        or _is_reparse_point(build_root)
        or (allowed_parent.exists() and _is_reparse_point(allowed_parent))
    ):
        raise TimelineProbeError("The timeline evidence path is invalid.")
    if must_exist:
        if not resolved.is_dir() or _is_reparse_point(resolved):
            raise TimelineProbeError("The timeline evidence path is invalid.")
    elif resolved.exists():
        raise TimelineProbeError("The timeline evidence directory is occupied.")
    return resolved


def _prepare_new_evidence_root(raw_path: str) -> Path:
    root = _validated_evidence_root(raw_path, must_exist=False)
    parent = root.parent
    if not parent.exists():
        parent.mkdir(parents=False)
    if _is_reparse_point(parent):
        raise TimelineProbeError("The timeline evidence path is invalid.")
    try:
        root.mkdir(parents=False)
    except OSError:
        raise TimelineProbeError(
            "The timeline evidence directory could not be created."
        ) from None
    return root


def _evidence_tree_manifest(root: Path) -> EvidenceTreeManifest:
    if not root.is_dir() or _is_reparse_point(root):
        raise TimelineProbeError("The timeline evidence archive is invalid.")
    entries: list[tuple[str, int, str]] = []
    for entry in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if _is_reparse_point(entry):
            raise TimelineProbeError("The timeline evidence archive is invalid.")
        if entry.name.endswith(".part"):
            raise TimelineProbeError("The timeline evidence archive is invalid.")
        if entry.is_dir():
            continue
        metadata = entry.stat()
        if (
            not entry.is_file()
            or metadata.st_nlink != 1
            or metadata.st_size < 0
        ):
            raise TimelineProbeError("The timeline evidence archive is invalid.")
        entries.append(
            (
                entry.relative_to(root).as_posix(),
                metadata.st_size,
                _hash_file(entry),
            )
        )
    canonical = "".join(
        f"{relative_path}\t{size}\t{digest}\n"
        for relative_path, size, digest in entries
    ).encode("utf-8")
    return EvidenceTreeManifest(
        entries=tuple(entries),
        file_count=len(entries),
        total_size=sum(size for _, size, _ in entries),
        manifest_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _archive_evidence_directory(
    source: Path,
    archive_root: Path,
    archive_name: str,
    transaction_name: str,
    *,
    mover: Callable[[Path, Path], None] = os.replace,
) -> tuple[Path, EvidenceTreeManifest]:
    if (
        not archive_name
        or not transaction_name
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in archive_name + transaction_name
        )
    ):
        raise TimelineProbeError("The timeline evidence archive is invalid.")
    if not source.is_dir() or _is_reparse_point(source):
        raise TimelineProbeError("The timeline evidence archive is invalid.")
    source = source.resolve(strict=True)
    archive_root = archive_root.resolve(strict=False)
    target = archive_root / archive_name
    transaction = archive_root.parent / transaction_name
    if (
        source.drive.casefold() != archive_root.drive.casefold()
        or target.exists()
        or transaction.exists()
        or _is_reparse_point(source)
    ):
        raise TimelineProbeError("The timeline evidence archive is invalid.")
    before = _evidence_tree_manifest(source)
    archive_root.mkdir(parents=False, exist_ok=True)
    if _is_reparse_point(archive_root):
        raise TimelineProbeError("The timeline evidence archive is invalid.")
    try:
        mover(source, transaction)
        if _evidence_tree_manifest(transaction) != before:
            raise TimelineProbeError("The timeline evidence archive is invalid.")
        mover(transaction, target)
        if _evidence_tree_manifest(target) != before:
            raise TimelineProbeError("The timeline evidence archive is invalid.")
    except Exception:
        try:
            if target.exists() and not source.exists():
                mover(target, source)
            elif transaction.exists() and not source.exists():
                mover(transaction, source)
        except Exception:
            raise TimelineProbeError(
                "The timeline evidence archive rollback failed."
            ) from None
        raise TimelineProbeError(
            "The timeline evidence archive failed safely."
        ) from None
    return target, before


def _authoritative_executable(expected_sha256: str) -> tuple[Path, str]:
    executable = (
        _repository_root() / EXPECTED_EXECUTABLE_RELATIVE_PATH
    ).resolve(strict=True)
    metadata = executable.lstat()
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    if (
        not stat.S_ISREG(metadata.st_mode)
        or attributes & 0x400
        or metadata.st_nlink != 1
        or executable.suffix.casefold() != ".exe"
    ):
        raise TimelineProbeError("The authoritative executable is invalid.")
    actual_sha256 = _hash_file(executable)
    if actual_sha256 != expected_sha256:
        raise TimelineProbeError("The authoritative executable is invalid.")
    expected_command = f'"{executable}" {AUTOSTART_ARGUMENT}'
    return executable, expected_command


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _persist_tracker(root: Path, tracker: TimelineTracker) -> None:
    _write_json_atomically(
        root / "timeline.json",
        [asdict(record) for record in tracker.records],
    )


def _persist_checkpoint(root: Path, coordinator: ProbeCoordinator) -> None:
    _write_json_atomically(
        root / "observer-checkpoint.json",
        asdict(coordinator.checkpoint()),
    )


def _persist_terminal_summary(
    root: Path,
    tracker: TimelineTracker,
    coordinator: ProbeCoordinator,
) -> TimelineSummary:
    checkpoint = coordinator.checkpoint()
    summary = tracker.summarize(
        safe_code_override=coordinator.safe_code,
        checkpoint=checkpoint,
    )
    _write_json_atomically(root / "terminal-summary.json", asdict(summary))
    return summary


def _read_ready_session_nonce(path: Path) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TimelineProbeError("The timeline observer is not ready.") from None
    if not isinstance(document, dict):
        raise TimelineProbeError("The timeline observer is not ready.")
    nonce = document.get("session_nonce")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("observer_ready") is not True
        or document.get("lifecycle_state")
        != ProbeLifecycleState.READY_UNARMED
        or not _valid_session_nonce(nonce)
    ):
        raise TimelineProbeError("The timeline observer is not ready.")
    try:
        checkpoint = json.loads(
            (path.parent / "observer-checkpoint.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        raise TimelineProbeError("The timeline observer is not ready.") from None
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("schema_version") != SCHEMA_VERSION
        or checkpoint.get("lifecycle_state")
        not in {
            ProbeLifecycleState.READY_UNARMED,
            ProbeLifecycleState.ARMED,
            ProbeLifecycleState.OBSERVING,
        }
        or checkpoint.get("observer_terminal_state") != "running"
    ):
        raise TimelineProbeError("The timeline observer is not ready.")
    return nonce


def _run_real_observer(
    expected_sha256: str,
    evidence_root: str,
    session_nonce: str,
    *,
    reader: ValueReader = query_fixed_run_value,
    identity_probe: ProcessIdentityProbe = _process_identity,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    root = _validated_evidence_root(evidence_root, must_exist=False)
    _, expected_command = _authoritative_executable(expected_sha256)
    root = _prepare_new_evidence_root(str(root))
    started_at = monotonic()
    coordinator = ProbeCoordinator(session_nonce, started_at)
    control_path = root / "control.json"
    owner_path = root / "owner-pid.json"
    initial_control = ControlMessage(
        schema_version=SCHEMA_VERSION,
        session_nonce=coordinator.session_nonce,
        revision=0,
        expected_previous_phase=None,
        phase="T0",
        stop=False,
        abort=False,
    )
    _write_json_atomically(
        control_path,
        _control_document(initial_control),
    )
    tracker = TimelineTracker()
    first = reader(expected_command)
    tracker.observe("T0", False, first)
    _persist_tracker(root, tracker)
    if first.state is not FixedValueState.ABSENT:
        safe_code = (
            "autostart_timeline_target_occupied"
            if first.state in {FixedValueState.OWNED, FixedValueState.OCCUPIED}
            else "autostart_timeline_probe_read_failed"
        )
        coordinator.fail(safe_code)
        _persist_checkpoint(root, coordinator)
        _persist_terminal_summary(root, tracker, coordinator)
        _write_json_atomically(
            root / "ready.json",
            {
                "schema_version": SCHEMA_VERSION,
                "observer_ready": False,
                "lifecycle_state": ProbeLifecycleState.FAILED,
                "safe_code": safe_code,
                "value_text_recorded": False,
            },
        )
        return 2
    coordinator.mark_ready(monotonic())
    _persist_checkpoint(root, coordinator)
    _write_json_atomically(
        root / "ready.json",
        {
            "schema_version": SCHEMA_VERSION,
            "observer_ready": True,
            "lifecycle_state": ProbeLifecycleState.READY_UNARMED,
            "session_nonce": coordinator.session_nonce,
            "safe_code": "autostart_timeline_observer_ready",
            "value_text_recorded": False,
        },
    )
    while True:
        now = monotonic()
        timeout_code = coordinator.timeout_code(now)
        if timeout_code is not None:
            coordinator.fail(timeout_code)
            _persist_checkpoint(root, coordinator)
            _persist_terminal_summary(root, tracker, coordinator)
            return 2
        try:
            registration = _read_owner_registration(owner_path)
            if registration is not None:
                coordinator.register_owner(registration)
            control = _read_control(control_path)
            if control.revision < coordinator.revision:
                raise TimelineCoordinationError(
                    "autostart_timeline_control_revision_invalid",
                    "The timeline control revision is invalid.",
                )
            if control.revision > coordinator.revision:
                current_identity = (
                    identity_probe(registration.process_id)
                    if registration is not None
                    else None
                )
                coordinator.accept_control(
                    control,
                    now,
                    current_process_identity=current_identity,
                )
                _persist_checkpoint(root, coordinator)
                if coordinator.lifecycle_state is ProbeLifecycleState.ARMED:
                    coordinator.begin_observing()
                    _persist_checkpoint(root, coordinator)
        except TimelineCoordinationError as error:
            coordinator.fail(error.safe_code)
            _persist_checkpoint(root, coordinator)
            _persist_terminal_summary(root, tracker, coordinator)
            return 2
        except TimelineProbeError:
            coordinator.fail("autostart_timeline_control_invalid")
            _persist_checkpoint(root, coordinator)
            _persist_terminal_summary(root, tracker, coordinator)
            return 2

        active_registration = coordinator.owner_registration
        current_identity = (
            identity_probe(active_registration.process_id)
            if active_registration is not None
            else None
        )
        owner_error = coordinator.observe_owner_identity(current_identity)
        if owner_error is not None:
            coordinator.fail(owner_error)
            _persist_checkpoint(root, coordinator)
            _persist_terminal_summary(root, tracker, coordinator)
            return 2
        running = coordinator.owner_terminal_state is OwnerTerminalState.RUNNING
        observation = reader(expected_command)
        record = tracker.observe(coordinator.current_phase, running, observation)
        if record is not None:
            _persist_tracker(root, tracker)
        if observation.state in {
            FixedValueState.OCCUPIED,
            FixedValueState.READ_ERROR,
        }:
            coordinator.fail(
                "autostart_ownership_lost"
                if observation.state is FixedValueState.OCCUPIED
                else "autostart_timeline_probe_read_failed"
            )
            _persist_checkpoint(root, coordinator)
            _persist_terminal_summary(root, tracker, coordinator)
            return 2
        if (
            coordinator.lifecycle_state is ProbeLifecycleState.FINALIZING
            and coordinator.safe_code == "autostart_timeline_probe_aborted"
        ):
            coordinator.fail(coordinator.safe_code)
            _persist_checkpoint(root, coordinator)
            _persist_terminal_summary(root, tracker, coordinator)
            return 2
        if (
            coordinator.lifecycle_state is ProbeLifecycleState.FINALIZING
            and coordinator.current_phase == "T9-final"
        ):
            candidate = tracker.summarize()
            if candidate.safe_code == "autostart_run_value_timeline_verified":
                coordinator.complete()
            else:
                coordinator.fail(candidate.safe_code)
            _persist_checkpoint(root, coordinator)
            summary = _persist_terminal_summary(root, tracker, coordinator)
            return (
                0
                if summary.safe_code
                == "autostart_run_value_timeline_verified"
                else 2
            )
        sleeper(POLL_INTERVAL_SECONDS)


def _owner_ui_checkpoint_ready(session_nonce: str) -> bool:
    """Validate the product-side Qt readiness checkpoint for the T1 gate."""

    if not _valid_session_nonce(session_nonce):
        return False
    parent = (
        _repository_root() / OWNER_UI_EVIDENCE_PARENT_RELATIVE_PATH
    ).resolve(strict=False)
    root = parent / session_nonce
    checkpoint = root / "checkpoint.json"
    try:
        parent_metadata = parent.lstat()
        root_metadata = root.lstat()
        checkpoint_metadata = checkpoint.lstat()
    except OSError:
        return False
    if (
        _is_reparse_point(parent)
        or _is_reparse_point(root)
        or _is_reparse_point(checkpoint)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or not stat.S_ISREG(checkpoint_metadata.st_mode)
        or checkpoint_metadata.st_nlink != 1
        or checkpoint_metadata.st_size <= 0
        or checkpoint_metadata.st_size > OWNER_UI_CHECKPOINT_MAX_BYTES
        or root.parent != parent
        or root.name != session_nonce
        or (root / "checkpoint.json.part").exists()
    ):
        return False
    try:
        document = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(document, dict)
        or set(document)
        != {
            "events",
            "owner_ui_readiness_checkpoint",
            "schema_version",
            "session_nonce",
            "value_text_recorded",
        }
        or document.get("schema_version") != 1
        or document.get("owner_ui_readiness_checkpoint") is not True
        or document.get("session_nonce") != session_nonce
        or document.get("value_text_recorded") is not False
    ):
        return False
    events = document.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 20:
        return False
    ordered_stages = (
        "started",
        "arguments_validated",
        "single_instance_owner",
        "composition_root_created",
        "runtime_starting",
        "pet_window_created",
        "settings_loaded",
        "pet_window_visible",
        "tray_created",
        "tray_visible",
        "runtime_ready",
        "application_ready",
        "closing",
        "closed",
    )
    stage_order = {
        stage: index for index, stage in enumerate(ordered_stages, start=1)
    }
    required_stages = {
        "single_instance_owner",
        "runtime_ready",
        "pet_window_created",
        "pet_window_visible",
        "tray_created",
        "tray_visible",
        "application_ready",
    }
    seen: set[str] = set()
    last_order = 0
    last_elapsed = -1
    for expected_sequence, event in enumerate(events, start=1):
        if (
            not isinstance(event, dict)
            or set(event)
            != {
                "elapsed_milliseconds",
                "failure_category",
                "sequence",
                "stage",
            }
        ):
            return False
        sequence = event.get("sequence")
        elapsed = event.get("elapsed_milliseconds")
        stage = event.get("stage")
        failure = event.get("failure_category")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence != expected_sequence
            or not isinstance(elapsed, int)
            or isinstance(elapsed, bool)
            or elapsed < last_elapsed
            or not isinstance(stage, str)
            or stage not in stage_order
            or stage in seen
            or stage_order[stage] <= last_order
            or failure != "none"
        ):
            return False
        seen.add(stage)
        last_order = stage_order[stage]
        last_elapsed = elapsed
    return (
        events[-1].get("stage") == "application_ready"
        and required_stages <= seen
    )


def _set_phase(
    phase: str,
    *,
    evidence_root: str,
    expected_previous_phase: str,
    revision: int,
    session_nonce: str,
    stop: bool,
) -> int:
    if phase not in PHASES or expected_previous_phase not in PHASES:
        raise TimelineProbeError("The timeline phase is invalid.")
    root = _validated_evidence_root(evidence_root, must_exist=True)
    ready_nonce = _read_ready_session_nonce(root / "ready.json")
    if session_nonce != ready_nonce:
        raise TimelineProbeError("The timeline session nonce is invalid.")
    current = _read_control(root / "control.json")
    if (
        current.session_nonce != session_nonce
        or revision != current.revision + 1
        or expected_previous_phase != current.phase
        or PHASE_INDEX[phase] != PHASE_INDEX[current.phase] + 1
        or stop != (phase == "T9-final")
    ):
        raise TimelineProbeError("The timeline control sequence is invalid.")
    if phase == "T1":
        if not _owner_ui_checkpoint_ready(session_nonce):
            raise TimelineCoordinationError(
                "autostart_owner_ui_not_ready",
                "The Owner UI readiness checkpoint is incomplete.",
            )
        if query_fixed_run_value("").state is not FixedValueState.ABSENT:
            raise TimelineCoordinationError(
                "autostart_t1_registry_state_invalid",
                "The fixed Run value is not absent at T1.",
            )
    _write_json_atomically(
        root / "control.json",
        _control_document(
            ControlMessage(
                schema_version=SCHEMA_VERSION,
                session_nonce=session_nonce,
                revision=revision,
                expected_previous_phase=expected_previous_phase,
                phase=phase,
                stop=stop,
                abort=False,
            )
        ),
    )
    return 0


def _abort_probe(
    *,
    evidence_root: str,
    expected_previous_phase: str,
    revision: int,
    session_nonce: str,
) -> int:
    if expected_previous_phase not in PHASES:
        raise TimelineProbeError("The timeline phase is invalid.")
    root = _validated_evidence_root(evidence_root, must_exist=True)
    ready_nonce = _read_ready_session_nonce(root / "ready.json")
    current = _read_control(root / "control.json")
    if (
        session_nonce != ready_nonce
        or current.session_nonce != session_nonce
        or expected_previous_phase != current.phase
        or revision != current.revision + 1
    ):
        raise TimelineProbeError("The timeline abort request is invalid.")
    _write_json_atomically(
        root / "control.json",
        _control_document(
            ControlMessage(
                schema_version=SCHEMA_VERSION,
                session_nonce=session_nonce,
                revision=revision,
                expected_previous_phase=expected_previous_phase,
                phase=current.phase,
                stop=False,
                abort=True,
            )
        ),
    )
    return 0


def _set_owner_pid(
    process_id: int,
    *,
    evidence_root: str,
    session_nonce: str,
    identity_probe: ProcessIdentityProbe = _process_identity,
) -> int:
    if process_id <= 0:
        raise TimelineProbeError("Owner process data is invalid.")
    root = _validated_evidence_root(evidence_root, must_exist=True)
    ready_nonce = _read_ready_session_nonce(root / "ready.json")
    current = _read_control(root / "control.json")
    if (
        session_nonce != ready_nonce
        or current.session_nonce != session_nonce
        or current.phase != "T0"
        or current.revision != 0
        or (root / "owner-pid.json").exists()
    ):
        raise TimelineProbeError("Owner process data is invalid.")
    identity = identity_probe(process_id)
    if identity is None:
        raise TimelineProbeError("Owner process data is invalid.")
    _write_json_atomically(
        root / "owner-pid.json",
        asdict(
            OwnerRegistration(
                schema_version=SCHEMA_VERSION,
                session_nonce=session_nonce,
                process_id=process_id,
                process_identity=identity,
            )
        ),
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--confirm-real-registry", action="store_true")
    modes.add_argument("--set-phase", choices=PHASES)
    modes.add_argument("--set-owner-pid", type=int)
    modes.add_argument("--abort", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--evidence-root", default="")
    parser.add_argument("--session-nonce", default="")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--expected-previous-phase", choices=PHASES)
    parser.add_argument("--expected-executable-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.confirm_real_registry:
            if (
                arguments.stop
                or arguments.revision is not None
                or arguments.expected_previous_phase is not None
            ):
                raise TimelineProbeError("Timeline control data is invalid.")
            expected = str(arguments.expected_executable_sha256)
            nonce = str(arguments.session_nonce)
            evidence_root = str(arguments.evidence_root)
            if (
                len(expected) != 64
                or expected != expected.casefold()
                or any(character not in "0123456789abcdef" for character in expected)
                or not _valid_session_nonce(nonce)
                or not evidence_root
            ):
                raise TimelineProbeError(
                    "The expected executable digest is invalid."
                )
            return _run_real_observer(expected, evidence_root, nonce)
        if arguments.set_phase is not None:
            nonce = str(arguments.session_nonce)
            revision = arguments.revision
            previous = arguments.expected_previous_phase
            if (
                not _valid_session_nonce(nonce)
                or not isinstance(revision, int)
                or revision <= 0
                or previous is None
            ):
                raise TimelineProbeError("Timeline control data is invalid.")
            return _set_phase(
                str(arguments.set_phase),
                evidence_root=str(arguments.evidence_root),
                expected_previous_phase=str(previous),
                revision=revision,
                session_nonce=nonce,
                stop=bool(arguments.stop),
            )
        if arguments.set_owner_pid is not None:
            nonce = str(arguments.session_nonce)
            if not _valid_session_nonce(nonce):
                raise TimelineProbeError("Owner process data is invalid.")
            return _set_owner_pid(
                int(arguments.set_owner_pid),
                evidence_root=str(arguments.evidence_root),
                session_nonce=nonce,
            )
        if arguments.abort:
            nonce = str(arguments.session_nonce)
            revision = arguments.revision
            previous = arguments.expected_previous_phase
            if (
                not _valid_session_nonce(nonce)
                or not isinstance(revision, int)
                or revision <= 0
                or previous is None
                or arguments.stop
            ):
                raise TimelineProbeError("The timeline abort request is invalid.")
            return _abort_probe(
                evidence_root=str(arguments.evidence_root),
                expected_previous_phase=str(previous),
                revision=revision,
                session_nonce=nonce,
            )
        if (
            arguments.stop
            or arguments.evidence_root
            or arguments.session_nonce
            or arguments.revision is not None
            or arguments.expected_previous_phase is not None
            or arguments.expected_executable_sha256
        ):
            raise TimelineProbeError("Timeline control data is invalid.")
        print(
            "autostart_run_timeline_probe=false "
            "safe_code=autostart_timeline_probe_disabled"
        )
        return 0
    except TimelineCoordinationError as error:
        print(
            "autostart_run_timeline_probe=false "
            f"safe_code={error.safe_code}"
        )
        return 2
    except TimelineProbeError:
        print(
            "autostart_run_timeline_probe=false "
            "safe_code=autostart_timeline_probe_failed"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
