from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtTest import QSignalSpy

from arkclaw.application.active_turn_coordinator import (
    DefaultActiveTurnCoordinator,
)
from arkclaw.application.agent_loop import AgentLoop
from arkclaw.application.context_manager import ContextManager
from arkclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
    ProviderProfileService,
)
from arkclaw.application.runtime_session_controller import (
    RuntimeCommandResult,
    RuntimeEventSink,
    RuntimeSessionController,
    RuntimeSnapshot,
)
from arkclaw.bootstrap.qt_runtime import (
    QT_SMOKE_SECONDARY_PROFILE_ID,
    FakeQtRuntimeCompositionRoot,
)
from arkclaw.domain.events import LLMEvent
from arkclaw.domain.models import (
    FAKE_DEFAULT_PROFILE_ID,
    FAKE_PROVIDER_ID,
    CredentialBinding,
    ProfileId,
    ProviderContinuation,
    ProviderProfile,
)
from arkclaw.domain.ports import LLMProvider
from arkclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)
from arkclaw.infrastructure.llm.fake_provider import FakeProvider
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.runtime_thread import (
    RuntimeControllerFactory,
    RuntimeThread,
    RuntimeThreadCommand,
    RuntimeThreadCommandType,
)

_OPTIONS = ProviderActivationOptions(
    timeout_seconds=30.0,
    max_retries=0,
    stream=True,
)


@pytest.fixture(scope="module")
def qcore_application() -> Iterator[QCoreApplication]:
    existing = QCoreApplication.instance()
    app = (
        existing
        if isinstance(existing, QCoreApplication)
        else QCoreApplication([])
    )
    yield app


def _rows(spy: QSignalSpy) -> list[list[object]]:
    return [list(spy.at(index)) for index in range(spy.count())]


def _run_qt_until(
    predicate: Callable[[], bool],
    *,
    timeout_ms: int,
) -> bool:
    if predicate():
        return True
    event_loop = QEventLoop()
    poll_timer = QTimer()
    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)

    def poll() -> None:
        if predicate():
            event_loop.quit()

    poll_timer.timeout.connect(poll)
    timeout_timer.timeout.connect(event_loop.quit)
    poll_timer.start(1)
    timeout_timer.start(timeout_ms)
    event_loop.exec()
    poll_timer.stop()
    timeout_timer.stop()
    return predicate()


def _wait_for(
    spy: QSignalSpy,
    predicate: Callable[[list[object]], bool],
    *,
    timeout_ms: int = 5000,
) -> list[object]:
    def matching_row() -> list[object] | None:
        return next((row for row in _rows(spy) if predicate(row)), None)

    if _run_qt_until(
        lambda: matching_row() is not None,
        timeout_ms=timeout_ms,
    ):
        row = matching_row()
        if row is not None:
            return row
    raise AssertionError(f"Expected Qt signal was not emitted: {_rows(spy)!r}")


def _wait_count(
    spy: QSignalSpy,
    expected_count: int,
    *,
    timeout_ms: int = 5000,
) -> None:
    if _run_qt_until(
        lambda: spy.count() >= expected_count,
        timeout_ms=timeout_ms,
    ):
        return
    raise AssertionError(
        f"Expected {expected_count} Qt signals, received {_rows(spy)!r}"
    )


def _wait_command(spy: QSignalSpy, command_id: str) -> None:
    _wait_for(
        spy,
        lambda row: bool(row) and row[0] == command_id,
    )


def _terminal_count(
    command_id: str,
    completed_spy: QSignalSpy,
    failed_spy: QSignalSpy,
) -> int:
    completed = sum(
        1 for row in _rows(completed_spy) if row[0] == command_id
    )
    failed = sum(1 for row in _rows(failed_spy) if row[0] == command_id)
    return completed + failed


class _ScriptedFactory:
    def __init__(self, script: Sequence[LLMEvent]) -> None:
        self._script = tuple(script)

    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        if profile.provider_id != FAKE_PROVIDER_ID:
            raise ValueError("The Qt test factory supports Fake only.")
        return FakeProvider(script=self._script)


class _ScriptedFactoryBuilder:
    def __init__(self, script: Sequence[LLMEvent]) -> None:
        self._script = tuple(script)

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _ScriptedFactory:
        del credential_bindings
        return _ScriptedFactory(self._script)


class _ScriptedCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        script: Sequence[LLMEvent],
    ) -> None:
        self._metadata_path = metadata_path
        self._script = tuple(script)
        self.creation_thread_id: int | None = None

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        self.creation_thread_id = threading.get_ident()
        coordinator = DefaultActiveTurnCoordinator()
        service = ProviderProfileService(
            JsonProviderProfileRepository(self._metadata_path),
            _ScriptedFactoryBuilder(self._script),
            turn_coordinator=coordinator,
        )
        service.ensure_builtin_metadata()
        return RuntimeSessionController(
            service,
            coordinator,
            lambda provider: AgentLoop(provider, ContextManager()),
            event_sink,
            runtime_thread_id=runtime_thread_id,
        )


