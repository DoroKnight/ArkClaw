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
from typing import Protocol

SCHEMA_VERSION = 1
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "SJTUClaw"
AUTOSTART_ARGUMENT = "--startup"
REGISTRY_STRING_VALUE_TYPE = 1
POLL_INTERVAL_SECONDS = 0.2
MAX_RUNTIME_SECONDS = 15 * 60
MAX_POLL_COUNT = 4_500
EXPECTED_EXECUTABLE_RELATIVE_PATH = Path("dist/SJTUClaw.dist/SJTUClaw.exe")
EVIDENCE_RELATIVE_PATH = Path("build/autostart-run-timeline-probe")
PHASES = (
    "T0",
    "T1",
    "T2",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7-before-shutdown",
    "T8",
    "T9",
)


class TimelineProbeError(RuntimeError):
    """Fixed-message probe failure without registry or path disclosure."""


class FixedValueState(StrEnum):
    """Safe classification that never contains registry value text."""

    ABSENT = "absent"
    OWNED = "owned"
    OCCUPIED = "occupied"
    READ_ERROR = "read_error"


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
    process_exit_sequence: int | None
    disappearance_interval: str | None
    phase_states: Mapping[str, str]
    observer_registry_write_count: int = 0
    observer_registry_delete_count: int = 0
    value_text_recorded: bool = False
    other_value_enumeration_count: int = 0
    startup_approved_access_count: int = 0


class ValueReader(Protocol):
    def __call__(self, expected_command: str) -> SafeValueObservation: ...


class ProcessProbe(Protocol):
    def __call__(self, process_id: int) -> bool: ...


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

    def summarize(self, *, timed_out: bool = False) -> TimelineSummary:
        states = [record for record in self.records]
        if timed_out:
            safe_code = "autostart_timeline_probe_timeout"
        elif any(record.query_error for record in states):
            safe_code = "autostart_timeline_probe_read_failed"
        elif any(record.present and not record.owned for record in states):
            safe_code = "autostart_ownership_lost"
        elif self.first_owned_sequence is None:
            safe_code = "autostart_value_never_persisted"
        elif self.first_absent_after_owned_sequence is not None:
            safe_code = (
                "autostart_value_removed_during_runtime"
                if self._absent_after_owned_while_running()
                else "autostart_value_removed_after_process_exit"
            )
        elif self._required_terminal_phases_owned():
            safe_code = "autostart_run_value_timeline_verified"
        else:
            safe_code = "autostart_timeline_probe_incomplete"
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
            process_exit_sequence=self.process_exit_sequence,
            disappearance_interval=self._disappearance_interval(),
            phase_states={
                phase: state.value
                for phase, state in sorted(self._phase_states.items())
            },
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

    def _absent_after_owned_while_running(self) -> bool:
        sequence = self.first_absent_after_owned_sequence
        if sequence is None:
            return False
        return self.records[sequence - 1].process_running

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
        last_owned_phase = previous_phases[-1] if previous_phases else "T2"
        return f"{last_owned_phase}_to_{record.phase}"

    def _required_terminal_phases_owned(self) -> bool:
        return all(
            self._phase_states.get(phase) is FixedValueState.OWNED
            for phase in ("T3", "T4", "T5", "T6", "T7-before-shutdown", "T8", "T9")
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
    except Exception as error:
        raise TimelineProbeError(
            "Timeline evidence could not be written safely."
        ) from error
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _read_control(path: Path) -> tuple[str, bool]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TimelineProbeError("Timeline control data is invalid.") from error
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "phase",
        "stop",
    }:
        raise TimelineProbeError("Timeline control data is invalid.")
    phase = document.get("phase")
    stop = document.get("stop")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or not isinstance(phase, str)
        or phase not in PHASES
        or not isinstance(stop, bool)
    ):
        raise TimelineProbeError("Timeline control data is invalid.")
    return phase, stop


def _read_owner_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TimelineProbeError("Owner process data is invalid.") from error
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "pid",
    }:
        raise TimelineProbeError("Owner process data is invalid.")
    process_id = document.get("pid")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or not isinstance(process_id, int)
        or isinstance(process_id, bool)
        or process_id <= 0
    ):
        raise TimelineProbeError("Owner process data is invalid.")
    return process_id


