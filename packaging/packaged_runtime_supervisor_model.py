"""Pure lifecycle and safe failure model for the PowerShell supervisor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class SupervisorPhase(StrEnum):
    CREATED = "created"
    PRECONDITIONS_VALIDATED = "preconditions_validated"
    CHILD_CREATED = "child_created"
    CHILD_RUNNING = "child_running"
    OBSERVING = "observing"
    CHILD_EXIT_OBSERVED = "child_exit_observed"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    SUPERVISOR_FAILED = "supervisor_failed"


class SafeFailureCategory(StrEnum):
    NONE = "none"
    PRECONDITION = "precondition"
    CHILD_CREATE = "child_create"
    SAMPLER = "sampler"
    PROCESS_REFRESH = "process_refresh"
    PROCESS_WAIT = "process_wait"
    RAW_WRITE = "raw_write"
    SUMMARY_WRITE = "summary_write"
    SERIALIZATION = "serialization"
    CLEANUP = "cleanup"
    CANCELLED = "cancelled"
    UNKNOWN_SAFE_CATEGORY = "unknown_safe_category"


class FaultPoint(StrEnum):
    NONE = "none"
    SAMPLER_FIRST = "sampler_first"
    SAMPLER_MID = "sampler_mid"
    RAW_WRITE = "raw_write"
    SUMMARY_WRITE = "summary_write"
    SERIALIZATION = "serialization"
    PROCESS_REFRESH = "process_refresh"
    PROCESS_WAIT = "process_wait"
    CLEANUP_STEP = "cleanup_step"
    CANCELLED = "cancelled"


_TRANSITIONS: dict[SupervisorPhase, frozenset[SupervisorPhase]] = {
    SupervisorPhase.CREATED: frozenset(
        {
            SupervisorPhase.PRECONDITIONS_VALIDATED,
            SupervisorPhase.SUPERVISOR_FAILED,
        }
    ),
    SupervisorPhase.PRECONDITIONS_VALIDATED: frozenset(
        {SupervisorPhase.CHILD_CREATED, SupervisorPhase.SUPERVISOR_FAILED}
    ),
    SupervisorPhase.CHILD_CREATED: frozenset(
        {SupervisorPhase.CHILD_RUNNING, SupervisorPhase.SUPERVISOR_FAILED}
    ),
    SupervisorPhase.CHILD_RUNNING: frozenset(
        {
            SupervisorPhase.OBSERVING,
            SupervisorPhase.CHILD_EXIT_OBSERVED,
            SupervisorPhase.SUPERVISOR_FAILED,
        }
    ),
    SupervisorPhase.OBSERVING: frozenset(
        {
            SupervisorPhase.OBSERVING,
            SupervisorPhase.CHILD_EXIT_OBSERVED,
            SupervisorPhase.SUPERVISOR_FAILED,
        }
    ),
    SupervisorPhase.CHILD_EXIT_OBSERVED: frozenset(
        {SupervisorPhase.FINALIZING, SupervisorPhase.SUPERVISOR_FAILED}
    ),
    SupervisorPhase.FINALIZING: frozenset(
        {SupervisorPhase.COMPLETED, SupervisorPhase.SUPERVISOR_FAILED}
    ),
    SupervisorPhase.COMPLETED: frozenset(),
    SupervisorPhase.SUPERVISOR_FAILED: frozenset(),
}


@dataclass(slots=True)
class SupervisorCheckpoint:
    supervisor_phase: SupervisorPhase = SupervisorPhase.CREATED
    phase_sequence: int = 0
    child_pid: int | None = None
    child_created: bool = False
    child_running: bool = False
    child_exit_observed: bool = False
    poll_attempt_count: int = 0
    successful_poll_count: int = 0
    raw_observation_count: int = 0
    terminal_summary_written: bool = False
    safe_code: str = "supervisor_in_progress"

    def transition(self, phase: SupervisorPhase) -> None:
        if phase not in _TRANSITIONS[self.supervisor_phase]:
            raise ValueError("invalid supervisor phase transition")
        self.supervisor_phase = phase
        self.phase_sequence += 1

    def to_safe_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "schema_version": 1,
            "supervisor_phase": self.supervisor_phase.value,
            "phase_sequence": self.phase_sequence,
            "child_pid": self.child_pid,
            "child_created": self.child_created,
            "child_running": self.child_running,
            "child_exit_observed": self.child_exit_observed,
            "poll_attempt_count": self.poll_attempt_count,
            "successful_poll_count": self.successful_poll_count,
            "raw_observation_count": self.raw_observation_count,
            "terminal_summary_written": self.terminal_summary_written,
            "safe_code": self.safe_code,
        }


@dataclass(frozen=True, slots=True)
class SupervisorScenario:
    samples: tuple[tuple[str, ...], ...] = ((), (), ())
    fault: FaultPoint = FaultPoint.NONE
    child_exits_normally: bool = True
    child_refuses_stop: bool = False
    result_already_exists: bool = False
    partial_file_exists: bool = False


@dataclass(frozen=True, slots=True)
class BoundaryOutcome:
    completed: bool
    safe_code: str
    phase: SupervisorPhase
    poll_attempt_count: int
    successful_poll_count: int
    raw_observation_count: int
    unique_observation_count: int
    terminal_summary_written: bool
    cleanup_attempt_count: int
    cleanup_failure_count: int
    child_reference_retained: bool
    residual_child_count: int


def _category_for_fault(fault: FaultPoint) -> SafeFailureCategory:
    return {
        FaultPoint.NONE: SafeFailureCategory.NONE,
        FaultPoint.SAMPLER_FIRST: SafeFailureCategory.SAMPLER,
        FaultPoint.SAMPLER_MID: SafeFailureCategory.SAMPLER,
        FaultPoint.RAW_WRITE: SafeFailureCategory.RAW_WRITE,
        FaultPoint.SUMMARY_WRITE: SafeFailureCategory.SUMMARY_WRITE,
        FaultPoint.SERIALIZATION: SafeFailureCategory.SERIALIZATION,
        FaultPoint.PROCESS_REFRESH: SafeFailureCategory.PROCESS_REFRESH,
        FaultPoint.PROCESS_WAIT: SafeFailureCategory.PROCESS_WAIT,
        FaultPoint.CLEANUP_STEP: SafeFailureCategory.CLEANUP,
        FaultPoint.CANCELLED: SafeFailureCategory.CANCELLED,
    }[fault]


def simulate_supervisor_boundary(scenario: SupervisorScenario) -> BoundaryOutcome:
    """Exercise deterministic inner/outer boundary behavior without processes."""

    checkpoint = SupervisorCheckpoint()
    child_reference_retained = False
    poll_attempt_count = 0
    successful_poll_count = 0
    raw_observation_count = 0
    observations: set[str] = set()
    cleanup_attempt_count = 0
    cleanup_failure_count = 0
    terminal_summary_written = False
    completed = False
    category = SafeFailureCategory.NONE
    try:
        if scenario.result_already_exists or scenario.partial_file_exists:
            category = SafeFailureCategory.PRECONDITION
            raise RuntimeError("safe fixture failure")
        checkpoint.transition(SupervisorPhase.PRECONDITIONS_VALIDATED)
        checkpoint.transition(SupervisorPhase.CHILD_CREATED)
        child_reference_retained = True
        checkpoint.transition(SupervisorPhase.CHILD_RUNNING)
        for index, sample in enumerate(scenario.samples, start=1):
            poll_attempt_count += 1
            if scenario.fault is FaultPoint.PROCESS_WAIT:
                category = SafeFailureCategory.PROCESS_WAIT
                raise RuntimeError("safe fixture failure")
            if scenario.fault is FaultPoint.PROCESS_REFRESH:
                category = SafeFailureCategory.PROCESS_REFRESH
                raise RuntimeError("safe fixture failure")
            checkpoint.transition(SupervisorPhase.OBSERVING)
            if (
                scenario.fault is FaultPoint.SAMPLER_FIRST
                or (
                    scenario.fault is FaultPoint.SAMPLER_MID
                    and index == 2
                )
            ):
                category = SafeFailureCategory.SAMPLER
                raise RuntimeError("safe fixture failure")
            successful_poll_count += 1
            if scenario.fault is FaultPoint.SERIALIZATION:
                category = SafeFailureCategory.SERIALIZATION
                raise RuntimeError("safe fixture failure")
            if scenario.fault is FaultPoint.RAW_WRITE:
                category = SafeFailureCategory.RAW_WRITE
                raise RuntimeError("safe fixture failure")
            raw_observation_count += max(1, len(sample))
            observations.update(sample)
            if scenario.fault is FaultPoint.CANCELLED:
                category = SafeFailureCategory.CANCELLED
                raise RuntimeError("safe fixture cancellation")
        if not scenario.child_exits_normally:
            category = SafeFailureCategory.PROCESS_WAIT
            raise RuntimeError("safe fixture failure")
        checkpoint.transition(SupervisorPhase.CHILD_EXIT_OBSERVED)
        checkpoint.transition(SupervisorPhase.FINALIZING)
        if scenario.fault is FaultPoint.SUMMARY_WRITE:
            category = SafeFailureCategory.SUMMARY_WRITE
            raise RuntimeError("safe fixture failure")
        terminal_summary_written = True
        checkpoint.transition(SupervisorPhase.COMPLETED)
        completed = True
    except RuntimeError:
        if category is SafeFailureCategory.NONE:
            category = _category_for_fault(scenario.fault)
        if checkpoint.supervisor_phase not in {
            SupervisorPhase.COMPLETED,
            SupervisorPhase.SUPERVISOR_FAILED,
        }:
            checkpoint.transition(SupervisorPhase.SUPERVISOR_FAILED)
    finally:
        if child_reference_retained:
            cleanup_attempt_count += 3
            if scenario.fault is FaultPoint.CLEANUP_STEP:
                cleanup_failure_count += 1
                category = SafeFailureCategory.CLEANUP
                completed = False
            if scenario.child_refuses_stop:
                cleanup_attempt_count += 1
        if not completed:
            terminal_summary_written = True
            if checkpoint.supervisor_phase is SupervisorPhase.COMPLETED:
                checkpoint.supervisor_phase = SupervisorPhase.SUPERVISOR_FAILED
    safe_code = (
        "supervisor_completed"
        if completed
        else safe_code_for_category(category)
    )
    return BoundaryOutcome(
        completed=completed,
        safe_code=safe_code,
        phase=checkpoint.supervisor_phase,
        poll_attempt_count=poll_attempt_count,
        successful_poll_count=successful_poll_count,
        raw_observation_count=raw_observation_count,
        unique_observation_count=len(observations),
        terminal_summary_written=terminal_summary_written,
        cleanup_attempt_count=cleanup_attempt_count,
        cleanup_failure_count=cleanup_failure_count,
        child_reference_retained=child_reference_retained,
        residual_child_count=0,
    )


def run_independent_cleanup_steps(
    steps: tuple[Callable[[], None], ...],
) -> int:
    """Run every cleanup step even when an earlier independent step fails."""

    failure_count = 0
    for step in steps:
        try:
            step()
        except Exception:
            failure_count += 1
    return failure_count


def safe_code_for_category(category: SafeFailureCategory) -> str:
    if category is SafeFailureCategory.NONE:
        return "supervisor_completed"
    return f"packaged_runtime_supervisor_{category.value}_failed"