class _BlockingFactory:
    def __init__(
        self,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self._entered = entered
        self._release = release

    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        if profile.provider_id != FAKE_PROVIDER_ID:
            raise ValueError("The Qt test factory supports Fake only.")
        self._entered.set()
        self._release.wait()
        return FakeProvider(response_text="qt-runtime-ok")


class _BlockingFactoryBuilder:
    def __init__(
        self,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self._entered = entered
        self._release = release

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _BlockingFactory:
        del credential_bindings
        return _BlockingFactory(self._entered, self._release)


class _BlockingFactoryCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self._metadata_path = metadata_path
        self._entered = entered
        self._release = release
        self.creation_thread_id: int | None = None

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        self.creation_thread_id = threading.get_ident()
        coordinator = DefaultActiveTurnCoordinator()
        service = ProviderProfileService(
            JsonProviderProfileRepository(self._metadata_path),
            _BlockingFactoryBuilder(self._entered, self._release),
            turn_coordinator=coordinator,
        )
        service.ensure_builtin_metadata()
        return RuntimeSessionController(
            service,
            coordinator,
            lambda provider: AgentLoop(provider, ContextManager()),
            event_sink,
            runtime_thread_id=runtime_thread_id,
        )


class _FailingCompositionRoot:
    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        del event_sink, runtime_thread_id
        raise RuntimeError("opaque-startup-secret")


class _CloseControl:
    def __init__(self) -> None:
        self.fail_close = True
        self.cancel_close = False
        self.close_calls = 0


class _CloseControlledProvider(FakeProvider):
    def __init__(self, control: _CloseControl) -> None:
        super().__init__(response_text="qt-runtime-ok")
        self._control = control

    async def aclose(self) -> None:
        self._control.close_calls += 1
        if self._control.cancel_close:
            raise asyncio.CancelledError("opaque-provider-close-cancel-secret")
        if self._control.fail_close:
            raise RuntimeError("opaque-close-secret")
        await super().aclose()


class _CloseControlledFactory:
    def __init__(self, control: _CloseControl) -> None:
        self._control = control

    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        if profile.provider_id != FAKE_PROVIDER_ID:
            raise ValueError("The Qt test factory supports Fake only.")
        return _CloseControlledProvider(self._control)


class _CloseControlledFactoryBuilder:
    def __init__(self, control: _CloseControl) -> None:
        self._control = control

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _CloseControlledFactory:
        del credential_bindings
        return _CloseControlledFactory(self._control)


class _CloseControlledCompositionRoot:
    def __init__(self, metadata_path: Path, control: _CloseControl) -> None:
        self._metadata_path = metadata_path
        self._control = control

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        coordinator = DefaultActiveTurnCoordinator()
        service = ProviderProfileService(
            JsonProviderProfileRepository(self._metadata_path),
            _CloseControlledFactoryBuilder(self._control),
            turn_coordinator=coordinator,
        )
        service.ensure_builtin_metadata()
        return RuntimeSessionController(
            service,
            coordinator,
            lambda provider: AgentLoop(provider, ContextManager()),
            event_sink,
            runtime_thread_id=runtime_thread_id,
        )


class _GatedCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        entered: threading.Event,
        release: threading.Event,
        *,
        fail_bootstrap: bool = False,
    ) -> None:
        self._delegate = FakeQtRuntimeCompositionRoot(metadata_path)
        self._entered = entered
        self._release = release
        self._fail_bootstrap = fail_bootstrap

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        self._entered.set()
        self._release.wait()
        if self._fail_bootstrap:
            raise RuntimeError("opaque-gated-bootstrap-secret")
        return self._delegate(event_sink, runtime_thread_id)


class _AsyncGeneratorCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        primed: threading.Event,
        finalized: threading.Event,
    ) -> None:
        self._delegate = FakeQtRuntimeCompositionRoot(metadata_path)
        self._primed = primed
        self._finalized = finalized
        self._generator: Any = None
        self._prime_task: asyncio.Task[None] | None = None

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        async def generator() -> AsyncIterator[None]:
            try:
                yield None
            finally:
                self._finalized.set()

        async def prime_generator() -> None:
            self._generator = generator()
            await anext(self._generator)
            self._primed.set()

        loop = asyncio.get_event_loop()
        self._prime_task = loop.create_task(prime_generator())
        return self._delegate(event_sink, runtime_thread_id)


class _ExecutorCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self._delegate = FakeQtRuntimeCompositionRoot(metadata_path)
        self._entered = entered
        self._release = release

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        def executor_work() -> None:
            self._entered.set()
            self._release.wait()

        asyncio.get_event_loop().run_in_executor(None, executor_work)
        return self._delegate(event_sink, runtime_thread_id)


class _LoopCleanupFailureCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        failure_kind: str,
        *,
        cancel: bool = False,
    ) -> None:
        self._delegate = FakeQtRuntimeCompositionRoot(metadata_path)
        self._failure_kind = failure_kind
        self._cancel = cancel

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        async def fail_cleanup() -> None:
            if self._cancel:
                raise asyncio.CancelledError(
                    "opaque-loop-cleanup-cancel-secret"
                )
            raise RuntimeError("opaque-loop-cleanup-secret")

        loop = asyncio.get_event_loop()
        if self._failure_kind == "asyncgen":
            loop.shutdown_asyncgens = fail_cleanup  # type: ignore[method-assign]
        else:
            loop.shutdown_default_executor = (  # type: ignore[method-assign]
                fail_cleanup
            )
        return self._delegate(event_sink, runtime_thread_id)


