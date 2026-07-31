"""Fully offline smoke for the shared Windows autostart UI boundary."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QEventLoop,
    QObject,
    QPoint,
    QRect,
    QSignalBlocker,
    QTimer,
)
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.autostart_service import (
    REGISTRY_STRING_VALUE_TYPE,
    AutostartService,
    AutostartStatus,
    AutostartStoredValue,
)
from sjtuclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from sjtuclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.provider_settings_dialog import (
    ProviderSettingsDialog,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from sjtuclaw.presentation.qt.system_tray import (
    PetTrayState,
    SystemTrayController,
    TrayCallbacks,
)


class _FakeAutostartBackend:
    def __init__(self) -> None:
        self.value: AutostartStoredValue | None = None
        self.read_count = 0
        self.write_count = 0
        self.delete_count = 0
        self.fail_write = False

    def read_value(self) -> AutostartStoredValue | None:
        self.read_count += 1
        return self.value

    def write_value(self, command: str) -> None:
        if self.fail_write:
            raise OSError("offline fake write failure")
        self.write_count += 1
        self.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            command,
        )

    def delete_value(self) -> None:
        self.delete_count += 1
        self.value = None


class _FakeTrayView:
    def __init__(self, callbacks: TrayCallbacks) -> None:
        self.callbacks = callbacks
        self.states: list[PetTrayState] = []
        self.closed = False
        self.autostart_action = QAction("Start with Windows")
        self.autostart_action.setObjectName(
            "trayAutostartEnabledAction"
        )
        self.autostart_action.setCheckable(True)
        if callbacks.set_autostart_enabled is not None:
            self.autostart_action.toggled.connect(
                callbacks.set_autostart_enabled
            )

    def show(self) -> None:
        pass

    def is_visible(self) -> bool:
        return not self.closed

    def update_state(self, state: PetTrayState) -> None:
        self.states.append(state)
        blocker = QSignalBlocker(self.autostart_action)
        self.autostart_action.setChecked(state.autostart.enabled)
        del blocker
        self.autostart_action.setEnabled(
            not state.closing
            and not state.autostart_busy
            and state.autostart.user_toggle_allowed
        )

    def close(self) -> None:
        self.closed = True


class _FakeTrayFactory:
    def __init__(self) -> None:
        self.view: _FakeTrayView | None = None

    def __call__(
        self,
        callbacks: TrayCallbacks,
        parent: QObject,
    ) -> _FakeTrayView:
        del parent
        self.view = _FakeTrayView(callbacks)
        return self.view


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


def _pet_autostart_action(pet: PetWindow) -> QAction:
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        QPoint(5, 5),
        QPoint(5, 5),
    )
    pet.contextMenuEvent(event)
    return next(
        action
        for action in pet.findChildren(QAction)
        if action.objectName() == "petAutostartEnabledAction"
    )


def _run_smoke(root: Path) -> int:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = _FakeAutostartBackend()
    executable = root / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(root / "profiles.json"),
        autostart_service_factory=lambda: AutostartService(
            backend,
            lambda: executable,
            platform_supported=True,
            packaged_runtime_probe=lambda: True,
        ),
    )
    controller = AutostartUiController(bridge, bridge)
    main_window = MainWindow(
        bridge,
        hide_on_close=True,
        autostart_controller=controller,
    )
    pet = PetWindow(autostart_controller=controller)
    coordinator = PetApplicationCoordinator(bridge, main_window, pet)
    tray_factory = _FakeTrayFactory()
    tray = SystemTrayController(
        coordinator,
        autostart_controller=controller,
        view_factory=tray_factory,
    )
    coordinator.attach_system_tray(tray)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    failure_spy = QSignalSpy(controller.operation_failed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    bridge.start_runtime()
    initial_disabled = _run_until(
        lambda: ready_spy.count() == 1
        and controller.snapshot.status is AutostartStatus.DISABLED
    )
    view = tray_factory.view
    if view is None:
        return 2
    pet_action = _pet_autostart_action(pet)
    dialog.resize(560, 360)
    dialog.show()
    dialog.settings_tabs.setCurrentWidget(dialog.general_page)
    app.processEvents()
    viewport = dialog.general_scroll_area.viewport()
    checkbox = dialog.autostart_checkbox
    checkbox_rect = QRect(
        checkbox.mapTo(viewport, QPoint(0, 0)),
        checkbox.size(),
    )
    settings_control_visible = (
        checkbox.isVisible()
        and checkbox.isVisibleTo(dialog)
        and checkbox.isEnabled()
        and viewport.rect().contains(checkbox_rect)
    )
    tray_action_available = (
        view.autostart_action.objectName()
        == "trayAutostartEnabledAction"
        and view.autostart_action.isVisible()
        and view.autostart_action.isEnabled()
    )
    pet_action_available = (
        pet_action.objectName() == "petAutostartEnabledAction"
        and pet_action.isVisible()
        and pet_action.isEnabled()
    )

    dialog.autostart_checkbox.click()
    settings_enabled = _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )
    three_entry_enable_sync = (
        settings_enabled
        and dialog.autostart_checkbox.isChecked()
        and view.states[-1].autostart.enabled
        and pet_action.isChecked()
    )

    if view.callbacks.set_autostart_enabled is not None:
        view.callbacks.set_autostart_enabled(False)
    tray_disabled = _run_until(
        lambda: controller.snapshot.status is AutostartStatus.DISABLED
        and not controller.busy
    )
    three_entry_disable_sync = (
        tray_disabled
        and not dialog.autostart_checkbox.isChecked()
        and not view.states[-1].autostart.enabled
        and not pet_action.isChecked()
    )

    backend.fail_write = True
    pet_action.trigger()
    failure_rolled_back = (
        _run_until(lambda: failure_spy.count() == 1)
        and not controller.busy
        and controller.snapshot.status is AutostartStatus.DISABLED
        and not dialog.autostart_checkbox.isChecked()
        and not view.states[-1].autostart.enabled
        and not pet_action.isChecked()
    )
    backend.fail_write = False
    pet_action.trigger()
    pet_enabled = _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )

    coordinator.request_safe_exit()
    shutdown_complete = (
        _run_until(lambda: shutdown_spy.count() == 1)
        and _run_until(lambda: not bridge.runtime_thread.isRunning())
    )
    registration_preserved = backend.value is not None
    pending_tasks = bridge.runtime_thread.pending_task_count_at_close
    tray.complete_shutdown()
    pet.complete_safe_close()
    dialog.close()
    main_window.close()
    timer_stopped = not pet.physics_timer.isActive()
    success = (
        initial_disabled
        and settings_control_visible
        and tray_action_available
        and pet_action_available
        and three_entry_enable_sync
        and three_entry_disable_sync
        and failure_rolled_back
        and pet_enabled
        and shutdown_complete
        and registration_preserved
        and pending_tasks == 0
        and timer_stopped
    )
    print(
        f"qt_autostart_smoke={success} "
        f"initial_disabled={initial_disabled} "
        f"settings_control_visible={settings_control_visible} "
        f"tray_action_available={tray_action_available} "
        f"pet_action_available={pet_action_available} "
        f"three_entry_enable_sync={three_entry_enable_sync} "
        f"three_entry_disable_sync={three_entry_disable_sync} "
        f"failure_rolled_back={failure_rolled_back} "
        f"registration_preserved={registration_preserved} "
        f"runtime_thread_closed={not bridge.runtime_thread.isRunning()} "
        f"pending_asyncio_tasks={pending_tasks} "
        f"timer_active={pet.physics_timer.isActive()} "
        f"fake_registry_reads={backend.read_count} "
        f"fake_registry_writes={backend.write_count} "
        f"fake_registry_deletes={backend.delete_count} "
        "real_registry_access_count=0 network_access_count=0"
    )
    return 0 if success else 2


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    temporary_parent = repository / "build" / "qt-autostart-smoke"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    external_network_calls = 0
    original_connect = socket.socket.connect

    def reject_network(sock: socket.socket, address: object) -> None:
        nonlocal external_network_calls
        if isinstance(address, tuple) and address:
            host = str(address[0]).casefold()
            if host not in {"127.0.0.1", "::1", "localhost"}:
                external_network_calls += 1
                raise AssertionError(
                    "The offline autostart smoke cannot use external network."
                )
        original_connect(sock, address)  # type: ignore[arg-type]

    with (
        patch.object(socket.socket, "connect", reject_network),
        tempfile.TemporaryDirectory(
            prefix="run-",
            dir=temporary_parent,
        ) as directory,
    ):
        result = _run_smoke(Path(directory))
    if external_network_calls:
        return 2
    return result


if __name__ == "__main__":
    sys.exit(main())
