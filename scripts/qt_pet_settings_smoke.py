"""Two-lifecycle offline smoke for desktop-pet settings persistence."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QEventLoop,
    QMessageLogContext,
    QTimer,
    QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from sjtuclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from sjtuclaw.infrastructure.config.json_pet_settings_repository import (
    JsonPetSettingsRepository,
)
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from sjtuclaw.presentation.qt.pet_settings_controller import (
    PetSettingsController,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge

_KNOWN_PLATFORM_WARNING_PARTS = (
    "QFontDatabase: Cannot find font directory",
    "This plugin does not support raise()",
    "This plugin does not support propagateSizeHints()",
)


class _QtWarningAudit:
    def __init__(self) -> None:
        self.unexpected: list[str] = []

    def handle(
        self,
        message_type: QtMsgType,
        context: QMessageLogContext,
        message: str,
    ) -> None:
        del context
        if (
            message_type is QtMsgType.QtWarningMsg
            and any(
                part in message for part in _KNOWN_PLATFORM_WARNING_PARTS
            )
        ):
            return
        if message_type in {
            QtMsgType.QtWarningMsg,
            QtMsgType.QtCriticalMsg,
            QtMsgType.QtFatalMsg,
        }:
            self.unexpected.append(message)
            print(message, file=sys.stderr)


def _run_until(
    predicate: Callable[[], bool],
    *,
    timeout_ms: int = 10_000,
) -> bool:
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)

    def check() -> None:
        if predicate():
            loop.quit()

    poll.timeout.connect(check)
    timeout.timeout.connect(loop.quit)
    poll.start(1)
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    return predicate()


def _run_lifecycle(
    profile_path: Path,
    settings_path: Path,
    *,
    restore_only: bool,
) -> tuple[
    PetSettingsController,
    tuple[int, int, bool],
    QtRuntimeBridge,
    bool,
    bool,
]:
    bridge = QtRuntimeBridge(FakeQtRuntimeCompositionRoot(profile_path))
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    main_window = MainWindow(bridge, hide_on_close=True)
    pet = PetWindow()
    controller = PetSettingsController(
        JsonPetSettingsRepository(settings_path)
    )
    coordinator = PetApplicationCoordinator(
        bridge,
        main_window,
        pet,
        settings_controller=controller,
    )
    quit_spy = QSignalSpy(coordinator.quit_requested)
    coordinator.restore_pet_settings()
    restored = pet.persisted_presentation_state()
    position_in_workspace = any(
        screen.availableGeometry().contains(pet.geometry())
        for screen in QApplication.screens()
    )
    if not restore_only:
        pet.restore_persisted_position(64, 72)
        pet.set_always_on_top(False)
    pet.show()
    ready = _run_until(lambda: ready_spy.count() == 1)
    pet.request_safe_exit()
    stopped = (
        _run_until(lambda: shutdown_spy.count() == 1)
        and _run_until(lambda: quit_spy.count() == 1)
        and not bridge.runtime_thread.isRunning()
        and not pet.physics_timer.isActive()
    )
    main_window.close()
    return (
        controller,
        restored,
        bridge,
        ready and stopped,
        position_in_workspace,
    )


def main(message_audit: _QtWarningAudit) -> int:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    app.setApplicationName("SJTUClawPetSettingsSmoke")
    app.setOrganizationName("SJTU")
    app.setQuitOnLastWindowClosed(False)

    with tempfile.TemporaryDirectory(
        prefix="sjtuclaw-pet-settings-"
    ) as temporary_directory:
        root = Path(temporary_directory)
        settings_path = root / "pet_settings.json"
        first, _, first_bridge, first_ok, _ = _run_lifecycle(
            root / "first-profiles.json",
            settings_path,
            restore_only=False,
        )
        (
            second,
            restored,
            second_bridge,
            second_ok,
            position_in_workspace,
        ) = _run_lifecycle(
            root / "second-profiles.json",
            settings_path,
            restore_only=True,
        )
        temporary_files = tuple(root.glob(".pet_settings.json.*.tmp"))
        persisted_document = JsonPetSettingsRepository(
            settings_path
        ).load()
        atomic_write = (
            persisted_document.settings is not None
            and persisted_document.safe_code == "none"
            and not temporary_files
        )
        threads_running = (
            first_bridge.runtime_thread.isRunning()
            or second_bridge.runtime_thread.isRunning()
        )
        first_pending = (
            first_bridge.runtime_thread.pending_task_count_at_close
        )
        second_pending = (
            second_bridge.runtime_thread.pending_task_count_at_close
        )
        pending_tasks = (
            -1
            if first_pending is None or second_pending is None
            else first_pending + second_pending
        )
        success = (
            first_ok
            and second_ok
            and first.save_count == 1
            and second.safe_code == "none"
            and second.load_count == 1
            and restored[:2] == (64, 72)
            and restored[2] is False
            and position_in_workspace
            and not threads_running
            and pending_tasks == 0
            and atomic_write
            and not message_audit.unexpected
        )
        failed_checks = []
        if message_audit.unexpected:
            failed_checks.append("unexpected_qt_warnings")
        print(
            f"qt_pet_settings_smoke={success} "
            "settings_schema_version=1 "
            f"first_save_count={first.save_count} "
            f"second_load_count={second.load_count} "
            f"position_restored={restored[:2] == (64, 72)} "
            f"position_in_workspace={position_in_workspace} "
            f"always_on_top_restored={restored[2] is False} "
            "secondary_settings_access_count=0 "
            f"atomic_write={atomic_write} "
            f"thread_running={threads_running} "
            f"pending_asyncio_tasks={pending_tasks} "
            "unexpected_qt_warnings="
            f"{len(message_audit.unexpected)} "
            f"failed_checks={','.join(failed_checks)}"
        )
        return 0 if success else 1


if __name__ == "__main__":
    message_audit = _QtWarningAudit()
    previous_handler = qInstallMessageHandler(message_audit.handle)
    try:
        exit_code = main(message_audit)
    finally:
        qInstallMessageHandler(previous_handler)
    raise SystemExit(exit_code)
