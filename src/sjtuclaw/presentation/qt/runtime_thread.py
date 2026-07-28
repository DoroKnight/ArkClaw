"""Persistent Qt worker thread hosting one asyncio runtime loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from sjtuclaw.application.autostart_service import AutostartService
from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
)
from sjtuclaw.application.provider_settings_service import (
    ProviderSettingsService,
    ProviderSettingsServiceError,
)
from sjtuclaw.application.runtime_session_controller import (
    RuntimeCommandResult,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeSessionController,
    RuntimeState,
)
from sjtuclaw.domain.models import CredentialId, ProfileId, ProviderId


class RuntimeThreadCommandType(Enum):
    ACTIVATE_PROFILE = "activate_profile"
    SEND_MESSAGE = "send_message"
    CANCEL_ACTIVE_TURN = "cancel_active_turn"
    REQUEST_SNAPSHOT = "request_snapshot"
    REQUEST_PROVIDER_SETTINGS = "request_provider_settings"
    CREATE_PROVIDER_PROFILE = "create_provider_profile"
    UPDATE_PROVIDER_PROFILE = "update_provider_profile"
    DELETE_PROVIDER_PROFILE = "delete_provider_profile"
    SAVE_PROVIDER_CREDENTIAL = "save_provider_credential"
    DELETE_PROVIDER_CREDENTIAL = "delete_provider_credential"
    REQUEST_AUTOSTART = "request_autostart"
    SET_AUTOSTART = "set_autostart"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class RuntimeThreadCommand:
    command_id: str
    type: RuntimeThreadCommandType
    profile_id: str = ""
    options: ProviderActivationOptions | None = None
    turn_handling: ActiveTurnHandling | None = None
    content: str = ""
    session_id: str = ""
    cancel_active: bool = True
    provider_id: str = ""
    display_name: str = ""
    model: str = ""
    credential_id: str = ""
    enabled: bool = False
    secret: str = field(default="", repr=False, compare=False)

    def clear_sensitive(self) -> None:
        """Release the command's secret reference after runtime processing."""

        object.__setattr__(self, "secret", "")


RuntimeControllerFactory = Callable[
    [RuntimeEventSink, int],
    RuntimeSessionController,
]
AutostartServiceFactory = Callable[[], AutostartService]


def _create_unavailable_autostart_service() -> AutostartService:
    return AutostartService(
        None,
        lambda: Path(__file__),
        platform_supported=False,
    )


@dataclass(frozen=True, slots=True)
class _ThreadExitOutcome:
    command_id: str
    success: bool
    safe_code: str
    safe_message: str


