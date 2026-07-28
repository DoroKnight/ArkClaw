from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODEL_PATH = _PROJECT_ROOT / "packaging/packaged_runtime_supervisor_model.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_packaged_runtime_supervisor_model_test",
        _MODEL_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MODEL: Any = _load_module()
SafeFailureCategory = _MODEL.SafeFailureCategory
FaultPoint = _MODEL.FaultPoint
SupervisorCheckpoint = _MODEL.SupervisorCheckpoint
SupervisorScenario = _MODEL.SupervisorScenario
SupervisorPhase = _MODEL.SupervisorPhase
run_independent_cleanup_steps = _MODEL.run_independent_cleanup_steps
safe_code_for_category = _MODEL.safe_code_for_category
simulate_supervisor_boundary = _MODEL.simulate_supervisor_boundary


def test_success_lifecycle_uses_every_required_phase() -> None:
    checkpoint = SupervisorCheckpoint()

    for phase in (
        SupervisorPhase.PRECONDITIONS_VALIDATED,
        SupervisorPhase.CHILD_CREATED,
        SupervisorPhase.CHILD_RUNNING,
        SupervisorPhase.OBSERVING,
        SupervisorPhase.OBSERVING,
        SupervisorPhase.CHILD_EXIT_OBSERVED,
        SupervisorPhase.FINALIZING,
        SupervisorPhase.COMPLETED,
    ):
        checkpoint.transition(phase)

    assert checkpoint.supervisor_phase is SupervisorPhase.COMPLETED
    assert checkpoint.phase_sequence == 8


@pytest.mark.parametrize(
    "phase",
    [
        SupervisorPhase.CREATED,
        SupervisorPhase.PRECONDITIONS_VALIDATED,
        SupervisorPhase.CHILD_CREATED,
        SupervisorPhase.CHILD_RUNNING,
        SupervisorPhase.OBSERVING,
        SupervisorPhase.CHILD_EXIT_OBSERVED,
        SupervisorPhase.FINALIZING,
    ],
)
def test_every_nonterminal_phase_can_fail_closed(phase: Any) -> None:
    checkpoint = SupervisorCheckpoint(supervisor_phase=phase)

    checkpoint.transition(SupervisorPhase.SUPERVISOR_FAILED)

    assert checkpoint.supervisor_phase is SupervisorPhase.SUPERVISOR_FAILED


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (SupervisorPhase.CREATED, SupervisorPhase.CHILD_RUNNING),
        (SupervisorPhase.PRECONDITIONS_VALIDATED, SupervisorPhase.OBSERVING),
        (SupervisorPhase.CHILD_CREATED, SupervisorPhase.FINALIZING),
        (SupervisorPhase.OBSERVING, SupervisorPhase.COMPLETED),
        (SupervisorPhase.COMPLETED, SupervisorPhase.SUPERVISOR_FAILED),
        (SupervisorPhase.SUPERVISOR_FAILED, SupervisorPhase.CREATED),
    ],
)
def test_illegal_lifecycle_transitions_are_rejected(source: Any, target: Any) -> None:
    checkpoint = SupervisorCheckpoint(supervisor_phase=source)

    with pytest.raises(ValueError, match="invalid supervisor phase transition"):
        checkpoint.transition(target)


def test_checkpoint_serialization_contains_only_safe_state() -> None:
    checkpoint = SupervisorCheckpoint(
        supervisor_phase=SupervisorPhase.OBSERVING,
        child_pid=41234,
        child_created=True,
        child_running=True,
        poll_attempt_count=3,
        successful_poll_count=2,
        raw_observation_count=2,
    )

    payload = checkpoint.to_safe_dict()

    assert payload["schema_version"] == 1
    assert payload["supervisor_phase"] == "observing"
    assert "environment" not in repr(payload).casefold()
    assert "exception" not in repr(payload).casefold()
    assert "endpoint" not in repr(payload).casefold()


def test_cleanup_continues_after_independent_failures() -> None:
    calls: list[str] = []

    def fail_first() -> None:
        calls.append("first")
        raise RuntimeError("sensitive internal detail")

    def succeed_second() -> None:
        calls.append("second")

    def fail_third() -> None:
        calls.append("third")
        raise ValueError("another internal detail")

    failures = run_independent_cleanup_steps(
        (fail_first, succeed_second, fail_third)
    )

    assert calls == ["first", "second", "third"]
    assert failures == 2


