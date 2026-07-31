from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROBE_PATH = _PROJECT_ROOT / "packaging/autostart_run_timeline_probe.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_autostart_run_timeline_probe_test",
        _PROBE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe: Any = _load_module()


EXPECTED = '"D:\\fixed\\SJTUClaw.exe" --startup'
TEST_SECRET = "unsafe-autostart-timeline-value-never-record"
NONCE = "0123456789abcdef0123456789abcdef"
OTHER_NONCE = "fedcba9876543210fedcba9876543210"
OWNER_IDENTITY = "0123456789abcdef"


class FakeClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.current = initial

    def monotonic(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def _coordinator(
    clock: FakeClock,
    **timeouts: float,
) -> probe.ProbeCoordinator:
    coordinator = probe.ProbeCoordinator(
        NONCE,
        clock.monotonic(),
        **timeouts,
    )
    coordinator.mark_ready(clock.monotonic())
    return coordinator


def _registration(
    *,
    nonce: str = NONCE,
    identity: str = OWNER_IDENTITY,
) -> probe.OwnerRegistration:
    return probe.OwnerRegistration(
        schema_version=probe.SCHEMA_VERSION,
        session_nonce=nonce,
        process_id=1234,
        process_identity=identity,
    )


def _control(
    phase: str,
    revision: int,
    previous: str,
    *,
    nonce: str = NONCE,
    stop: bool = False,
    abort: bool = False,
) -> probe.ControlMessage:
    return probe.ControlMessage(
        schema_version=probe.SCHEMA_VERSION,
        session_nonce=nonce,
        revision=revision,
        expected_previous_phase=previous,
        phase=phase,
        stop=stop,
        abort=abort,
    )


def _owned() -> probe.SafeValueObservation:
    return probe.SafeValueObservation.from_stored_value(
        EXPECTED,
        probe.REGISTRY_STRING_VALUE_TYPE,
        EXPECTED,
    )


def _occupied(
    value: object = TEST_SECRET,
    value_type: object = probe.REGISTRY_STRING_VALUE_TYPE,
) -> probe.SafeValueObservation:
    return probe.SafeValueObservation.from_stored_value(
        value,
        value_type,
        EXPECTED,
    )


def _write_owner_ui_checkpoint(
    repository: Path,
    *,
    nonce: str = NONCE,
    stages: tuple[str, ...] | None = None,
) -> Path:
    selected = stages or (
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
    )
    root = (
        repository
        / "build"
        / "autostart-owner-ui-readiness"
        / nonce
    )
    root.mkdir(parents=True)
    probe._write_json_atomically(
        root / "checkpoint.json",
        {
            "events": [
                {
                    "elapsed_milliseconds": index,
                    "failure_category": "none",
                    "sequence": index,
                    "stage": stage,
                }
                for index, stage in enumerate(selected, start=1)
            ],
            "owner_ui_readiness_checkpoint": True,
            "schema_version": 1,
            "session_nonce": nonce,
            "value_text_recorded": False,
        },
    )
    return root


def _write_control_root(repository: Path) -> Path:
    root = (
        repository
        / "build"
        / "autostart-run-timeline-probes"
        / "session-01"
    )
    root.mkdir(parents=True)
    probe._write_json_atomically(
        root / "ready.json",
        {
            "schema_version": probe.SCHEMA_VERSION,
            "observer_ready": True,
            "lifecycle_state": probe.ProbeLifecycleState.READY_UNARMED,
            "session_nonce": NONCE,
            "safe_code": "autostart_timeline_observer_ready",
            "value_text_recorded": False,
        },
    )
    probe._persist_checkpoint(root, _coordinator(FakeClock()))
    probe._write_json_atomically(
        root / "control.json",
        probe._control_document(
            probe.ControlMessage(
                schema_version=probe.SCHEMA_VERSION,
                session_nonce=NONCE,
                revision=0,
                expected_previous_phase=None,
                phase="T0",
                stop=False,
                abort=False,
            )
        ),
    )
    return root


def _complete_owned_timeline() -> probe.TimelineTracker:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T1", True, probe.SafeValueObservation.absent())
    tracker.observe(
        "T2-before-enable",
        True,
        probe.SafeValueObservation.absent(),
    )
    for phase in (
        "T3-after-enable",
        "T4",
        "T5",
        "T6",
        "T7-before-shutdown",
    ):
        tracker.observe(phase, True, _owned())
    tracker.observe("T8-after-process-exit", False, _owned())
    tracker.observe("T9-final", False, _owned())
    return tracker


def test_default_entry_is_inert(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_reader(expected_command: str) -> probe.SafeValueObservation:
        del expected_command
        raise AssertionError("The default entry must not access the registry.")

    monkeypatch.setattr(probe, "query_fixed_run_value", fail_reader)

    assert probe.main([]) == 0
    assert capsys.readouterr().out.strip() == (
        "autostart_run_timeline_probe=false "
        "safe_code=autostart_timeline_probe_disabled"
    )


def test_real_mode_requires_explicit_evidence_root_and_nonce(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_observer(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise AssertionError("The observer must not start without coordination.")

    monkeypatch.setattr(probe, "_run_real_observer", fail_observer)

    assert (
        probe.main(
            [
                "--confirm-real-registry",
                "--expected-executable-sha256",
                "0" * 64,
            ]
        )
        == 2
    )
    assert capsys.readouterr().out.strip() == (
        "autostart_run_timeline_probe=false "
        "safe_code=autostart_timeline_probe_failed"
    )


def test_safe_value_observation_accepts_only_exact_reg_sz() -> None:
    owned = _owned()
    wrong_text = _occupied()
    wrong_type = _occupied(EXPECTED, 7)
    non_string = _occupied(object(), probe.REGISTRY_STRING_VALUE_TYPE)

    assert owned.state is probe.FixedValueState.OWNED
    assert owned.type_valid
    assert owned.owned
    assert owned.length == len(EXPECTED)
    assert owned.sha256 is not None
    assert wrong_text.state is probe.FixedValueState.OCCUPIED
    assert wrong_text.type_valid
    assert not wrong_text.owned
    assert wrong_type.state is probe.FixedValueState.OCCUPIED
    assert not wrong_type.type_valid
    assert non_string.state is probe.FixedValueState.OCCUPIED
    assert non_string.length == 0
    assert non_string.sha256 is None


def test_always_absent_is_never_persisted() -> None:
    tracker = probe.TimelineTracker()
    for phase, running in (
        ("T0", False),
        ("T1", True),
        ("T2-before-enable", True),
        ("T3-after-enable", True),
        ("T8-after-process-exit", False),
        ("T9-final", False),
    ):
        tracker.observe(phase, running, probe.SafeValueObservation.absent())

    summary = tracker.summarize()

    assert summary.safe_code == "autostart_value_never_persisted"
    assert summary.first_present_sequence is None
    assert summary.first_owned_sequence is None


def test_value_appears_once_and_remains_owned() -> None:
    tracker = _complete_owned_timeline()

    summary = tracker.summarize()

    assert summary.safe_code == "autostart_run_value_timeline_verified"
    assert summary.first_present_sequence is not None
    assert summary.first_owned_sequence == summary.first_present_sequence
    assert summary.first_absent_after_owned_sequence is None
    assert summary.process_exit_sequence is not None


@pytest.mark.parametrize(
    ("absent_phase", "running", "expected_code"),
    [
        (
            "T3-after-enable",
            True,
            "autostart_value_removed_during_runtime",
        ),
        ("T4", True, "autostart_value_removed_during_runtime"),
        ("T5", True, "autostart_value_removed_during_runtime"),
        ("T6", True, "autostart_value_removed_during_runtime"),
        (
            "T8-after-process-exit",
            False,
            "autostart_value_removed_after_process_exit",
        ),
        (
            "T9-final",
            False,
            "autostart_value_removed_after_process_exit",
        ),
    ],
)
def test_value_disappearance_is_classified_by_process_lifetime(
    absent_phase: str,
    running: bool,
    expected_code: str,
) -> None:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T1", True, probe.SafeValueObservation.absent())
    tracker.observe("T2-before-enable", True, _owned())
    tracker.observe(absent_phase, running, probe.SafeValueObservation.absent())

    summary = tracker.summarize()

    assert summary.safe_code == expected_code
    assert summary.first_absent_after_owned_sequence is not None
    assert summary.first_absent_after_owned_phase == absent_phase


def test_t7_removal_before_owner_exit_is_shutdown_removal() -> None:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T1", True, probe.SafeValueObservation.absent())
    tracker.observe("T2-before-enable", True, _owned())
    tracker.observe("T7-before-shutdown", True, _owned())
    tracker.observe(
        "T7-before-shutdown",
        True,
        probe.SafeValueObservation.absent(),
    )

    summary = tracker.summarize()

    assert (
        summary.safe_code == "autostart_value_removed_during_shutdown"
    )
    assert summary.first_absent_after_owned_phase == "T7-before-shutdown"
    assert summary.owner_exit_observed_sequence is None


def test_adjacent_absence_and_owner_exit_uses_persisted_event_order() -> None:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T1", True, probe.SafeValueObservation.absent())
    tracker.observe("T3-after-enable", True, _owned())
    tracker.observe(
        "T7-before-shutdown",
        False,
        probe.SafeValueObservation.absent(),
    )

    summary = tracker.summarize()

    assert (
        summary.safe_code
        == "autostart_value_removed_after_process_exit"
    )
    assert (
        summary.owner_exit_observed_sequence
        == summary.first_absent_after_owned_sequence
    )


def test_backend_error_has_priority_over_ownership_loss() -> None:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T3-after-enable", True, _occupied())
    tracker.observe(
        "T4",
        True,
        probe.SafeValueObservation.read_error(),
    )

    assert (
        tracker.summarize().safe_code
        == "autostart_timeline_probe_read_failed"
    )


def test_external_replacement_and_wrong_type_are_ownership_loss() -> None:
    for observation in (_occupied(), _occupied(EXPECTED, 7)):
        tracker = probe.TimelineTracker()
        tracker.observe("T0", False, probe.SafeValueObservation.absent())
        tracker.observe("T2-before-enable", True, _owned())
        tracker.observe("T3-after-enable", True, observation)

        summary = tracker.summarize()

        assert summary.safe_code == "autostart_ownership_lost"


def test_read_failure_and_timeout_use_fixed_codes() -> None:
    read_failure = probe.TimelineTracker()
    read_failure.observe("T0", False, probe.SafeValueObservation.read_error())
    timeout = probe.TimelineTracker()
    timeout.observe("T0", False, probe.SafeValueObservation.absent())

    assert (
        read_failure.summarize().safe_code
        == "autostart_timeline_probe_read_failed"
    )
    assert (
        timeout.summarize(timed_out=True).safe_code
        == "autostart_timeline_probe_timeout"
    )


def test_identical_poll_is_not_persisted_twice() -> None:
    tracker = probe.TimelineTracker()
    first = tracker.observe("T0", False, probe.SafeValueObservation.absent())
    duplicate = tracker.observe(
        "T0",
        False,
        probe.SafeValueObservation.absent(),
    )

    assert first is not None
    assert duplicate is None
    assert tracker.query_count == 2
    assert len(tracker.records) == 1


def test_atomic_writer_removes_part_file(tmp_path: Path) -> None:
    destination = tmp_path / "result.json"
    part = tmp_path / "result.json.part"
    part.write_text("stale", encoding="utf-8")

    probe._write_json_atomically(destination, {"safe_code": "none"})

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "safe_code": "none"
    }
    assert not part.exists()


def test_atomic_writer_failure_is_safe_and_cleans_part(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "result.json"

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise OSError(TEST_SECRET)

    monkeypatch.setattr(probe.os, "replace", fail_replace)

    with pytest.raises(probe.TimelineProbeError) as captured:
        probe._write_json_atomically(destination, {"safe_code": "none"})

    assert str(captured.value) == (
        "Timeline evidence could not be written safely."
    )
    assert TEST_SECRET not in str(captured.value)
    assert TEST_SECRET not in repr(captured.value)
    assert not (tmp_path / "result.json.part").exists()


def test_records_and_summary_never_store_value_text() -> None:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T2-before-enable", True, _occupied())

    visible = json.dumps(
        {
            "records": [probe.asdict(record) for record in tracker.records],
            "summary": probe.asdict(tracker.summarize()),
        },
        sort_keys=True,
    )

    assert TEST_SECRET not in visible
    assert EXPECTED not in visible
    assert '"value_text_recorded": false' in visible
    assert '"other_value_enumeration_count": 0' in visible
    assert '"startup_approved_access_count": 0' in visible


def test_invalid_phase_and_control_are_rejected(tmp_path: Path) -> None:
    tracker = probe.TimelineTracker()
    with pytest.raises(probe.TimelineProbeError):
        tracker.observe("invalid", False, probe.SafeValueObservation.absent())
    control = tmp_path / "control.json"
    control.write_text(
        json.dumps(
            {
                "schema_version": probe.SCHEMA_VERSION,
                "session_nonce": NONCE,
                "revision": 0,
                "expected_previous_phase": None,
                "phase": "T0",
                "stop": "false",
                "abort": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(probe.TimelineProbeError):
        probe._read_control(control)


def test_ready_unarmed_wait_does_not_consume_old_or_active_budget() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)

    clock.advance(15 * 60 + 1)

    assert coordinator.lifecycle_state is probe.ProbeLifecycleState.READY_UNARMED
    assert coordinator.active_started_at is None
    assert coordinator.timeout_code(clock.monotonic()) is None
    assert not hasattr(probe, "MAX_RUNTIME_SECONDS")


def test_t1_starts_active_budget_only_after_owner_registration() -> None:
    clock = FakeClock()
    coordinator = _coordinator(
        clock,
        stage_lease_seconds=probe.ACTIVE_TIMEOUT_SECONDS * 2,
    )
    coordinator.register_owner(_registration())
    clock.advance(20 * 60)

    coordinator.accept_control(
        _control("T1", 1, "T0"),
        clock.monotonic(),
        current_process_identity=OWNER_IDENTITY,
    )

    assert coordinator.lifecycle_state is probe.ProbeLifecycleState.ARMED
    assert coordinator.active_started_at == 20 * 60
    clock.advance(probe.ACTIVE_TIMEOUT_SECONDS - 1)
    assert coordinator.timeout_code(clock.monotonic()) is None
    clock.advance(1)
    assert (
        coordinator.timeout_code(clock.monotonic())
        == "autostart_timeline_active_timeout"
    )


def test_t1_requires_registered_live_owner() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)

    with pytest.raises(probe.TimelineCoordinationError) as captured:
        coordinator.accept_control(
            _control("T1", 1, "T0"),
            clock.monotonic(),
            current_process_identity=None,
        )

    assert captured.value.safe_code == "autostart_timeline_owner_missing"


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        (
            _control("T1", 0, "T0"),
            "autostart_timeline_control_revision_invalid",
        ),
        (
            _control("T1", 2, "T0"),
            "autostart_timeline_control_revision_invalid",
        ),
        (
            _control("T2-before-enable", 1, "T0"),
            "autostart_timeline_control_sequence_invalid",
        ),
        (
            _control("T1", 1, "T0", nonce=OTHER_NONCE),
            "autostart_timeline_nonce_mismatch",
        ),
    ],
)
def test_revision_phase_and_nonce_controls_fail_closed(
    message: probe.ControlMessage,
    expected_code: str,
) -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    coordinator.register_owner(_registration())

    with pytest.raises(probe.TimelineCoordinationError) as captured:
        coordinator.accept_control(
            message,
            clock.monotonic(),
            current_process_identity=OWNER_IDENTITY,
        )

    assert captured.value.safe_code == expected_code


def test_duplicate_and_stale_revision_are_rejected_after_t1() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    coordinator.register_owner(_registration())
    first = _control("T1", 1, "T0")
    coordinator.accept_control(
        first,
        clock.monotonic(),
        current_process_identity=OWNER_IDENTITY,
    )
    coordinator.begin_observing()

    with pytest.raises(probe.TimelineCoordinationError) as duplicate:
        coordinator.accept_control(
            first,
            clock.monotonic(),
            current_process_identity=OWNER_IDENTITY,
        )
    with pytest.raises(probe.TimelineCoordinationError) as stale:
        coordinator.accept_control(
            _control("T1", 0, "T0"),
            clock.monotonic(),
            current_process_identity=OWNER_IDENTITY,
        )

    assert (
        duplicate.value.safe_code
        == "autostart_timeline_control_revision_invalid"
    )
    assert stale.value.safe_code == "autostart_timeline_control_revision_invalid"


def test_normal_t1_through_t9_flow_and_owner_post_exit_observation() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    coordinator.register_owner(_registration())
    previous = "T0"
    for revision, phase in enumerate(probe.PHASES[1:], start=1):
        coordinator.accept_control(
            _control(
                phase,
                revision,
                previous,
                stop=phase == "T9-final",
            ),
            clock.monotonic(),
            current_process_identity=(
                OWNER_IDENTITY if phase == "T1" else None
            ),
        )
        if phase == "T1":
            coordinator.begin_observing()
        if phase == "T7-before-shutdown":
            assert coordinator.observe_owner_identity(None) is None
        clock.advance(1)
        previous = phase

    coordinator.complete()
    checkpoint = coordinator.checkpoint()

    assert coordinator.lifecycle_state is probe.ProbeLifecycleState.COMPLETED
    assert checkpoint.observer_terminal_state == "completed"
    assert checkpoint.owner_terminal_state == probe.OwnerTerminalState.EXITED
    assert checkpoint.revision == 9


def test_each_phase_refreshes_lease_without_resetting_active_budget() -> None:
    clock = FakeClock()
    coordinator = _coordinator(
        clock,
        active_timeout_seconds=100.0,
        stage_lease_seconds=10.0,
    )
    coordinator.register_owner(_registration())
    coordinator.accept_control(
        _control("T1", 1, "T0"),
        clock.monotonic(),
        current_process_identity=OWNER_IDENTITY,
    )
    coordinator.begin_observing()
    active_started = coordinator.active_started_at
    clock.advance(9)
    coordinator.accept_control(
        _control("T2-before-enable", 2, "T1"),
        clock.monotonic(),
        current_process_identity=OWNER_IDENTITY,
    )

    assert coordinator.active_started_at == active_started
    clock.advance(9)
    assert coordinator.timeout_code(clock.monotonic()) is None
    clock.advance(1)
    assert (
        coordinator.timeout_code(clock.monotonic())
        == "autostart_timeline_stage_timeout"
    )


def test_ready_active_and_total_timeouts_are_independent() -> None:
    ready_clock = FakeClock()
    ready = _coordinator(
        ready_clock,
        ready_timeout_seconds=10.0,
        total_timeout_seconds=100.0,
    )
    ready_clock.advance(10)
    assert (
        ready.timeout_code(ready_clock.monotonic())
        == "autostart_timeline_ready_timeout"
    )

    active_clock = FakeClock()
    active = _coordinator(
        active_clock,
        active_timeout_seconds=10.0,
        stage_lease_seconds=20.0,
        total_timeout_seconds=100.0,
    )
    active.register_owner(_registration())
    active.accept_control(
        _control("T1", 1, "T0"),
        active_clock.monotonic(),
        current_process_identity=OWNER_IDENTITY,
    )
    active.begin_observing()
    active_clock.advance(10)
    assert (
        active.timeout_code(active_clock.monotonic())
        == "autostart_timeline_active_timeout"
    )

    total_clock = FakeClock()
    total = _coordinator(
        total_clock,
        ready_timeout_seconds=100.0,
        total_timeout_seconds=10.0,
    )
    total_clock.advance(10)
    assert (
        total.timeout_code(total_clock.monotonic())
        == "autostart_timeline_total_timeout"
    )


def test_failed_observer_preserves_running_owner_for_supervisor() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    coordinator.register_owner(_registration())
    coordinator.fail("autostart_timeline_active_timeout")

    checkpoint = coordinator.checkpoint()

    assert checkpoint.observer_terminal_state == "failed"
    assert checkpoint.owner_terminal_state == probe.OwnerTerminalState.RUNNING
    assert checkpoint.supervisor_terminal_state == "awaiting_owner_safe_exit"
    assert checkpoint.owner_safe_exit_required


def test_owner_early_exit_and_pid_reuse_are_distinct() -> None:
    clock = FakeClock()
    early_exit = _coordinator(clock)
    early_exit.register_owner(_registration())
    assert (
        early_exit.observe_owner_identity(None)
        == "autostart_timeline_owner_exited_early"
    )

    reused = _coordinator(clock)
    reused.register_owner(_registration())
    assert (
        reused.observe_owner_identity("fedcba9876543210")
        == "autostart_timeline_owner_identity_lost"
    )
    assert reused.owner_terminal_state is probe.OwnerTerminalState.IDENTITY_LOST


def test_abort_is_explicit_and_stop_is_t9_only() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    abort = _control("T0", 1, "T0", abort=True)
    coordinator.accept_control(
        abort,
        clock.monotonic(),
        current_process_identity=None,
    )
    assert coordinator.lifecycle_state is probe.ProbeLifecycleState.FINALIZING
    assert coordinator.safe_code == "autostart_timeline_probe_aborted"

    invalid_stop = _coordinator(clock)
    invalid_stop.register_owner(_registration())
    with pytest.raises(probe.TimelineCoordinationError) as captured:
        invalid_stop.accept_control(
            _control("T1", 1, "T0", stop=True),
            clock.monotonic(),
            current_process_identity=OWNER_IDENTITY,
        )
    assert captured.value.safe_code == "autostart_timeline_stop_invalid"


def test_checkpoint_and_summary_writes_are_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    probe._persist_checkpoint(tmp_path, coordinator)
    coordinator.fail("autostart_timeline_ready_timeout")
    probe._persist_terminal_summary(tmp_path, tracker, coordinator)

    checkpoint = json.loads(
        (tmp_path / "observer-checkpoint.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (tmp_path / "terminal-summary.json").read_text(encoding="utf-8")
    )
    assert checkpoint["lifecycle_state"] == "ready_unarmed"
    assert summary["safe_code"] == "autostart_timeline_ready_timeout"

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise OSError(TEST_SECRET)

    monkeypatch.setattr(probe.os, "replace", fail_replace)
    with pytest.raises(probe.TimelineProbeError) as checkpoint_failure:
        probe._persist_checkpoint(tmp_path, coordinator)
    with pytest.raises(probe.TimelineProbeError) as summary_failure:
        probe._persist_terminal_summary(tmp_path, tracker, coordinator)

    assert TEST_SECRET not in str(checkpoint_failure.value)
    assert TEST_SECRET not in repr(checkpoint_failure.value)
    assert TEST_SECRET not in str(summary_failure.value)
    assert TEST_SECRET not in repr(summary_failure.value)
    assert TEST_SECRET not in "".join(
        traceback.format_exception(checkpoint_failure.value)
    )
    assert TEST_SECRET not in "".join(
        traceback.format_exception(summary_failure.value)
    )
    assert not list(tmp_path.glob("*.part"))


def test_control_and_checkpoint_documents_do_not_leak_sensitive_text() -> None:
    clock = FakeClock()
    coordinator = _coordinator(clock)
    coordinator.register_owner(_registration())
    visible = json.dumps(
        {
            "control": probe._control_document(_control("T1", 1, "T0")),
            "checkpoint": probe.asdict(coordinator.checkpoint()),
        },
        sort_keys=True,
    )

    assert TEST_SECRET not in visible
    assert EXPECTED not in visible
    assert "value_text_recorded" in visible


def test_terminal_observer_rejects_late_control_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (
        tmp_path
        / "build"
        / "autostart-run-timeline-probes"
        / "session-01"
    )
    root.mkdir(parents=True)
    clock = FakeClock()
    coordinator = _coordinator(clock)
    coordinator.fail("autostart_timeline_ready_timeout")
    probe._write_json_atomically(
        root / "ready.json",
        {
            "schema_version": probe.SCHEMA_VERSION,
            "observer_ready": True,
            "lifecycle_state": probe.ProbeLifecycleState.READY_UNARMED,
            "session_nonce": NONCE,
            "safe_code": "autostart_timeline_observer_ready",
            "value_text_recorded": False,
        },
    )
    probe._persist_checkpoint(root, coordinator)
    probe._write_json_atomically(
        root / "control.json",
        probe._control_document(
            probe.ControlMessage(
                schema_version=probe.SCHEMA_VERSION,
                session_nonce=NONCE,
                revision=0,
                expected_previous_phase=None,
                phase="T0",
                stop=False,
                abort=False,
            )
        ),
    )
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)

    with pytest.raises(probe.TimelineProbeError):
        probe._set_phase(
            "T1",
            evidence_root=str(root),
            expected_previous_phase="T0",
            revision=1,
            session_nonce=NONCE,
            stop=False,
        )

    assert probe._read_control(root / "control.json").revision == 0


def test_evidence_root_requires_unique_direct_child_of_allowed_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "build").mkdir()
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)
    valid = (
        tmp_path
        / "build"
        / "autostart-run-timeline-probes"
        / "session-01"
    )

    assert probe._validated_evidence_root(
        str(valid),
        must_exist=False,
    ) == valid
    valid.parent.mkdir()
    valid.mkdir()
    with pytest.raises(probe.TimelineProbeError):
        probe._validated_evidence_root(str(valid), must_exist=False)
    assert probe._validated_evidence_root(
        str(valid),
        must_exist=True,
    ) == valid


def test_owner_ui_checkpoint_requires_all_qt_readiness_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)
    _write_owner_ui_checkpoint(tmp_path)

    assert probe._owner_ui_checkpoint_ready(NONCE)

    checkpoint = (
        tmp_path
        / "build"
        / "autostart-owner-ui-readiness"
        / NONCE
        / "checkpoint.json"
    )
    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    document["events"] = [
        event
        for event in document["events"]
        if event["stage"] != "tray_visible"
    ]
    for sequence, event in enumerate(document["events"], start=1):
        event["sequence"] = sequence
    probe._write_json_atomically(checkpoint, document)

    assert not probe._owner_ui_checkpoint_ready(NONCE)


