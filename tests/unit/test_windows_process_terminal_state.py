from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROBE_PATH = _PROJECT_ROOT / "packaging/autostart_run_timeline_probe.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_autostart_windows_process_state_test",
        _PROBE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe: Any = _load_module()

CREATION_FILETIME = 0x0123456789ABCDEF
CREATION_IDENTITY = f"{CREATION_FILETIME:016x}"
OTHER_CREATION_FILETIME = 0xFEDCBA9876543210
STILL_ACTIVE = 259


class FakeWindowsProcessApi:
    def __init__(
        self,
        *,
        handle: int | None = 77,
        open_error: int = 0,
        creation_filetime: int = CREATION_FILETIME,
        exit_filetime: int = 0,
        exit_code: int | None = STILL_ACTIVE,
        times_fail: bool = False,
        times_error: BaseException | None = None,
        exit_code_error: BaseException | None = None,
    ) -> None:
        self.handle = handle
        self.open_error = open_error
        self.creation_filetime = creation_filetime
        self.exit_filetime = exit_filetime
        self.exit_code = exit_code
        self.times_fail = times_fail
        self.times_error = times_error
        self.exit_code_error = exit_code_error
        self.open_count = 0
        self.times_count = 0
        self.exit_code_count = 0
        self.closed_handles: list[int] = []

    def open_process(self, process_id: int) -> tuple[int | None, int]:
        assert process_id == 4321
        self.open_count += 1
        return self.handle, self.open_error

    def get_process_times(self, handle: int) -> Any:
        assert handle == self.handle
        self.times_count += 1
        if self.times_error is not None:
            raise self.times_error
        if self.times_fail:
            return None
        return probe.WindowsProcessTimes(
            creation_filetime=self.creation_filetime,
            exit_filetime=self.exit_filetime,
        )

    def get_exit_code(self, handle: int) -> int | None:
        assert handle == self.handle
        self.exit_code_count += 1
        if self.exit_code_error is not None:
            raise self.exit_code_error
        return self.exit_code

    def close_handle(self, handle: int) -> None:
        assert handle == self.handle
        self.closed_handles.append(handle)


def _query(api: FakeWindowsProcessApi) -> Any:
    return probe._query_windows_process_state(
        4321,
        CREATION_IDENTITY,
        api=api,
    )


def _terminal_conditions() -> Any:
    return probe.OwnerTerminalConditions(
        supervisor_completed=True,
        supervisor_identity_matched=True,
        owner_exit_code=0,
        owner_checkpoint_closed=True,
        pid_tcp_endpoint_count=0,
        forced_termination=False,
        toggle_command_count=1,
        tray_menu_activation_count=0,
        pet_menu_activation_count=0,
        secondary_creation_count=0,
    )


def test_matching_live_process_is_running() -> None:
    api = FakeWindowsProcessApi()

    status = _query(api)

    assert status.state is probe.WindowsProcessState.RUNNING
    assert status.creation_matches
    assert not status.exit_filetime_recorded
    assert status.exit_code == STILL_ACTIVE
    assert api.closed_handles == [77]


def test_matching_nonzero_exit_filetime_is_exited() -> None:
    status = _query(FakeWindowsProcessApi(exit_filetime=1, exit_code=0))

    assert status.state is probe.WindowsProcessState.EXITED
    assert status.exit_filetime_recorded
    assert status.terminal_source is probe.ProcessTerminalSource.EXIT_FILETIME
    assert status.consistency is probe.ProcessQueryConsistency.CONSISTENT


def test_exit_filetime_is_authoritative_over_still_active() -> None:
    status = _query(
        FakeWindowsProcessApi(exit_filetime=1, exit_code=STILL_ACTIVE)
    )

    assert status.state is probe.WindowsProcessState.EXITED
    assert status.consistency is (
        probe.ProcessQueryConsistency.EXIT_FILETIME_WITH_STILL_ACTIVE
    )


def test_terminal_exit_code_is_fallback_when_exit_filetime_is_zero() -> None:
    status = _query(FakeWindowsProcessApi(exit_filetime=0, exit_code=0))

    assert status.state is probe.WindowsProcessState.EXITED
    assert not status.exit_filetime_recorded
    assert status.terminal_source is (
        probe.ProcessTerminalSource.EXIT_CODE_TERMINAL_FALLBACK
    )
    assert status.consistency is (
        probe.ProcessQueryConsistency.EXIT_CODE_WITHOUT_EXIT_FILETIME
    )


def test_creation_filetime_mismatch_is_pid_reuse() -> None:
    api = FakeWindowsProcessApi(creation_filetime=OTHER_CREATION_FILETIME)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.PID_REUSED
    assert not status.creation_matches
    assert api.exit_code_count == 0
    assert api.closed_handles == [77]


@pytest.mark.parametrize("error_code", [87, 1168])
def test_missing_pid_is_not_found(error_code: int) -> None:
    api = FakeWindowsProcessApi(handle=None, open_error=error_code)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.NOT_FOUND
    assert api.closed_handles == []


def test_access_denied_is_inaccessible_not_exited() -> None:
    api = FakeWindowsProcessApi(handle=None, open_error=5)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.INACCESSIBLE
    assert api.closed_handles == []