@pytest.mark.parametrize("category", list(SafeFailureCategory))
def test_failure_categories_map_to_fixed_safe_codes(category: Any) -> None:
    code = safe_code_for_category(category)

    assert " " not in code
    assert "internal detail" not in code
    if category is SafeFailureCategory.NONE:
        assert code == "supervisor_completed"
    else:
        assert code.startswith("packaged_runtime_supervisor_")
        assert code.endswith("_failed")


def test_empty_sampler_results_are_successful_observations() -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(samples=((), (), ()))
    )

    assert outcome.completed
    assert outcome.poll_attempt_count == 3
    assert outcome.successful_poll_count == 3
    assert outcome.raw_observation_count == 3
    assert outcome.unique_observation_count == 0
    assert outcome.residual_child_count == 0


def test_duplicate_records_are_aggregated_without_losing_raw_samples() -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(
            samples=(("endpoint-a", "endpoint-a"), ("endpoint-a",)),
        )
    )

    assert outcome.completed
    assert outcome.raw_observation_count == 3
    assert outcome.unique_observation_count == 1


@pytest.mark.parametrize(
    ("fault", "expected_code"),
    [
        (
            FaultPoint.SAMPLER_FIRST,
            "packaged_runtime_supervisor_sampler_failed",
        ),
        (
            FaultPoint.SAMPLER_MID,
            "packaged_runtime_supervisor_sampler_failed",
        ),
        (
            FaultPoint.RAW_WRITE,
            "packaged_runtime_supervisor_raw_write_failed",
        ),
        (
            FaultPoint.SUMMARY_WRITE,
            "packaged_runtime_supervisor_summary_write_failed",
        ),
        (
            FaultPoint.SERIALIZATION,
            "packaged_runtime_supervisor_serialization_failed",
        ),
        (
            FaultPoint.PROCESS_REFRESH,
            "packaged_runtime_supervisor_process_refresh_failed",
        ),
        (
            FaultPoint.PROCESS_WAIT,
            "packaged_runtime_supervisor_process_wait_failed",
        ),
        (
            FaultPoint.CANCELLED,
            "packaged_runtime_supervisor_cancelled_failed",
        ),
    ],
)
def test_inner_faults_write_terminal_state_and_retain_child_reference(
    fault: Any,
    expected_code: str,
) -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(fault=fault),
    )

    assert not outcome.completed
    assert outcome.safe_code == expected_code
    assert outcome.phase is SupervisorPhase.SUPERVISOR_FAILED
    assert outcome.terminal_summary_written
    assert outcome.child_reference_retained
    assert outcome.cleanup_attempt_count >= 3
    assert outcome.residual_child_count == 0


def test_sampler_mid_failure_preserves_first_successful_poll() -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(
            samples=(("endpoint-a",), ("endpoint-b",), ("endpoint-c",)),
            fault=FaultPoint.SAMPLER_MID,
        )
    )

    assert outcome.poll_attempt_count == 2
    assert outcome.successful_poll_count == 1
    assert outcome.raw_observation_count == 1
    assert outcome.unique_observation_count == 1


@pytest.mark.parametrize(
    ("existing_result", "partial_file"),
    [(True, False), (False, True)],
)
def test_existing_or_partial_results_fail_before_child_creation(
    existing_result: bool,
    partial_file: bool,
) -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(
            result_already_exists=existing_result,
            partial_file_exists=partial_file,
        )
    )

    assert not outcome.completed
    assert outcome.safe_code == "packaged_runtime_supervisor_precondition_failed"
    assert not outcome.child_reference_retained
    assert outcome.cleanup_attempt_count == 0
    assert outcome.terminal_summary_written


def test_child_early_exit_still_finalizes_normally() -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(samples=()),
    )

    assert outcome.completed
    assert outcome.poll_attempt_count == 0
    assert outcome.terminal_summary_written


def test_child_refusing_stop_is_force_cleaned_without_losing_reference() -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(
            child_exits_normally=False,
            child_refuses_stop=True,
        )
    )

    assert not outcome.completed
    assert outcome.child_reference_retained
    assert outcome.cleanup_attempt_count == 4
    assert outcome.residual_child_count == 0
    assert outcome.terminal_summary_written


def test_cleanup_step_failure_does_not_skip_remaining_cleanup() -> None:
    outcome = simulate_supervisor_boundary(
        SupervisorScenario(fault=FaultPoint.CLEANUP_STEP),
    )

    assert not outcome.completed or outcome.cleanup_failure_count == 1
    assert outcome.cleanup_attempt_count == 3
    assert outcome.cleanup_failure_count == 1
    assert outcome.residual_child_count == 0