class RuntimeThread(QThread):
    """QThread whose ``run`` owns one asyncio loop and runtime graph."""

    worker_ready = Signal(object)
    runtime_event_emitted = Signal(object)
    snapshot_emitted = Signal(object)
    provider_settings_emitted = Signal(str, object)
    autostart_state_emitted = Signal(str, object)
    command_result_emitted = Signal(str, bool, str, str)
    shutdown_outcome_emitted = Signal(str, bool, str, str)

    def __init__(
        self,
        controller_factory: RuntimeControllerFactory,
        autostart_service_factory: AutostartServiceFactory | None = None,
    ) -> None:
        super().__init__()
        self._controller_factory = controller_factory
        self._autostart_service_factory = (
            autostart_service_factory
            or _create_unavailable_autostart_service
        )
        self._autostart_service: AutostartService | None = None
        self._guard = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[RuntimeThreadCommand] | None = None
        self._ready = False
        self._accepting_submissions = False
        self._closing = False
        self._shutdown_in_flight = False
        self._startup_shutdown: RuntimeThreadCommand | None = None
        self._active_command: RuntimeThreadCommand | None = None
        self._outcome_emitted = False
        self._runtime_thread_id: int | None = None
        self._pending_task_count_at_close: int | None = None

    @property
    def runtime_thread_id(self) -> int | None:
        return self._runtime_thread_id

    @property
    def pending_task_count_at_close(self) -> int | None:
        return self._pending_task_count_at_close

    def submit(self, command: RuntimeThreadCommand) -> bool:
        """Submit without blocking the GUI thread."""

        with self._guard:
            loop = self._loop
            queue = self._queue
            if (
                loop is None
                or queue is None
                or not self._ready
                or not self._accepting_submissions
                or self._closing
                or loop.is_closed()
            ):
                return False
            try:
                loop.call_soon_threadsafe(queue.put_nowait, command)
            except RuntimeError:
                return False
            return True

    def request_shutdown(self, command: RuntimeThreadCommand) -> bool:
        """Record or enqueue one shutdown intent without a startup race."""

        if command.type is not RuntimeThreadCommandType.SHUTDOWN:
            return False
        with self._guard:
            if self._shutdown_in_flight:
                return False
            loop = self._loop
            queue = self._queue
            if loop is None or queue is None:
                if self._closing:
                    return False
                self._startup_shutdown = command
                self._shutdown_in_flight = True
                self._closing = True
                self._accepting_submissions = False
                return True
            if not self._ready or loop.is_closed():
                return False
            self._shutdown_in_flight = True
            self._closing = True
            self._accepting_submissions = False
            try:
                loop.call_soon_threadsafe(queue.put_nowait, command)
            except RuntimeError:
                self._shutdown_in_flight = False
                return False
            return True

    def run(self) -> None:
        """Consume every exception at the final synchronous QThread boundary."""

        self._outcome_emitted = False
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            self._run_owned_runtime(loop)
        except BaseException as error:
            # PySide calls this Python override from a native QThread boundary.
            # Even a secondary cleanup or signal failure must not propagate back
            # into Qt, which would otherwise print an override traceback.
            with suppress(BaseException):
                self._recover_final_boundary(error, loop)

    def _recover_final_boundary(
        self,
        error: BaseException,
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        with suppress(BaseException):
            self._stop_accepting()
        if loop is not None:
            with suppress(BaseException):
                if not loop.is_closed():
                    self._finalize_event_loop(loop)
        if self._outcome_emitted:
            return
        try:
            outcome = (
                self._cancelled_exit_outcome()
                if isinstance(error, asyncio.CancelledError)
                else _ThreadExitOutcome(
                    command_id=(
                        ""
                        if self._active_command is None
                        else self._active_command.command_id
                    ),
                    success=False,
                    safe_code="runtime_thread_boundary_failed",
                    safe_message=(
                        "The runtime thread stopped at its safety boundary."
                    ),
                )
            )
        except BaseException:
            outcome = _ThreadExitOutcome(
                command_id="",
                success=False,
                safe_code="runtime_thread_boundary_failed",
                safe_message="The runtime thread stopped at its safety boundary.",
            )
        self._emit_shutdown_outcome_safely(outcome)

    def _run_owned_runtime(
        self,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Create, run, drain, and close the sole runtime event loop."""

        asyncio.set_event_loop(loop)
        self._runtime_thread_id = threading.get_ident()
        queue: asyncio.Queue[RuntimeThreadCommand] = asyncio.Queue()
        controller_ref: list[RuntimeSessionController] = []

        def event_sink(event: RuntimeEvent) -> None:
            self.runtime_event_emitted.emit(event)
            if controller_ref:
                self.snapshot_emitted.emit(controller_ref[0].snapshot())

        exit_outcome = _ThreadExitOutcome(
            command_id="",
            success=False,
            safe_code="runtime_bootstrap_failed",
            safe_message="The runtime thread failed to start safely.",
        )
        controller: RuntimeSessionController | None = None
        try:
            controller = self._controller_factory(
                event_sink,
                threading.get_ident(),
            )
            self._autostart_service = self._autostart_service_factory()
            controller_ref.append(controller)
            with self._guard:
                self._loop = loop
                self._queue = queue
                startup_shutdown = self._startup_shutdown
                self._startup_shutdown = None
                self._ready = True
                if startup_shutdown is None and not self._closing:
                    self._accepting_submissions = True
            exit_outcome = _ThreadExitOutcome(
                command_id="",
                success=False,
                safe_code="runtime_thread_failed",
                safe_message="The runtime thread stopped unexpectedly.",
            )
            if startup_shutdown is None:
                self.worker_ready.emit(controller.snapshot())
                exit_outcome = loop.run_until_complete(
                    self._dispatch_commands(queue, controller)
                )
            else:
                self._active_command = startup_shutdown
                result = loop.run_until_complete(
                    self._execute_command_safely(
                        startup_shutdown,
                        controller,
                    )
                )
                self._active_command = None
                self.snapshot_emitted.emit(controller.snapshot())
                if result.success:
                    exit_outcome = _ThreadExitOutcome(
                        command_id=startup_shutdown.command_id,
                        success=True,
                        safe_code=result.safe_code,
                        safe_message=result.safe_message,
                    )
                else:
                    self.command_result_emitted.emit(
                        startup_shutdown.command_id,
                        False,
                        result.safe_code,
                        result.safe_message,
                    )
                    self._allow_shutdown_retry()
                    exit_outcome = loop.run_until_complete(
                        self._dispatch_commands(queue, controller)
                    )
        except asyncio.CancelledError:
            exit_outcome = self._cancelled_exit_outcome()
            self._attempt_controller_cleanup(loop, controller)
        except BaseException:
            self._attempt_controller_cleanup(loop, controller)
        finally:
            self._stop_accepting()
            cleanup_failure = self._finalize_event_loop(loop)
            if cleanup_failure is not None and exit_outcome.success:
                exit_outcome = _ThreadExitOutcome(
                    command_id=exit_outcome.command_id,
                    success=False,
                    safe_code=cleanup_failure.safe_code,
                    safe_message=cleanup_failure.safe_message,
                )
            self._emit_shutdown_outcome_safely(exit_outcome)

    async def _dispatch_commands(
        self,
        queue: asyncio.Queue[RuntimeThreadCommand],
        controller: RuntimeSessionController,
    ) -> _ThreadExitOutcome:
        while True:
            command = await queue.get()
            self._active_command = command
            try:
                result = await self._execute_command_safely(
                    command,
                    controller,
                )
            finally:
                command.clear_sensitive()
            self.snapshot_emitted.emit(controller.snapshot())
            if command.type is RuntimeThreadCommandType.SHUTDOWN:
                if result.success:
                    self._active_command = None
                    self._stop_accepting()
                    return _ThreadExitOutcome(
                        command_id=command.command_id,
                        success=True,
                        safe_code=result.safe_code,
                        safe_message=result.safe_message,
                    )
                self.command_result_emitted.emit(
                    command.command_id,
                    False,
                    result.safe_code,
                    result.safe_message,
                )
                self._allow_shutdown_retry()
                self._active_command = None
                continue
            self.command_result_emitted.emit(
                command.command_id,
                result.success,
                result.safe_code,
                result.safe_message,
            )
            self._active_command = None

    async def _execute_command_safely(
        self,
        command: RuntimeThreadCommand,
        controller: RuntimeSessionController,
    ) -> RuntimeCommandResult:
        try:
            return await self._execute_command(command, controller)
        except asyncio.CancelledError:
            raise
        except ProviderSettingsServiceError as error:
            return RuntimeCommandResult.failure(
                error.safe_code,
                error.safe_message,
            )
        except Exception:
            return RuntimeCommandResult.failure(
                "runtime_command_failed",
                "The runtime command failed safely.",
            )

    async def _execute_command(
        self,
        command: RuntimeThreadCommand,
        controller: RuntimeSessionController,
    ) -> RuntimeCommandResult:
        if command.type is RuntimeThreadCommandType.ACTIVATE_PROFILE:
            if command.options is None:
                return RuntimeCommandResult.failure(
                    "invalid_command",
                    "Provider activation options are required.",
                )
            try:
                profile_id = ProfileId(command.profile_id)
            except (TypeError, ValueError):
                return RuntimeCommandResult.failure(
                    "invalid_command",
                    "The Provider profile identifier is invalid.",
                )
            return await controller.activate_profile(
                profile_id,
                command.options,
                command.turn_handling,
            )
        if command.type is RuntimeThreadCommandType.SEND_MESSAGE:
            return await controller.start_turn(
                content=command.content,
                session_id=command.session_id,
            )
        if command.type is RuntimeThreadCommandType.CANCEL_ACTIVE_TURN:
            return await controller.cancel_active_turn()
        if command.type is RuntimeThreadCommandType.REQUEST_SNAPSHOT:
            return RuntimeCommandResult.ok()
        if command.type is RuntimeThreadCommandType.REQUEST_PROVIDER_SETTINGS:
            return self._publish_provider_settings(command, controller)
        if command.type is RuntimeThreadCommandType.CREATE_PROVIDER_PROFILE:
            settings = self._require_provider_settings(controller)
            provider_id = ProviderId(command.provider_id)
            credential_id = (
                None
                if not command.credential_id
                else CredentialId(command.credential_id)
            )
            settings.create_settings_profile(
                provider_id=provider_id,
                display_name=command.display_name,
                model=command.model,
                credential_id=credential_id,
            )
            return self._publish_provider_settings(command, controller)
        if command.type is RuntimeThreadCommandType.UPDATE_PROVIDER_PROFILE:
            settings = self._require_provider_settings(controller)
            credential_id = (
                None
                if not command.credential_id
                else CredentialId(command.credential_id)
            )
            settings.update_settings_profile(
                ProfileId(command.profile_id),
                display_name=command.display_name,
                model=command.model,
                credential_id=credential_id,
            )
            return self._publish_provider_settings(command, controller)
        if command.type is RuntimeThreadCommandType.DELETE_PROVIDER_PROFILE:
            settings = self._require_provider_settings(controller)
            settings.delete_settings_profile(ProfileId(command.profile_id))
            return self._publish_provider_settings(command, controller)
        if command.type is RuntimeThreadCommandType.SAVE_PROVIDER_CREDENTIAL:
            settings = self._require_provider_settings(controller)
            settings.save_credential(
                CredentialId(command.credential_id),
                command.secret,
            )
            return self._publish_provider_settings(command, controller)
        if command.type is RuntimeThreadCommandType.DELETE_PROVIDER_CREDENTIAL:
            settings = self._require_provider_settings(controller)
            settings.delete_credential(CredentialId(command.credential_id))
            return self._publish_provider_settings(command, controller)
        if command.type is RuntimeThreadCommandType.REQUEST_AUTOSTART:
            service = self._require_autostart_service()
            snapshot = service.query()
            self.autostart_state_emitted.emit(command.command_id, snapshot)
            return RuntimeCommandResult.ok()
        if command.type is RuntimeThreadCommandType.SET_AUTOSTART:
            service = self._require_autostart_service()
            result = service.set_enabled(command.enabled)
            self.autostart_state_emitted.emit(
                command.command_id,
                result.snapshot,
            )
            if result.success:
                return RuntimeCommandResult.ok()
            return RuntimeCommandResult.failure(
                result.safe_code,
                result.safe_message,
            )
        if command.type is RuntimeThreadCommandType.SHUTDOWN:
            return await controller.shutdown(
                cancel_active=command.cancel_active
            )
        return RuntimeCommandResult.failure(
            "invalid_command",
            "The runtime command is not supported.",
        )

    def _require_autostart_service(self) -> AutostartService:
        service = self._autostart_service
        if service is None:
            raise RuntimeError("The autostart service is unavailable.")
        return service

    @staticmethod
    def _require_provider_settings(
        controller: RuntimeSessionController,
    ) -> ProviderSettingsService:
        settings = controller.provider_settings_service
        if settings is None:
            raise ProviderSettingsServiceError(
                "provider_settings_unavailable",
                "Provider settings are unavailable in this runtime.",
            )
        return settings

    def _publish_provider_settings(
        self,
        command: RuntimeThreadCommand,
        controller: RuntimeSessionController,
    ) -> RuntimeCommandResult:
        settings = self._require_provider_settings(controller)
        runtime = controller.snapshot()
        snapshot = settings.settings_snapshot(
            runtime_state=runtime.runtime_state,
            active_turn=runtime.active_turn_id is not None,
        )
        self.provider_settings_emitted.emit(command.command_id, snapshot)
        return RuntimeCommandResult.ok()

    @staticmethod
    async def _cancel_remaining_tasks() -> int:
        current = asyncio.current_task()
        remaining = [
            task
            for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        return len(
            [
                task
                for task in asyncio.all_tasks()
                if task is not current and not task.done()
            ]
        )

    def _stop_accepting(self) -> None:
        with self._guard:
            self._ready = False
            self._accepting_submissions = False
            self._closing = True
            self._shutdown_in_flight = True

    def _allow_shutdown_retry(self) -> None:
        with self._guard:
            self._shutdown_in_flight = False
            self._closing = True
            self._accepting_submissions = False

    def _cancelled_exit_outcome(self) -> _ThreadExitOutcome:
        command = self._active_command
        if command is None:
            return _ThreadExitOutcome(
                command_id="",
                success=False,
                safe_code="runtime_thread_cancelled",
                safe_message="The runtime thread was cancelled safely.",
            )
        if command.type is RuntimeThreadCommandType.SHUTDOWN:
            return _ThreadExitOutcome(
                command_id=command.command_id,
                success=False,
                safe_code="runtime_shutdown_cancelled",
                safe_message="Runtime shutdown was cancelled safely.",
            )
        return _ThreadExitOutcome(
            command_id=command.command_id,
            success=False,
            safe_code="runtime_command_cancelled",
            safe_message="The runtime command was cancelled safely.",
        )

    def _emit_shutdown_outcome_safely(
        self,
        outcome: _ThreadExitOutcome,
    ) -> None:
        try:
            self.shutdown_outcome_emitted.emit(
                outcome.command_id,
                outcome.success,
                outcome.safe_code,
                outcome.safe_message,
            )
        except BaseException:
            pass
        finally:
            self._outcome_emitted = True
            self._active_command = None

    @staticmethod
    def _attempt_controller_cleanup(
        loop: asyncio.AbstractEventLoop,
        controller: RuntimeSessionController | None,
    ) -> RuntimeCommandResult | None:
        if controller is None or controller.state is RuntimeState.CLOSED:
            return None
        try:
            return loop.run_until_complete(
                controller.shutdown(cancel_active=True)
            )
        except asyncio.CancelledError:
            return RuntimeCommandResult.failure(
                "runtime_shutdown_cancelled",
                "Runtime shutdown was cancelled safely.",
            )
        except BaseException:
            return RuntimeCommandResult.failure(
                "runtime_thread_cleanup_failed",
                "The runtime thread could not clean up safely.",
            )

    def _finalize_event_loop(
        self,
        loop: asyncio.AbstractEventLoop,
    ) -> RuntimeCommandResult | None:
        failure: RuntimeCommandResult | None = None
        try:
            loop.run_until_complete(self._cancel_remaining_tasks())
        except asyncio.CancelledError:
            failure = RuntimeCommandResult.failure(
                "runtime_task_cleanup_cancelled",
                "Runtime task cleanup was cancelled.",
            )
        except BaseException:
            failure = RuntimeCommandResult.failure(
                "runtime_task_cleanup_failed",
                "The runtime could not cancel asynchronous work safely.",
            )

        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except asyncio.CancelledError:
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_asyncgen_cleanup_cancelled",
                    "Runtime asynchronous-generator cleanup was cancelled.",
                )
        except BaseException:
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_asyncgen_cleanup_failed",
                    "The runtime could not close asynchronous generators safely.",
                )

        try:
            loop.run_until_complete(loop.shutdown_default_executor())
        except asyncio.CancelledError:
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_executor_cleanup_cancelled",
                    "Runtime executor cleanup was cancelled.",
                )
        except BaseException:
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_executor_cleanup_failed",
                    "The runtime could not close its executor safely.",
                )

        try:
            self._pending_task_count_at_close = len(
                [task for task in asyncio.all_tasks(loop) if not task.done()]
            )
        except BaseException:
            self._pending_task_count_at_close = None
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_task_cleanup_failed",
                    "The runtime could not inspect pending tasks safely.",
                )
        if self._pending_task_count_at_close and failure is None:
            failure = RuntimeCommandResult.failure(
                "runtime_task_cleanup_failed",
                "The runtime left asynchronous work pending.",
            )

        with self._guard:
            self._ready = False
            self._accepting_submissions = False
            self._queue = None
            self._loop = None
            self._startup_shutdown = None
        try:
            asyncio.set_event_loop(None)
        except BaseException:
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_loop_detach_failed",
                    "The runtime event loop could not be detached safely.",
                )
        try:
            loop.close()
        except BaseException:
            if failure is None:
                failure = RuntimeCommandResult.failure(
                    "runtime_loop_close_failed",
                    "The runtime event loop could not close safely.",
                )
        return failure