def _process_is_running(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _repository_root() -> Path:
    return Path(__file__).resolve(strict=True).parents[1]


def _evidence_root() -> Path:
    return _repository_root() / EVIDENCE_RELATIVE_PATH


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


def _run_real_observer(
    expected_sha256: str,
    *,
    reader: ValueReader = query_fixed_run_value,
    process_probe: ProcessProbe = _process_is_running,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    root = _evidence_root()
    if root.exists():
        raise TimelineProbeError("The timeline evidence directory is occupied.")
    root.mkdir(parents=False)
    _, expected_command = _authoritative_executable(expected_sha256)
    control_path = root / "control.json"
    owner_path = root / "owner-pid.json"
    _write_json_atomically(
        control_path,
        {"schema_version": SCHEMA_VERSION, "phase": "T0", "stop": False},
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
        summary = tracker.summarize()
        summary_document = asdict(summary)
        summary_document["safe_code"] = safe_code
        _write_json_atomically(root / "terminal-summary.json", summary_document)
        _write_json_atomically(
            root / "ready.json",
            {
                "schema_version": SCHEMA_VERSION,
                "observer_ready": False,
                "safe_code": safe_code,
                "value_text_recorded": False,
            },
        )
        return 2
    _write_json_atomically(
        root / "ready.json",
        {
            "schema_version": SCHEMA_VERSION,
            "observer_ready": True,
            "safe_code": "autostart_timeline_observer_ready",
            "value_text_recorded": False,
        },
    )
    started = monotonic()
    timed_out = False
    for _ in range(MAX_POLL_COUNT):
        phase, stop = _read_control(control_path)
        process_id = _read_owner_pid(owner_path)
        running = (
            process_id is not None and process_probe(process_id)
        )
        observation = reader(expected_command)
        record = tracker.observe(phase, running, observation)
        if record is not None:
            _persist_tracker(root, tracker)
        if observation.state in {
            FixedValueState.OCCUPIED,
            FixedValueState.READ_ERROR,
        }:
            break
        if stop:
            break
        if monotonic() - started >= MAX_RUNTIME_SECONDS:
            timed_out = True
            break
        sleeper(POLL_INTERVAL_SECONDS)
    else:
        timed_out = True
    summary = tracker.summarize(timed_out=timed_out)
    _write_json_atomically(root / "terminal-summary.json", asdict(summary))
    return 0 if summary.safe_code == "autostart_run_value_timeline_verified" else 2


def _set_phase(phase: str, *, stop: bool) -> int:
    if phase not in PHASES:
        raise TimelineProbeError("The timeline phase is invalid.")
    root = _evidence_root()
    if not (root / "ready.json").is_file():
        raise TimelineProbeError("The timeline observer is not ready.")
    _write_json_atomically(
        root / "control.json",
        {"schema_version": SCHEMA_VERSION, "phase": phase, "stop": stop},
    )
    return 0


def _set_owner_pid(process_id: int) -> int:
    if process_id <= 0:
        raise TimelineProbeError("Owner process data is invalid.")
    root = _evidence_root()
    if not (root / "ready.json").is_file():
        raise TimelineProbeError("The timeline observer is not ready.")
    _write_json_atomically(
        root / "owner-pid.json",
        {"schema_version": SCHEMA_VERSION, "pid": process_id},
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--confirm-real-registry", action="store_true")
    modes.add_argument("--set-phase", choices=PHASES)
    modes.add_argument("--set-owner-pid", type=int)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--expected-executable-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.confirm_real_registry:
            expected = str(arguments.expected_executable_sha256)
            if (
                len(expected) != 64
                or expected != expected.casefold()
                or any(character not in "0123456789abcdef" for character in expected)
            ):
                raise TimelineProbeError(
                    "The expected executable digest is invalid."
                )
            return _run_real_observer(expected)
        if arguments.set_phase is not None:
            return _set_phase(str(arguments.set_phase), stop=bool(arguments.stop))
        if arguments.set_owner_pid is not None:
            return _set_owner_pid(int(arguments.set_owner_pid))
        print(
            "autostart_run_timeline_probe=false "
            "safe_code=autostart_timeline_probe_disabled"
        )
        return 0
    except TimelineProbeError:
        print(
            "autostart_run_timeline_probe=false "
            "safe_code=autostart_timeline_probe_failed"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