def test_unknown_open_failure_is_query_failed() -> None:
    status = _query(FakeWindowsProcessApi(handle=None, open_error=1234))

    assert status.state is probe.WindowsProcessState.QUERY_FAILED


def test_get_process_times_failure_is_query_failed_and_closes_once() -> None:
    api = FakeWindowsProcessApi(times_fail=True)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.QUERY_FAILED
    assert api.closed_handles == [77]


def test_exit_between_open_and_process_times_is_terminal() -> None:
    api = FakeWindowsProcessApi(exit_filetime=9, exit_code=0)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.EXITED
    assert status.creation_matches
    assert api.closed_handles == [77]


def test_exit_between_times_and_exit_code_uses_terminal_fallback() -> None:
    api = FakeWindowsProcessApi(exit_filetime=0, exit_code=0)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.EXITED
    assert status.terminal_source is (
        probe.ProcessTerminalSource.EXIT_CODE_TERMINAL_FALLBACK
    )
    assert api.closed_handles == [77]


def test_retained_exited_process_object_can_satisfy_t9() -> None:
    api = FakeWindowsProcessApi(exit_filetime=4, exit_code=0)
    status = _query(api)
    coordinator = probe.ProbeCoordinator("a" * 32, 0.0)
    coordinator.mark_ready(0.0)
    coordinator.register_owner(
        probe.OwnerRegistration(2, "a" * 32, 4321, CREATION_IDENTITY)
    )
    coordinator.current_phase = "T8-after-process-exit"
    coordinator.revision = 8

    coordinator.accept_control(
        probe.ControlMessage(
            2,
            "a" * 32,
            9,
            "T8-after-process-exit",
            "T9-final",
            True,
            False,
            _terminal_conditions(),
        ),
        1.0,
        current_process_status=status,
    )

    assert coordinator.current_phase == "T9-final"
    assert coordinator.lifecycle_state is probe.ProbeLifecycleState.FINALIZING


def test_pid_reuse_cannot_satisfy_t9() -> None:
    status = _query(
        FakeWindowsProcessApi(creation_filetime=OTHER_CREATION_FILETIME)
    )
    coordinator = probe.ProbeCoordinator("b" * 32, 0.0)
    coordinator.mark_ready(0.0)
    coordinator.register_owner(
        probe.OwnerRegistration(2, "b" * 32, 4321, CREATION_IDENTITY)
    )
    coordinator.current_phase = "T8-after-process-exit"
    coordinator.revision = 8

    with pytest.raises(probe.TimelineCoordinationError) as captured:
        coordinator.accept_control(
            probe.ControlMessage(
                2,
                "b" * 32,
                9,
                "T8-after-process-exit",
                "T9-final",
                True,
                False,
                _terminal_conditions(),
            ),
            1.0,
            current_process_status=status,
        )

    assert captured.value.safe_code == (
        "autostart_timeline_owner_terminal_unverified"
    )


def test_not_found_pid_requires_matching_supervisor_terminal_for_t9() -> None:
    status = _query(FakeWindowsProcessApi(handle=None, open_error=87))
    coordinator = probe.ProbeCoordinator("c" * 32, 0.0)
    coordinator.mark_ready(0.0)
    coordinator.register_owner(
        probe.OwnerRegistration(2, "c" * 32, 4321, CREATION_IDENTITY)
    )
    coordinator.current_phase = "T8-after-process-exit"
    coordinator.revision = 8
    message = probe.ControlMessage(
        2,
        "c" * 32,
        9,
        "T8-after-process-exit",
        "T9-final",
        True,
        False,
        _terminal_conditions(),
    )

    coordinator.accept_control(
        message,
        1.0,
        current_process_status=status,
    )
    assert coordinator.owner_terminal_state is probe.OwnerTerminalState.EXITED
    assert coordinator.owner_terminal_fallback_verified


def test_old_t0_through_t8_shape_can_complete_with_exit_filetime() -> None:
    tracker = probe.TimelineTracker()
    absent = probe.SafeValueObservation.absent()
    owned = probe.SafeValueObservation.from_stored_value(
        "owned",
        probe.REGISTRY_STRING_VALUE_TYPE,
        "owned",
    )
    tracker.observe("T0", False, absent)
    for phase in probe.PHASES[1:8]:
        tracker.observe(phase, True, absent if phase in {"T1", "T2-before-enable"} else owned)
    tracker.observe("T8-after-process-exit", False, owned)
    tracker.observe("T9-final", False, owned)

    summary = tracker.summarize()

    assert summary.safe_code == "autostart_run_value_timeline_verified"
    assert summary.process_exit_sequence is not None


@pytest.mark.parametrize(
    "failure",
    [
        KeyboardInterrupt(),
        RuntimeError("fixed test failure"),
    ],
)
def test_handle_closes_once_when_query_is_interrupted_or_fails(
    failure: BaseException,
) -> None:
    api = FakeWindowsProcessApi(times_error=failure)

    with pytest.raises(type(failure)):
        _query(api)

    assert api.closed_handles == [77]


def test_exit_code_query_failure_is_not_guessed_and_closes_once() -> None:
    api = FakeWindowsProcessApi(exit_code=None)

    status = _query(api)

    assert status.state is probe.WindowsProcessState.QUERY_FAILED
    assert api.closed_handles == [77]