class _MultipleCleanupCompositionRoot:
    def __init__(
        self,
        metadata_path: Path,
        asyncgen_called: threading.Event,
        executor_called: threading.Event,
    ) -> None:
        self._delegate = FakeQtRuntimeCompositionRoot(metadata_path)
        self._asyncgen_called = asyncgen_called
        self._executor_called = executor_called

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        async def cancel_asyncgens() -> None:
            self._asyncgen_called.set()
            raise asyncio.CancelledError(
                "opaque-multiple-cleanup-cancel-secret"
            )

        async def fail_executor() -> None:
            self._executor_called.set()
            raise RuntimeError("opaque-multiple-cleanup-failure-secret")

        loop = asyncio.get_event_loop()
        loop.shutdown_asyncgens = (  # type: ignore[method-assign]
            cancel_asyncgens
        )
        loop.shutdown_default_executor = (  # type: ignore[method-assign]
            fail_executor
        )
        return self._delegate(event_sink, runtime_thread_id)


class _FatalRuntimeExit(BaseException):
    pass


class _GatedFakeLoop:
    def __init__(
        self,
        entered: threading.Event,
        release: threading.Event,
        *,
        fail_schedule: bool = False,
    ) -> None:
        self._entered = entered
        self._release = release
        self._fail_schedule = fail_schedule
        self.scheduled = False

    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(
        self,
        callback: Callable[[RuntimeThreadCommand], None],
        command: RuntimeThreadCommand,
    ) -> None:
        self._entered.set()
        self._release.wait()
        if self._fail_schedule:
            raise RuntimeError("Event loop is closed")
        self.scheduled = True
        del callback, command


def test_qt_start_then_immediate_shutdown_never_becomes_ready(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "early-shutdown.json")
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    start_id = bridge.start_runtime()
    shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)

    assert ready_spy.count() == 0
    assert _terminal_count(start_id, completed_spy, failed_spy) == 1
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert _rows(failed_spy) == []
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0
    assert (
        bridge.runtime_thread.submit(
            RuntimeThreadCommand(
                command_id="after-loop-close",
                type=RuntimeThreadCommandType.REQUEST_SNAPSHOT,
            )
        )
        is False
    )