def test_owner_ui_checkpoint_rejects_stale_nonce_part_and_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)
    root = _write_owner_ui_checkpoint(tmp_path)
    checkpoint = root / "checkpoint.json"
    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    document["events"][1]["sequence"] = 1
    probe._write_json_atomically(checkpoint, document)

    assert not probe._owner_ui_checkpoint_ready(NONCE)
    assert not probe._owner_ui_checkpoint_ready(OTHER_NONCE)

    document["events"][1]["sequence"] = 2
    probe._write_json_atomically(checkpoint, document)
    (root / "checkpoint.json.part").write_bytes(b"partial")
    assert not probe._owner_ui_checkpoint_ready(NONCE)


def test_t1_requires_product_readiness_and_absent_fixed_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)
    root = _write_control_root(tmp_path)
    _write_owner_ui_checkpoint(tmp_path)
    monkeypatch.setattr(
        probe,
        "query_fixed_run_value",
        lambda expected: probe.SafeValueObservation.absent(),
    )

    assert (
        probe._set_phase(
            "T1",
            evidence_root=str(root),
            expected_previous_phase="T0",
            revision=1,
            session_nonce=NONCE,
            stop=False,
        )
        == 0
    )
    assert probe._read_control(root / "control.json").phase == "T1"


def test_t1_rejects_ui_probe_false_positive_and_registry_presence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)
    root = _write_control_root(tmp_path)
    monkeypatch.setattr(
        probe,
        "query_fixed_run_value",
        lambda expected: probe.SafeValueObservation.absent(),
    )

    with pytest.raises(
        probe.TimelineCoordinationError,
        match="readiness checkpoint",
    ):
        probe._set_phase(
            "T1",
            evidence_root=str(root),
            expected_previous_phase="T0",
            revision=1,
            session_nonce=NONCE,
            stop=False,
        )
    assert probe._read_control(root / "control.json").revision == 0

    _write_owner_ui_checkpoint(tmp_path)
    monkeypatch.setattr(
        probe,
        "query_fixed_run_value",
        lambda expected: _occupied(),
    )
    with pytest.raises(
        probe.TimelineCoordinationError,
        match="not absent",
    ):
        probe._set_phase(
            "T1",
            evidence_root=str(root),
            expected_previous_phase="T0",
            revision=1,
            session_nonce=NONCE,
            stop=False,
        )
    assert probe._read_control(root / "control.json").revision == 0


