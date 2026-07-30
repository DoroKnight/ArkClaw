from __future__ import annotations

import importlib.util
import json
import sys
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


def _complete_owned_timeline() -> probe.TimelineTracker:
    tracker = probe.TimelineTracker()
    tracker.observe("T0", False, probe.SafeValueObservation.absent())
    tracker.observe("T1", True, probe.SafeValueObservation.absent())
    tracker.observe("T2", True, probe.SafeValueObservation.absent())
    for phase in ("T3", "T4", "T5", "T6", "T7-before-shutdown"):
        tracker.observe(phase, True, _owned())
    tracker.observe("T8", False, _owned())
    tracker.observe("T9", False, _owned())
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
        ("T2", True),
        ("T3", True),
        ("T8", False),
        ("T9", False),
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
        ("T3", True, "autostart_value_removed_during_runtime"),
        ("T5", True, "autostart_value_removed_during_runtime"),
        ("T8", False, "autostart_value_removed_after_process_exit"),
        ("T9", False, "autostart_value_removed_after_process_exit"),
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
    tracker.observe("T2", True, _owned())
    tracker.observe(absent_phase, running, probe.SafeValueObservation.absent())

    summary = tracker.summarize()

    assert summary.safe_code == expected_code
    assert summary.first_absent_after_owned_sequence is not None


def test_external_replacement_and_wrong_type_are_ownership_loss() -> None:
    for observation in (_occupied(), _occupied(EXPECTED, 7)):
        tracker = probe.TimelineTracker()
        tracker.observe("T0", False, probe.SafeValueObservation.absent())
        tracker.observe("T2", True, _owned())
        tracker.observe("T3", True, observation)

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
    tracker.observe("T2", True, _occupied())

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
                "phase": "T0",
                "stop": "false",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(probe.TimelineProbeError):
        probe._read_control(control)
