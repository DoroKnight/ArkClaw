from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "packaging/windows_process_exit_observer.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_windows_process_exit_observer_test",
        _MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


observer_module: Any = _load_module()

CREATION_FILETIME = 0x0123456789ABCDEF
OTHER_CREATION_FILETIME = 0xFEDCBA9876543210
HANDLE = 91
PID = 4321


class FakeWindowsProcessHandleApi:
    def __init__(
        self,
        *,
        handle: int | None = HANDLE,
        open_error: int = 0,
        times: list[Any] | None = None,
        exit_codes: list[int | None] | None = None,
        wait_results: list[int] | None = None,
    ) -> None:
        self.handle = handle
        self.open_error = open_error
        self.times = list(
            times
            or [observer_module.ProcessTimes(CREATION_FILETIME, 0)]
        )
        self.exit_codes = list(
            exit_codes or [observer_module.STILL_ACTIVE]
        )
        self.wait_results = list(
            wait_results or [observer_module.WAIT_TIMEOUT]
        )
        self.events: list[str] = []
        self.close_count = 0

    def open_process(self, process_id: int) -> tuple[int | None, int]:
        assert process_id == PID
        self.events.append("open")
        return self.handle, self.open_error

    def get_process_times(self, handle: int) -> Any:
        assert handle == self.handle
        self.events.append("times")
        return self.times.pop(0)

    def get_exit_code(self, handle: int) -> int | None:
        assert handle == self.handle
        self.events.append("exit_code")
        return cast("int | None", self.exit_codes.pop(0))

    def wait_for_single_object(self, handle: int, timeout_ms: int) -> int:
        assert handle == self.handle
        assert timeout_ms >= 0
        self.events.append("wait")
        return cast("int", self.wait_results.pop(0))

    def close_handle(self, handle: int) -> None:
        assert handle == self.handle
        self.events.append("close")
        self.close_count += 1


def _acquire(api: FakeWindowsProcessHandleApi) -> Any:
    return observer_module.retain_process_exit_handle(
        PID,
        CREATION_FILETIME,
        api=api,
    )


def _running_api(
    *,
    terminal_times: Any | None = None,
    terminal_exit_code: int | None = 0,
    wait_result: int | None = None,
) -> FakeWindowsProcessHandleApi:
    return FakeWindowsProcessHandleApi(
        times=[
            observer_module.ProcessTimes(CREATION_FILETIME, 0),
            terminal_times
            or observer_module.ProcessTimes(CREATION_FILETIME, 1),
        ],
        exit_codes=[observer_module.STILL_ACTIVE, terminal_exit_code],
        wait_results=[
            observer_module.WAIT_OBJECT_0
            if wait_result is None
            else wait_result
        ],
    )


def test_running_process_has_zero_exit_filetime_and_retained_handle() -> None:
    api = FakeWindowsProcessHandleApi()

    acquisition = _acquire(api)

    assert acquisition.result.state is observer_module.ProcessExitState.RUNNING
    assert acquisition.observer is not None
    assert not acquisition.observer.closed
    assert api.close_count == 0
    acquisition.observer.close()
    assert api.close_count == 1


@pytest.mark.parametrize("exit_code", [0, 37])
def test_signaled_process_returns_exact_exit_code(exit_code: int) -> None:
    api = _running_api(terminal_exit_code=exit_code)
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is observer_module.ProcessExitState.EXITED_WITH_CODE
    assert result.exit_code_observed
    assert result.exit_code == exit_code
    assert result.exit_filetime_recorded
    assert api.events == [
        "open",
        "times",
        "exit_code",
        "wait",
        "times",
        "exit_code",
        "close",
    ]
    assert api.close_count == 1


def test_retained_handle_does_not_reopen_after_pid_disappears() -> None:
    api = _running_api()
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.exit_code == 0
    assert api.events.count("open") == 1


def test_creation_filetime_mismatch_during_acquisition_is_pid_reuse() -> None:
    api = FakeWindowsProcessHandleApi(
        times=[observer_module.ProcessTimes(OTHER_CREATION_FILETIME, 0)]
    )

    acquisition = _acquire(api)

    assert acquisition.observer is None
    assert acquisition.result.state is observer_module.ProcessExitState.PID_REUSED
    assert api.close_count == 1


def test_creation_filetime_mismatch_after_signal_is_pid_reuse() -> None:
    api = _running_api(
        terminal_times=observer_module.ProcessTimes(
            OTHER_CREATION_FILETIME,
            1,
        )
    )
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is observer_module.ProcessExitState.PID_REUSED
    assert not result.creation_filetime_matches
    assert result.exit_code is None
    assert api.close_count == 1


def test_wait_timeout_keeps_handle_for_later_exit() -> None:
    api = FakeWindowsProcessHandleApi(
        times=[
            observer_module.ProcessTimes(CREATION_FILETIME, 0),
            observer_module.ProcessTimes(CREATION_FILETIME, 1),
        ],
        exit_codes=[observer_module.STILL_ACTIVE, 0],
        wait_results=[
            observer_module.WAIT_TIMEOUT,
            observer_module.WAIT_OBJECT_0,
        ],
    )
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    running = acquisition.observer.wait_for_exit(1)
    exited = acquisition.observer.wait_for_exit(5000)

    assert running.state is observer_module.ProcessExitState.RUNNING
    assert not running.wait_signaled
    assert exited.exit_code == 0
    assert api.close_count == 1