@pytest.mark.parametrize(
    "invalid_path",
    [
        r"\\server\share\session",
        "relative-session",
        "D:\\SJTUClaw\\build\\autostart-run-timeline-probes\\..\\escape",
        "D:\\SJTUClaw\\build\\autostart-run-timeline-probe",
        "D:\\SJTUClaw\\build\\autostart-run-timeline-probes\\bad.name",
        "D:\\SJTUClaw\\build\\autostart-run-timeline-probes\\"
        + ("x" * 200),
    ],
)
def test_evidence_root_rejects_escape_unc_legacy_and_long_paths(
    invalid_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "build").mkdir()
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)

    with pytest.raises(probe.TimelineProbeError):
        probe._validated_evidence_root(invalid_path, must_exist=False)


def test_evidence_root_rejects_reparse_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = tmp_path / "build"
    parent = build / "autostart-run-timeline-probes"
    build.mkdir()
    parent.mkdir()
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)
    monkeypatch.setattr(
        probe,
        "_is_reparse_point",
        lambda path: path == parent,
    )

    with pytest.raises(probe.TimelineProbeError):
        probe._validated_evidence_root(
            str(parent / "session-01"),
            must_exist=False,
        )


def test_archive_rejects_existing_target_and_preserves_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "record.json").write_text("{}", encoding="utf-8")
    archive = tmp_path / "archive"
    target = archive / "attempt-01"
    target.mkdir(parents=True)

    with pytest.raises(probe.TimelineProbeError):
        probe._archive_evidence_directory(
            source,
            archive,
            "attempt-01",
            "txn-01",
        )

    assert source.is_dir()
    assert (source / "record.json").is_file()


