from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

STILL_ACTIVE = 259
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF


class ProcessExitState(StrEnum):
    """Fixed process states that never contain Win32 error text."""

    RUNNING = "running"
    EXITED_WITH_CODE = "exited_with_code"
    EXITED_CODE_UNAVAILABLE = "exited_code_unavailable"
    PID_REUSED = "pid_reused"
    PROCESS_NOT_FOUND = "process_not_found"
    ACCESS_DENIED = "access_denied"
    OPEN_FAILED = "open_failed"
    WAIT_FAILED = "wait_failed"
    PROCESS_TIMES_FAILED = "process_times_failed"
    EXIT_CODE_QUERY_FAILED = "exit_code_query_failed"


@dataclass(frozen=True, slots=True)
class ProcessTimes:
    creation_filetime: int
    exit_filetime: int


@dataclass(frozen=True, slots=True)
class ProcessExitResult:
    state: ProcessExitState
    creation_filetime_matches: bool
    exit_filetime_recorded: bool
    exit_code_observed: bool
    exit_code: int | None
    wait_signaled: bool

    @classmethod
    def unavailable(
        cls,
        state: ProcessExitState,
        *,
        creation_filetime_matches: bool = False,
        exit_filetime_recorded: bool = False,
        wait_signaled: bool = False,
    ) -> ProcessExitResult:
        return cls(
            state=state,
            creation_filetime_matches=creation_filetime_matches,
            exit_filetime_recorded=exit_filetime_recorded,
            exit_code_observed=False,
            exit_code=None,
            wait_signaled=wait_signaled,
        )


class WindowsProcessHandleApi(Protocol):
    def open_process(self, process_id: int) -> tuple[int | None, int]: ...

    def get_process_times(self, handle: int) -> ProcessTimes | None: ...

    def get_exit_code(self, handle: int) -> int | None: ...

    def wait_for_single_object(self, handle: int, timeout_ms: int) -> int: ...

    def close_handle(self, handle: int) -> None: ...