@pytest.mark.parametrize(
    "wait_result",
    [observer_module.WAIT_FAILED, 12345],
)
def test_wait_failure_is_safe_and_closes_once(wait_result: int) -> None:
    api = FakeWindowsProcessHandleApi(wait_results=[wait_result])
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is observer_module.ProcessExitState.WAIT_FAILED
    assert not result.exit_code_observed
    assert api.close_count == 1


def test_process_times_failure_during_acquisition_closes_once() -> None:
    api = FakeWindowsProcessHandleApi(times=[None])

    acquisition = _acquire(api)

    assert acquisition.result.state is (
        observer_module.ProcessExitState.PROCESS_TIMES_FAILED
    )
    assert acquisition.observer is None
    assert api.close_count == 1


def test_process_times_failure_after_signal_closes_once() -> None:
    api = _running_api(terminal_times=None)
    api.times[1] = None
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is observer_module.ProcessExitState.PROCESS_TIMES_FAILED
    assert api.close_count == 1


def test_exit_code_failure_during_acquisition_closes_once() -> None:
    api = FakeWindowsProcessHandleApi(exit_codes=[None])

    acquisition = _acquire(api)

    assert acquisition.result.state is (
        observer_module.ProcessExitState.EXIT_CODE_QUERY_FAILED
    )
    assert not acquisition.result.exit_code_observed
    assert api.close_count == 1


def test_exit_code_failure_after_exit_is_not_guessed() -> None:
    api = _running_api(terminal_exit_code=None)
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is (
        observer_module.ProcessExitState.EXIT_CODE_QUERY_FAILED
    )
    assert result.exit_filetime_recorded
    assert not result.exit_code_observed
    assert result.exit_code is None
    assert api.close_count == 1


def test_still_active_after_signaled_exit_is_not_a_terminal_code() -> None:
    api = _running_api(terminal_exit_code=observer_module.STILL_ACTIVE)
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is (
        observer_module.ProcessExitState.EXITED_CODE_UNAVAILABLE
    )
    assert not result.exit_code_observed
    assert result.exit_code is None
    assert api.close_count == 1


def test_signaled_handle_without_exit_filetime_is_not_guessed() -> None:
    api = _running_api(
        terminal_times=observer_module.ProcessTimes(CREATION_FILETIME, 0),
        terminal_exit_code=0,
    )
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.state is (
        observer_module.ProcessExitState.EXITED_CODE_UNAVAILABLE
    )
    assert not result.exit_filetime_recorded
    assert result.exit_code is None


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (5, "ACCESS_DENIED"),
        (87, "PROCESS_NOT_FOUND"),
        (1168, "PROCESS_NOT_FOUND"),
        (1234, "OPEN_FAILED"),
    ],
)
def test_open_failures_are_fixed_safe_states(
    error: int,
    expected_state: str,
) -> None:
    api = FakeWindowsProcessHandleApi(handle=None, open_error=error)

    acquisition = _acquire(api)

    assert acquisition.observer is None
    assert acquisition.result.state is getattr(
        observer_module.ProcessExitState,
        expected_state,
    )
    assert api.close_count == 0


def test_close_is_idempotent_on_manual_cleanup() -> None:
    api = FakeWindowsProcessHandleApi()
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    acquisition.observer.close()
    acquisition.observer.close()

    assert api.close_count == 1


def test_context_manager_closes_once_on_failure() -> None:
    api = FakeWindowsProcessHandleApi()
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    with pytest.raises(
        RuntimeError,
        match="fixed failure",
    ), acquisition.observer:
        raise RuntimeError("fixed failure")

    assert api.close_count == 1


def test_supervisor_holds_handle_before_user_exit() -> None:
    api = _running_api()
    acquisition = _acquire(api)

    assert acquisition.observer is not None
    assert api.events == ["open", "times", "exit_code"]
    assert api.close_count == 0

    result = acquisition.observer.wait_for_exit(5000)
    assert result.exit_code_observed


def test_checkpoint_identity_and_exit_code_share_one_handle() -> None:
    api = _running_api(terminal_exit_code=0)
    acquisition = _acquire(api)
    assert acquisition.observer is not None

    result = acquisition.observer.wait_for_exit(5000)

    assert result.creation_filetime_matches
    assert result.exit_filetime_recorded
    assert result.exit_code_observed
    assert result.exit_code == 0
    assert api.events.count("open") == 1
    assert api.events.count("close") == 1


def test_invalid_pid_does_not_open_or_invent_exit_code() -> None:
    api = FakeWindowsProcessHandleApi()

    acquisition = observer_module.retain_process_exit_handle(
        0,
        CREATION_FILETIME,
        api=api,
    )

    assert acquisition.result.state is (
        observer_module.ProcessExitState.PROCESS_NOT_FOUND
    )
    assert acquisition.result.exit_code is None
    assert api.events == []