def test_archive_success_preserves_manifest_without_part_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "record.json").write_text("{}", encoding="utf-8")
    before = probe._evidence_tree_manifest(source)

    target, archived = probe._archive_evidence_directory(
        source,
        tmp_path / "archive",
        "attempt-01",
        "txn-01",
    )

    assert archived == before
    assert probe._evidence_tree_manifest(target) == before
    assert not source.exists()
    assert not list(tmp_path.rglob("*.part"))


def test_archive_rolls_back_after_partial_move(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "record.json").write_text("{}", encoding="utf-8")
    archive = tmp_path / "archive"
    calls = 0

    def fail_commit_then_allow_rollback(
        current: Path,
        destination: Path,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(TEST_SECRET)
        probe.os.replace(current, destination)

    with pytest.raises(probe.TimelineProbeError) as captured:
        probe._archive_evidence_directory(
            source,
            archive,
            "attempt-01",
            "txn-01",
            mover=fail_commit_then_allow_rollback,
        )

    assert calls == 3
    assert source.is_dir()
    assert (source / "record.json").is_file()
    assert not (archive / "attempt-01").exists()
    assert not (tmp_path / "txn-01").exists()
    assert TEST_SECRET not in str(captured.value)
    assert TEST_SECRET not in repr(captured.value)


def test_fake_clock_full_observer_flow_waits_then_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "build").mkdir()
    root = (
        tmp_path
        / "build"
        / "autostart-run-timeline-probes"
        / "session-01"
    )
    clock = FakeClock()
    identity_running = True
    next_phase_index = 1

    monkeypatch.setattr(
        probe,
        "_authoritative_executable",
        lambda expected_sha256: (tmp_path / "SJTUClaw.exe", EXPECTED),
    )
    monkeypatch.setattr(probe, "_repository_root", lambda: tmp_path)

    def reader(expected_command: str) -> probe.SafeValueObservation:
        assert expected_command == EXPECTED
        if not (root / "control.json").exists():
            return probe.SafeValueObservation.absent()
        control = probe._read_control(root / "control.json")
        if (
            probe.PHASE_INDEX[control.phase]
            >= probe.PHASE_INDEX["T3-after-enable"]
        ):
            return _owned()
        return probe.SafeValueObservation.absent()

    def identity_probe(process_id: int) -> str | None:
        assert process_id == 1234
        return OWNER_IDENTITY if identity_running else None

    def sleeper(seconds: float) -> None:
        nonlocal identity_running, next_phase_index
        assert seconds == probe.POLL_INTERVAL_SECONDS
        if next_phase_index == 1:
            clock.advance(15 * 60 + 1)
            ready = json.loads(
                (root / "ready.json").read_text(encoding="utf-8")
            )
            nonce = ready["session_nonce"]
            probe._write_json_atomically(
                root / "owner-pid.json",
                probe.asdict(_registration(nonce=nonce)),
            )
        else:
            clock.advance(1)
            nonce = NONCE
        previous = probe.PHASES[next_phase_index - 1]
        phase = probe.PHASES[next_phase_index]
        if phase == "T8-after-process-exit":
            identity_running = False
        probe._write_json_atomically(
            root / "control.json",
            probe._control_document(
                _control(
                    phase,
                    next_phase_index,
                    previous,
                    nonce=nonce,
                    stop=phase == "T9-final",
                )
            ),
        )
        next_phase_index += 1

    result = probe._run_real_observer(
        "0" * 64,
        str(root),
        NONCE,
        reader=reader,
        identity_probe=identity_probe,
        monotonic=clock.monotonic,
        sleeper=sleeper,
    )

    summary = json.loads(
        (root / "terminal-summary.json").read_text(encoding="utf-8")
    )
    assert result == 0
    assert summary["safe_code"] == "autostart_run_value_timeline_verified"
    assert summary["observer_terminal_state"] == "completed"
    assert summary["owner_terminal_state"] == "exited"
    assert not list(root.rglob("*.part"))