class CtypesWindowsProcessHandleApi:
    """Minimal Win32 adapter retaining SYNCHRONIZE and query rights."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        self._ctypes = ctypes
        self._file_time_type = FileTime
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._open_process = self._kernel32.OpenProcess
        self._open_process.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._open_process.restype = wintypes.HANDLE

        self._get_process_times = self._kernel32.GetProcessTimes
        self._get_process_times.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
        ]
        self._get_process_times.restype = wintypes.BOOL

        self._get_exit_code_process = self._kernel32.GetExitCodeProcess
        self._get_exit_code_process.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._get_exit_code_process.restype = wintypes.BOOL

        self._wait_for_single_object = self._kernel32.WaitForSingleObject
        self._wait_for_single_object.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self._wait_for_single_object.restype = wintypes.DWORD

        self._close_handle = self._kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL

    def open_process(self, process_id: int) -> tuple[int | None, int]:
        synchronize = 0x00100000
        process_query_limited_information = 0x1000
        handle = self._open_process(
            synchronize | process_query_limited_information,
            False,
            process_id,
        )
        if not handle:
            return None, int(self._ctypes.get_last_error())
        return int(handle), 0

    def get_process_times(self, handle: int) -> ProcessTimes | None:
        created = self._file_time_type()
        exited = self._file_time_type()
        kernel = self._file_time_type()
        user = self._file_time_type()
        if not self._get_process_times(
            handle,
            self._ctypes.byref(created),
            self._ctypes.byref(exited),
            self._ctypes.byref(kernel),
            self._ctypes.byref(user),
        ):
            return None
        return ProcessTimes(
            creation_filetime=(int(created.high) << 32) | int(created.low),
            exit_filetime=(int(exited.high) << 32) | int(exited.low),
        )

    def get_exit_code(self, handle: int) -> int | None:
        from ctypes import wintypes

        exit_code = wintypes.DWORD()
        if not self._get_exit_code_process(handle, self._ctypes.byref(exit_code)):
            return None
        return int(exit_code.value)

    def wait_for_single_object(self, handle: int, timeout_ms: int) -> int:
        return int(self._wait_for_single_object(handle, timeout_ms))

    def close_handle(self, handle: int) -> None:
        self._close_handle(handle)


class RetainedProcessExitObserver:
    """Own one immutable process handle until exit evidence is collected."""

    def __init__(
        self,
        api: WindowsProcessHandleApi,
        handle: int,
        creation_filetime: int,
    ) -> None:
        self._api = api
        self._handle: int | None = handle
        self._creation_filetime = creation_filetime

    @property
    def closed(self) -> bool:
        return self._handle is None

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        self._api.close_handle(handle)

    def wait_for_exit(self, timeout_ms: int) -> ProcessExitResult:
        if self._handle is None or timeout_ms < 0:
            return ProcessExitResult.unavailable(ProcessExitState.WAIT_FAILED)
        handle = self._handle
        wait_result = self._api.wait_for_single_object(handle, timeout_ms)
        if wait_result == WAIT_TIMEOUT:
            return ProcessExitResult(
                state=ProcessExitState.RUNNING,
                creation_filetime_matches=True,
                exit_filetime_recorded=False,
                exit_code_observed=False,
                exit_code=None,
                wait_signaled=False,
            )
        if wait_result != WAIT_OBJECT_0:
            self.close()
            return ProcessExitResult.unavailable(ProcessExitState.WAIT_FAILED)

        times = self._api.get_process_times(handle)
        if times is None:
            self.close()
            return ProcessExitResult.unavailable(
                ProcessExitState.PROCESS_TIMES_FAILED,
                wait_signaled=True,
            )
        if times.creation_filetime != self._creation_filetime:
            self.close()
            return ProcessExitResult.unavailable(
                ProcessExitState.PID_REUSED,
                exit_filetime_recorded=times.exit_filetime != 0,
                wait_signaled=True,
            )
        if times.exit_filetime == 0:
            self.close()
            return ProcessExitResult.unavailable(
                ProcessExitState.EXITED_CODE_UNAVAILABLE,
                creation_filetime_matches=True,
                wait_signaled=True,
            )

        exit_code = self._api.get_exit_code(handle)
        if exit_code is None:
            self.close()
            return ProcessExitResult.unavailable(
                ProcessExitState.EXIT_CODE_QUERY_FAILED,
                creation_filetime_matches=True,
                exit_filetime_recorded=True,
                wait_signaled=True,
            )
        if exit_code == STILL_ACTIVE:
            self.close()
            return ProcessExitResult.unavailable(
                ProcessExitState.EXITED_CODE_UNAVAILABLE,
                creation_filetime_matches=True,
                exit_filetime_recorded=True,
                wait_signaled=True,
            )

        self.close()
        return ProcessExitResult(
            state=ProcessExitState.EXITED_WITH_CODE,
            creation_filetime_matches=True,
            exit_filetime_recorded=True,
            exit_code_observed=True,
            exit_code=exit_code,
            wait_signaled=True,
        )

    def __enter__(self) -> RetainedProcessExitObserver:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class ProcessHandleAcquisition:
    observer: RetainedProcessExitObserver | None
    result: ProcessExitResult


def retain_process_exit_handle(
    process_id: int,
    expected_creation_filetime: int,
    *,
    api: WindowsProcessHandleApi | None = None,
) -> ProcessHandleAcquisition:
    """Retain a verified running process handle without reopening by PID."""

    if process_id <= 0 or expected_creation_filetime <= 0:
        return ProcessHandleAcquisition(
            None,
            ProcessExitResult.unavailable(ProcessExitState.PROCESS_NOT_FOUND),
        )
    selected_api = api or CtypesWindowsProcessHandleApi()
    handle, error = selected_api.open_process(process_id)
    if handle is None:
        if error in {87, 1168}:
            state = ProcessExitState.PROCESS_NOT_FOUND
        elif error == 5:
            state = ProcessExitState.ACCESS_DENIED
        else:
            state = ProcessExitState.OPEN_FAILED
        return ProcessHandleAcquisition(None, ProcessExitResult.unavailable(state))

    observer = RetainedProcessExitObserver(
        selected_api,
        handle,
        expected_creation_filetime,
    )
    times = selected_api.get_process_times(handle)
    if times is None:
        observer.close()
        return ProcessHandleAcquisition(
            None,
            ProcessExitResult.unavailable(
                ProcessExitState.PROCESS_TIMES_FAILED
            ),
        )
    if times.creation_filetime != expected_creation_filetime:
        observer.close()
        return ProcessHandleAcquisition(
            None,
            ProcessExitResult.unavailable(
                ProcessExitState.PID_REUSED,
                exit_filetime_recorded=times.exit_filetime != 0,
            ),
        )

    exit_code = selected_api.get_exit_code(handle)
    if exit_code is None:
        observer.close()
        return ProcessHandleAcquisition(
            None,
            ProcessExitResult.unavailable(
                ProcessExitState.EXIT_CODE_QUERY_FAILED,
                creation_filetime_matches=True,
                exit_filetime_recorded=times.exit_filetime != 0,
            ),
        )
    if times.exit_filetime != 0 or exit_code != STILL_ACTIVE:
        observer.close()
        if times.exit_filetime != 0 and exit_code != STILL_ACTIVE:
            return ProcessHandleAcquisition(
                None,
                ProcessExitResult(
                    state=ProcessExitState.EXITED_WITH_CODE,
                    creation_filetime_matches=True,
                    exit_filetime_recorded=True,
                    exit_code_observed=True,
                    exit_code=exit_code,
                    wait_signaled=False,
                ),
            )
        return ProcessHandleAcquisition(
            None,
            ProcessExitResult.unavailable(
                ProcessExitState.EXITED_CODE_UNAVAILABLE,
                creation_filetime_matches=True,
                exit_filetime_recorded=times.exit_filetime != 0,
            ),
        )

    return ProcessHandleAcquisition(
        observer,
        ProcessExitResult(
            state=ProcessExitState.RUNNING,
            creation_filetime_matches=True,
            exit_filetime_recorded=False,
            exit_code_observed=False,
            exit_code=None,
            wait_signaled=False,
        ),
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--creation-filetime", required=True, type=int)
    parser.add_argument("--timeout-ms", required=True, type=int)
    return parser.parse_args(argv)


def _main(argv: list[str]) -> int:
    arguments = _parse_args(argv)
    acquisition = retain_process_exit_handle(
        arguments.pid,
        arguments.creation_filetime,
    )
    result = acquisition.result
    observer = acquisition.observer
    if observer is not None:
        try:
            result = observer.wait_for_exit(arguments.timeout_ms)
        finally:
            observer.close()
    print(
        json.dumps(
            {
                "schema": 1,
                "state": result.state,
                "creation_filetime_matches": (
                    result.creation_filetime_matches
                ),
                "exit_filetime_recorded": result.exit_filetime_recorded,
                "exit_code_observed": result.exit_code_observed,
                "exit_code": result.exit_code,
                "wait_signaled": result.wait_signaled,
            },
            separators=(",", ":"),
        )
    )
    return 0 if result.state is ProcessExitState.EXITED_WITH_CODE else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