def test_qt_startup_gate_shutdown_intent_is_not_lost(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    entered = threading.Event()
    release = threading.Event()
    bridge = QtRuntimeBridge(
        _GatedCompositionRoot(
            tmp_path / "gated-shutdown.json",
            entered,
            release,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    start_id = bridge.start_runtime()
    assert _run_qt_until(entered.is_set, timeout_ms=5000)
    shutdown_id = bridge.shutdown(cancel_active=False)
    duplicate_shutdown_id = bridge.shutdown(cancel_active=True)
    rejected_message_id = bridge.send_message("blocked", "starting")

    duplicate_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == duplicate_shutdown_id,
    )
    closing_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == rejected_message_id,
    )
    assert duplicate_failure[1] == "shutdown_in_progress"
    assert closing_failure[1] == "runtime_closing"
    assert ready_spy.count() == 0

    gui_timer_fired = threading.Event()
    QTimer.singleShot(0, gui_timer_fired.set)
    assert _run_qt_until(gui_timer_fired.is_set, timeout_ms=5000)
    release.set()
    _wait_count(shutdown_spy, 1)

    assert ready_spy.count() == 0
    assert _terminal_count(start_id, completed_spy, failed_spy) == 1
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert _terminal_count(
        duplicate_shutdown_id,
        completed_spy,
        failed_spy,
    ) == 1
    assert _terminal_count(
        rejected_message_id,
        completed_spy,
        failed_spy,
    ) == 1
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_startup_shutdown_bootstrap_failure_finalizes_both_commands(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    entered = threading.Event()
    release = threading.Event()
    bridge = QtRuntimeBridge(
        _GatedCompositionRoot(
            tmp_path / "gated-bootstrap-failure.json",
            entered,
            release,
            fail_bootstrap=True,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    start_id = bridge.start_runtime()
    assert _run_qt_until(entered.is_set, timeout_ms=5000)
    shutdown_id = bridge.shutdown(cancel_active=True)
    release.set()
    _wait_count(shutdown_spy, 1)

    assert ready_spy.count() == 0
    assert completed_spy.count() == 0
    assert _terminal_count(start_id, completed_spy, failed_spy) == 1
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    failures = {
        str(row[0]): str(row[1])
        for row in _rows(failed_spy)
    }
    assert failures == {
        start_id: "runtime_bootstrap_failed",
        shutdown_id: "runtime_bootstrap_failed",
    }
    assert "opaque-gated-bootstrap-secret" not in repr(_rows(failed_spy))
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_runtime_thread_submit_is_linearized_with_close() -> None:
    entered = threading.Event()
    release = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()
    loop = _GatedFakeLoop(entered, release)
    thread = RuntimeThread(_FailingCompositionRoot())
    command = RuntimeThreadCommand(
        command_id="linearized-submit",
        type=RuntimeThreadCommandType.REQUEST_SNAPSHOT,
    )
    with thread._guard:
        thread._loop = cast(Any, loop)
        thread._queue = asyncio.Queue()
        thread._ready = True
        thread._accepting_submissions = True
    submit_result: list[bool] = []

    submitter = threading.Thread(
        target=lambda: submit_result.append(thread.submit(command))
    )

    def close_submission_boundary() -> None:
        close_started.set()
        thread._stop_accepting()
        close_finished.set()

    closer = threading.Thread(target=close_submission_boundary)
    submitter.start()
    assert entered.wait(5)
    closer.start()
    assert close_started.wait(5)
    assert not close_finished.is_set()
    release.set()
    submitter.join(5)
    closer.join(5)

    assert submit_result == [True]
    assert loop.scheduled
    assert close_finished.is_set()
    assert thread.submit(command) is False


def test_runtime_thread_closed_loop_schedule_failure_returns_false() -> None:
    entered = threading.Event()
    release = threading.Event()
    release.set()
    loop = _GatedFakeLoop(entered, release, fail_schedule=True)
    thread = RuntimeThread(_FailingCompositionRoot())
    command = RuntimeThreadCommand(
        command_id="closed-loop-submit",
        type=RuntimeThreadCommandType.REQUEST_SNAPSHOT,
    )
    with thread._guard:
        thread._loop = cast(Any, loop)
        thread._queue = asyncio.Queue()
        thread._ready = True
        thread._accepting_submissions = True

    assert thread.submit(command) is False
    thread._stop_accepting()
    assert thread.submit(command) is False


def test_qt_unexpected_runtime_exit_fails_all_pending_once(
    tmp_path: Path,
    qcore_application: QCoreApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qcore_application
    entered = threading.Event()
    release = threading.Event()

    async def fatal_execute(
        runtime_thread: RuntimeThread,
        command: RuntimeThreadCommand,
        controller: RuntimeSessionController,
    ) -> RuntimeCommandResult:
        del runtime_thread, command, controller
        entered.set()
        await asyncio.get_running_loop().run_in_executor(
            None,
            release.wait,
        )
        raise _FatalRuntimeExit

    monkeypatch.setattr(RuntimeThread, "_execute_command", fatal_execute)
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "unexpected-exit.json")
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    start_id = bridge.start_runtime()
    _wait_count(ready_spy, 1)
    first_id = bridge.request_snapshot()
    assert _run_qt_until(entered.is_set, timeout_ms=5000)
    second_id = bridge.request_snapshot()
    third_id = bridge.request_snapshot()
    release.set()
    _wait_count(shutdown_spy, 1)

    assert _terminal_count(start_id, completed_spy, failed_spy) == 1
    for command_id in (first_id, second_id, third_id):
        assert _terminal_count(command_id, completed_spy, failed_spy) == 1

        def is_selected(
            row: list[object],
            selected: str = command_id,
        ) -> bool:
            return row[0] == selected

        failure = _wait_for(
            failed_spy,
            is_selected,
        )
        assert failure[1] == "runtime_thread_stopped_unexpectedly"

    completed_before_stale = completed_spy.count()
    failed_before_stale = failed_spy.count()
    bridge.runtime_thread.command_result_emitted.emit(
        first_id,
        True,
        "none",
        "",
    )
    stale_processed = threading.Event()
    QTimer.singleShot(0, stale_processed.set)
    assert _run_qt_until(stale_processed.is_set, timeout_ms=5000)
    assert completed_spy.count() == completed_before_stale
    assert failed_spy.count() == failed_before_stale
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_cancelled_command_fails_active_and_other_pending_once(
    tmp_path: Path,
    qcore_application: QCoreApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qcore_application
    entered = threading.Event()
    release = threading.Event()

    async def cancel_execute(
        runtime_thread: RuntimeThread,
        command: RuntimeThreadCommand,
        controller: RuntimeSessionController,
    ) -> RuntimeCommandResult:
        del runtime_thread, command, controller
        entered.set()
        await asyncio.get_running_loop().run_in_executor(
            None,
            release.wait,
        )
        raise asyncio.CancelledError("opaque-command-cancel-secret")

    monkeypatch.setattr(RuntimeThread, "_execute_command", cancel_execute)
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "cancelled-command.json")
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    finished_spy = QSignalSpy(bridge.runtime_thread.finished)

    start_id = bridge.start_runtime()
    _wait_count(ready_spy, 1)
    active_id = bridge.request_snapshot()
    assert _run_qt_until(entered.is_set, timeout_ms=5000)
    second_id = bridge.request_snapshot()
    third_id = bridge.request_snapshot()
    release.set()
    _wait_count(shutdown_spy, 1)
    _wait_count(finished_spy, 1)

    assert _terminal_count(start_id, completed_spy, failed_spy) == 1
    assert _wait_for(
        failed_spy,
        lambda row: row[0] == active_id,
    )[1] == "runtime_command_cancelled"
    for command_id in (second_id, third_id):
        def is_selected(
            row: list[object],
            selected: str = command_id,
        ) -> bool:
            return row[0] == selected

        assert _wait_for(
            failed_spy,
            is_selected,
        )[1] == "runtime_thread_cancelled"
    for command_id in (active_id, second_id, third_id):
        assert _terminal_count(command_id, completed_spy, failed_spy) == 1
    assert _rows(shutdown_spy) == [
        [False, "runtime_command_cancelled"]
    ]
    assert finished_spy.count() == 1
    assert "opaque-command-cancel-secret" not in repr(
        _rows(failed_spy) + _rows(shutdown_spy)
    )
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


@pytest.mark.parametrize("starting_shutdown", [False, True])
def test_qt_shutdown_cancellation_stops_thread_normally(
    tmp_path: Path,
    qcore_application: QCoreApplication,
    monkeypatch: pytest.MonkeyPatch,
    starting_shutdown: bool,
) -> None:
    del qcore_application
    original_execute = RuntimeThread._execute_command

    async def cancel_shutdown(
        runtime_thread: RuntimeThread,
        command: RuntimeThreadCommand,
        controller: RuntimeSessionController,
    ) -> RuntimeCommandResult:
        if command.type is RuntimeThreadCommandType.SHUTDOWN:
            raise asyncio.CancelledError("opaque-shutdown-cancel-secret")
        return await original_execute(runtime_thread, command, controller)

    monkeypatch.setattr(RuntimeThread, "_execute_command", cancel_shutdown)
    entered = threading.Event()
    release = threading.Event()
    root: RuntimeControllerFactory
    if starting_shutdown:
        root = _GatedCompositionRoot(
            tmp_path / "starting-shutdown-cancel.json",
            entered,
            release,
        )
    else:
        root = FakeQtRuntimeCompositionRoot(
            tmp_path / "ready-shutdown-cancel.json"
        )
    bridge = QtRuntimeBridge(root)
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    finished_spy = QSignalSpy(bridge.runtime_thread.finished)

    start_id = bridge.start_runtime()
    if starting_shutdown:
        assert _run_qt_until(entered.is_set, timeout_ms=5000)
    else:
        _wait_count(ready_spy, 1)
    shutdown_id = bridge.shutdown(cancel_active=True)
    if starting_shutdown:
        release.set()
    _wait_count(shutdown_spy, 1)
    _wait_count(finished_spy, 1)

    assert ready_spy.count() == (0 if starting_shutdown else 1)
    assert _terminal_count(start_id, completed_spy, failed_spy) == 1
    failure = _wait_for(
        failed_spy,
        lambda row: row[0] == shutdown_id,
    )
    assert failure[1] == "runtime_shutdown_cancelled"
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert _rows(shutdown_spy) == [
        [False, "runtime_shutdown_cancelled"]
    ]
    assert finished_spy.count() == 1
    assert "opaque-shutdown-cancel-secret" not in repr(
        _rows(failed_spy) + _rows(shutdown_spy)
    )
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_provider_activation_cancellation_is_safely_bounded(
    tmp_path: Path,
    qcore_application: QCoreApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qcore_application

    async def cancel_activation(
        controller: RuntimeSessionController,
        profile_id: ProfileId,
        options: ProviderActivationOptions,
        turn_handling: ActiveTurnHandling | None,
    ) -> RuntimeCommandResult:
        del controller, profile_id, options, turn_handling
        raise asyncio.CancelledError("opaque-activation-cancel-secret")

    monkeypatch.setattr(
        RuntimeSessionController,
        "activate_profile",
        cancel_activation,
    )
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(
            tmp_path / "activation-cancel.json"
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    finished_spy = QSignalSpy(bridge.runtime_thread.finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    activation_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_count(shutdown_spy, 1)
    _wait_count(finished_spy, 1)

    failure = _wait_for(
        failed_spy,
        lambda row: row[0] == activation_id,
    )
    assert failure[1] == "runtime_command_cancelled"
    assert _rows(shutdown_spy) == [
        [False, "runtime_command_cancelled"]
    ]
    assert "opaque-activation-cancel-secret" not in repr(
        _rows(failed_spy)
    )
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_cancelled_error_subprocess_exits_without_qthread_override_error(
) -> None:
    probe = Path(__file__).with_name(
        "runtime_thread_cancelled_subprocess.py"
    )
    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=probe.parents[2],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"

    assert result.returncode == 0
    assert "cancel_subprocess=True" in result.stdout
    assert "safe_code=runtime_command_cancelled" in result.stdout
    assert "command_terminal_count=1" in result.stdout
    assert "shutdown_finished_count=1" in result.stdout
    assert "qthread_finished_count=1" in result.stdout
    assert "thread_running=False" in result.stdout
    assert "pending_asyncio_tasks=0" in result.stdout
    assert result.stderr == ""
    assert "Error calling Python override of QThread::run()" not in combined
    assert "Traceback" not in combined
    assert "opaque-subprocess-cancel-secret" not in combined


def test_qt_event_loop_finalizes_async_generators(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    primed = threading.Event()
    finalized = threading.Event()
    bridge = QtRuntimeBridge(
        _AsyncGeneratorCompositionRoot(
            tmp_path / "asyncgen-finalization.json",
            primed,
            finalized,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    assert _run_qt_until(primed.is_set, timeout_ms=5000)
    bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)

    assert finalized.is_set()
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_event_loop_waits_for_default_executor_cleanup(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    entered = threading.Event()
    release = threading.Event()
    bridge = QtRuntimeBridge(
        _ExecutorCompositionRoot(
            tmp_path / "executor-finalization.json",
            entered,
            release,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    assert entered.is_set()
    bridge.shutdown(cancel_active=True)
    gui_timer_fired = threading.Event()
    QTimer.singleShot(0, gui_timer_fired.set)
    assert _run_qt_until(gui_timer_fired.is_set, timeout_ms=5000)
    assert shutdown_spy.count() == 0
    assert bridge.runtime_thread.isRunning()

    release.set()
    _wait_count(shutdown_spy, 1)
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("asyncgen", "runtime_asyncgen_cleanup_failed"),
        ("executor", "runtime_executor_cleanup_failed"),
    ],
)
def test_qt_loop_cleanup_failures_are_safely_mapped(
    tmp_path: Path,
    qcore_application: QCoreApplication,
    failure_kind: str,
    expected_code: str,
) -> None:
    del qcore_application
    bridge = QtRuntimeBridge(
        _LoopCleanupFailureCompositionRoot(
            tmp_path / f"{failure_kind}-cleanup-failure.json",
            failure_kind,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)
    failure = _wait_for(
        failed_spy,
        lambda row: row[0] == shutdown_id,
    )

    assert failure[1] == expected_code
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert "opaque-loop-cleanup-secret" not in repr(
        _rows(failed_spy) + _rows(shutdown_spy)
    )
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("tasks", "runtime_task_cleanup_cancelled"),
        ("asyncgen", "runtime_asyncgen_cleanup_cancelled"),
        ("executor", "runtime_executor_cleanup_cancelled"),
    ],
)
def test_qt_loop_cleanup_cancellation_is_safely_bounded(
    tmp_path: Path,
    qcore_application: QCoreApplication,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: str,
) -> None:
    del qcore_application

    async def cancel_task_cleanup() -> int:
        raise asyncio.CancelledError("opaque-task-cleanup-cancel-secret")

    root: RuntimeControllerFactory
    if failure_kind == "tasks":
        monkeypatch.setattr(
            RuntimeThread,
            "_cancel_remaining_tasks",
            staticmethod(cancel_task_cleanup),
        )
        root = FakeQtRuntimeCompositionRoot(
            tmp_path / "task-cleanup-cancel.json"
        )
    else:
        root = _LoopCleanupFailureCompositionRoot(
            tmp_path / f"{failure_kind}-cleanup-cancel.json",
            failure_kind,
            cancel=True,
        )
    bridge = QtRuntimeBridge(root)
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    finished_spy = QSignalSpy(bridge.runtime_thread.finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)
    _wait_count(finished_spy, 1)

    failure = _wait_for(
        failed_spy,
        lambda row: row[0] == shutdown_id,
    )
    assert failure[1] == expected_code
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert _rows(shutdown_spy) == [[False, expected_code]]
    visible_output = repr(_rows(failed_spy) + _rows(shutdown_spy))
    assert "opaque-task-cleanup-cancel-secret" not in visible_output
    assert "opaque-loop-cleanup-cancel-secret" not in visible_output
    assert finished_spy.count() == 1
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_cleanup_preserves_first_cancellation_and_runs_later_steps(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    asyncgen_called = threading.Event()
    executor_called = threading.Event()
    bridge = QtRuntimeBridge(
        _MultipleCleanupCompositionRoot(
            tmp_path / "multiple-cleanup-failures.json",
            asyncgen_called,
            executor_called,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    finished_spy = QSignalSpy(bridge.runtime_thread.finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)
    _wait_count(finished_spy, 1)

    assert asyncgen_called.is_set()
    assert executor_called.is_set()
    assert _wait_for(
        failed_spy,
        lambda row: row[0] == shutdown_id,
    )[1] == "runtime_asyncgen_cleanup_cancelled"
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert _rows(shutdown_spy) == [
        [False, "runtime_asyncgen_cleanup_cancelled"]
    ]
    visible_output = repr(_rows(failed_spy) + _rows(shutdown_spy))
    assert "opaque-multiple-cleanup-cancel-secret" not in visible_output
    assert "opaque-multiple-cleanup-failure-secret" not in visible_output
    assert finished_spy.count() == 1
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_runtime_fake_smoke_commands_signals_and_shutdown(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(
            tmp_path / "qt-smoke-providers.json"
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    snapshot_spy = QSignalSpy(bridge.runtime_state_changed)
    turn_completed_spy = QSignalSpy(bridge.turn_completed)
    turn_cancelled_spy = QSignalSpy(bridge.turn_cancelled)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    thread_outcome_spy = QSignalSpy(
        bridge.runtime_thread.shutdown_outcome_emitted
    )
    thread_ready_spy = QSignalSpy(bridge.runtime_thread.worker_ready)
    signal_threads: list[QThread] = []
    bridge.runtime_ready.connect(
        lambda: signal_threads.append(QThread.currentThread())
    )
    bridge.command_completed.connect(
        lambda _command_id: signal_threads.append(QThread.currentThread())
    )
    bridge.turn_completed.connect(
        lambda _turn_id, _text: signal_threads.append(
            QThread.currentThread()
        )
    )
    gui_thread_id = threading.get_ident()

    start_id = bridge.start_runtime()
    duplicate_start_id = bridge.start_runtime()
    _wait_count(ready_spy, 1)
    assert ready_spy.count() == 1, (
        _rows(thread_outcome_spy),
        bridge.runtime_thread.isRunning(),
        bridge.runtime_thread.runtime_thread_id,
        _rows(thread_ready_spy),
    )
    _wait_command(completed_spy, start_id)
    duplicate_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == duplicate_start_id,
    )
    assert duplicate_failure[1] == "runtime_already_started"

    snapshot = _rows(snapshot_spy)[-1][0]
    assert isinstance(snapshot, RuntimeSnapshot)
    assert snapshot.runtime_thread_id != gui_thread_id
    assert bridge.runtime_thread.runtime_thread_id == snapshot.runtime_thread_id
    assert bridge.thread() is qcore_application.thread()
    assert bridge.runtime_thread.thread() is qcore_application.thread()
    assert signal_threads
    assert all(
        thread is qcore_application.thread()
        for thread in signal_threads
    )

    activate_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activate_id)

    snapshot_id = bridge.request_snapshot()
    _wait_command(completed_spy, snapshot_id)
    _wait_count(snapshot_spy, 3)

    message_id = bridge.send_message("hello", "qt-smoke")
    _wait_command(completed_spy, message_id)
    _wait_count(turn_completed_spy, 1)
    assert _rows(turn_completed_spy)[-1][1] == "qt-runtime-ok"

    completed_turn_count = turn_completed_spy.count()
    missing_policy_message = bridge.send_message(
        "requires decision",
        "qt-smoke",
    )
    missing_policy_switch = bridge.activate_profile(
        QT_SMOKE_SECONDARY_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, missing_policy_message)
    missing_policy_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == missing_policy_switch,
    )
    assert missing_policy_failure[1] == "switch_requires_turn_decision"
    _wait_count(turn_completed_spy, completed_turn_count + 1)

    cancel_message = bridge.send_message("cancel me", "qt-smoke")
    cancel_switch = bridge.activate_profile(
        QT_SMOKE_SECONDARY_PROFILE_ID.value,
        _OPTIONS,
        ActiveTurnHandling.CANCEL_ACTIVE,
    )
    _wait_command(completed_spy, cancel_message)
    _wait_command(completed_spy, cancel_switch)
    _wait_count(turn_cancelled_spy, 1)

    wait_message = bridge.send_message("wait for me", "qt-smoke")
    wait_switch = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        ActiveTurnHandling.WAIT_FOR_ACTIVE,
    )
    _wait_command(completed_spy, wait_message)
    _wait_command(completed_spy, wait_switch)

    shutdown_id = bridge.shutdown(cancel_active=True)
    rejected_while_closing = bridge.send_message(
        "too late",
        "qt-smoke",
    )
    closing_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == rejected_while_closing,
    )
    assert closing_failure[1] == "runtime_closing"
    _wait_count(shutdown_spy, 1)
    assert _rows(shutdown_spy)[-1] == [True, "none"]
    _wait_command(completed_spy, shutdown_id)
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0

    rejected_after_close = bridge.send_message("closed", "qt-smoke")
    closed_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == rejected_after_close,
    )
    assert closed_failure[1] == "runtime_closed"

    repeated_shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_command(completed_spy, repeated_shutdown_id)
    assert _rows(shutdown_spy)[-1] == [
        True,
        "runtime_already_closed",
    ]
    assert signal_threads
    assert all(
        thread is qcore_application.thread()
        for thread in signal_threads
    )


def test_qt_partial_delta_failure_never_emits_turn_completed(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    secret = "opaque-qt-never-emit"
    root = _ScriptedCompositionRoot(
        tmp_path / "qt-failure-providers.json",
        (
            LLMEvent.text_delta("partial"),
            LLMEvent.failure(
                "fake_failure",
                "The Fake Provider failed.",
            ),
        ),
    )
    bridge = QtRuntimeBridge(root)
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_command_spy = QSignalSpy(bridge.command_completed)
    delta_spy = QSignalSpy(bridge.text_delta)
    turn_failed_spy = QSignalSpy(bridge.turn_failed)
    turn_completed_spy = QSignalSpy(bridge.turn_completed)
    snapshot_spy = QSignalSpy(bridge.runtime_state_changed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    assert root.creation_thread_id == bridge.runtime_thread.runtime_thread_id
    assert root.creation_thread_id != threading.get_ident()
    activate_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_command_spy, activate_id)
    send_id = bridge.send_message("fail safely", "qt-failure")
    _wait_command(completed_command_spy, send_id)

    _wait_count(delta_spy, 1)
    _wait_count(turn_failed_spy, 1)
    assert turn_completed_spy.count() == 0
    assert _rows(turn_failed_spy)[-1][1:] == [
        "fake_failure",
        "The Fake Provider failed.",
    ]
    visible = repr(
        _rows(delta_spy)
        + _rows(turn_failed_spy)
        + _rows(snapshot_spy)
    )
    assert secret not in visible
    assert "ProviderContinuation" not in visible

    bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)
    assert not bridge.runtime_thread.isRunning()


def test_qt_runtime_graph_is_worker_owned_and_gui_submission_is_nonblocking(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    root = _BlockingFactoryCompositionRoot(
        tmp_path / "qt-nonblocking.json",
        entered,
        release,
    )
    bridge = QtRuntimeBridge(root)
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    assert root.creation_thread_id == bridge.runtime_thread.runtime_thread_id
    assert root.creation_thread_id != threading.get_ident()

    activation_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    assert isinstance(activation_id, str)
    assert not release.is_set()
    assert _run_qt_until(entered.is_set, timeout_ms=5000)

    gui_callback_ran = threading.Event()
    QTimer.singleShot(0, gui_callback_ran.set)
    assert _run_qt_until(gui_callback_ran.is_set, timeout_ms=5000)
    assert completed_spy.count() == 1

    release.set()
    _wait_command(completed_spy, activation_id)
    bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0
    assert bridge.thread() is qcore_application.thread()


def test_qt_startup_failure_is_correlated_and_redacted(
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    bridge = QtRuntimeBridge(_FailingCompositionRoot())
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    start_id = bridge.start_runtime()
    failure = _wait_for(
        failed_spy,
        lambda row: row[0] == start_id,
    )
    _wait_count(shutdown_spy, 1)

    assert failure[1:] == [
        "runtime_bootstrap_failed",
        "The runtime thread failed to start safely.",
    ]
    assert _rows(shutdown_spy)[-1] == [
        False,
        "runtime_bootstrap_failed",
    ]
    assert "opaque-startup-secret" not in repr(
        _rows(failed_spy) + _rows(shutdown_spy)
    )
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_failed_provider_cleanup_keeps_thread_alive_for_retry(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    control = _CloseControl()
    bridge = QtRuntimeBridge(
        _CloseControlledCompositionRoot(
            tmp_path / "qt-cleanup-retry.json",
            control,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    activate_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activate_id)

    first_shutdown_id = bridge.shutdown(cancel_active=True)
    first_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == first_shutdown_id,
    )
    _wait_count(shutdown_spy, 1)
    assert first_failure[1:] == [
        "shutdown_provider_cleanup_failed",
        "Provider cleanup did not complete safely.",
    ]
    assert _rows(shutdown_spy)[-1] == [
        False,
        "shutdown_provider_cleanup_failed",
    ]
    assert bridge.runtime_thread.isRunning()
    assert control.close_calls == 1
    assert "opaque-close-secret" not in repr(
        _rows(failed_spy) + _rows(shutdown_spy)
    )

    rejected_id = bridge.send_message("blocked", "cleanup")
    closing_failure = _wait_for(
        failed_spy,
        lambda row: row[0] == rejected_id,
    )
    assert closing_failure[1] == "runtime_closing"

    control.fail_close = False
    second_shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 2)
    _wait_command(completed_spy, second_shutdown_id)
    assert _rows(shutdown_spy)[-1] == [True, "none"]
    assert control.close_calls == 2
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_provider_close_cancellation_is_consumed_at_thread_boundary(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    control = _CloseControl()
    control.fail_close = False
    control.cancel_close = True
    bridge = QtRuntimeBridge(
        _CloseControlledCompositionRoot(
            tmp_path / "qt-provider-close-cancel.json",
            control,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    finished_spy = QSignalSpy(bridge.runtime_thread.finished)

    bridge.start_runtime()
    _wait_count(ready_spy, 1)
    activation_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activation_id)
    shutdown_id = bridge.shutdown(cancel_active=True)
    _wait_count(shutdown_spy, 1)
    _wait_count(finished_spy, 1)

    assert _wait_for(
        failed_spy,
        lambda row: row[0] == shutdown_id,
    )[1] == "runtime_shutdown_cancelled"
    assert _terminal_count(shutdown_id, completed_spy, failed_spy) == 1
    assert _rows(shutdown_spy) == [
        [False, "runtime_shutdown_cancelled"]
    ]
    assert control.close_calls == 2
    assert "opaque-provider-close-cancel-secret" not in repr(
        _rows(failed_spy) + _rows(shutdown_spy)
    )
    assert finished_spy.count() == 1
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_qt_rejects_commands_before_start_and_never_uses_terminate(
    tmp_path: Path,
    qcore_application: QCoreApplication,
) -> None:
    del qcore_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(
            tmp_path / "qt-not-started.json"
        )
    )
    failed_spy = QSignalSpy(bridge.command_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    message_id = bridge.send_message("not ready", "session")
    failure = _wait_for(
        failed_spy,
        lambda row: row[0] == message_id,
    )
    assert failure[1] == "runtime_not_ready"

    shutdown_id = bridge.shutdown(cancel_active=True)
    assert _rows(shutdown_spy)[-1] == [True, "none"]
    assert isinstance(shutdown_id, str)
    assert not bridge.runtime_thread.isRunning()

    source = (
        Path(__file__).parents[2]
        / "src"
        / "arkclaw"
        / "presentation"
        / "qt"
        / "runtime_thread.py"
    ).read_text(encoding="utf-8")
    assert ".terminate(" not in source
    assert "QThread.terminate" not in source


def test_qt_signal_payload_types_exclude_runtime_owned_objects() -> None:
    continuation = ProviderContinuation(
        provider_name="fake",
        state=b"opaque",
    )

    assert repr(continuation) == "<ProviderContinuation redacted>"
    assert "continuation" not in RuntimeSnapshot.__dataclass_fields__
