from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.autostart_service import (
    REGISTRY_STRING_VALUE_TYPE,
    AutostartService,
    AutostartStatus,
    AutostartStoredValue,
)
from sjtuclaw.application.startup_mode import parse_startup_mode
from sjtuclaw.bootstrap.qt_runtime import ProductionQtRuntimeCompositionRoot
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.models import CredentialId
from sjtuclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from sjtuclaw.presentation.qt.main_window import MainWindow
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


@pytest.fixture
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app


def _run_until(
    predicate: Callable[[], bool],
    *,
    timeout_ms: int = 5_000,
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


class _FakeBackend:
    def __init__(self) -> None:
        self.value: AutostartStoredValue | None = None
        self.read_count = 0
        self.write_count = 0
        self.delete_count = 0
        self.fail_write = False
        self.fail_delete = False
        self.fail_read = False
        self.thread_ids: list[int] = []
        self.write_entered = threading.Event()
        self.write_gate: threading.Event | None = None
        self.delete_entered = threading.Event()
        self.delete_gate: threading.Event | None = None
        self.read_entered = threading.Event()
        self.read_gate: threading.Event | None = None

    def read_value(self) -> AutostartStoredValue | None:
        self.thread_ids.append(threading.get_ident())
        self.read_entered.set()
        if self.read_gate is not None and not self.read_gate.wait(5):
            raise RuntimeError("offline read gate timed out")
        if self.fail_read:
            raise OSError("unsafe-autostart-value-never-display")
        self.read_count += 1
        return self.value

    def write_value(self, command: str) -> None:
        self.thread_ids.append(threading.get_ident())
        self.write_entered.set()
        if self.write_gate is not None and not self.write_gate.wait(5):
            raise RuntimeError("offline write gate timed out")
        if self.fail_write:
            raise OSError("unsafe-autostart-value-never-display")
        self.write_count += 1
        self.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            command,
        )

    def delete_value(self) -> None:
        self.thread_ids.append(threading.get_ident())
        self.delete_entered.set()
        if self.delete_gate is not None and not self.delete_gate.wait(5):
            raise RuntimeError("offline delete gate timed out")
        if self.fail_delete:
            raise OSError("unsafe-autostart-value-never-display")
        self.delete_count += 1
        self.value = None


class _CountingSecretStore(InMemorySecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.access_count = 0

    def has_secret(self, credential_id: CredentialId) -> bool:
        self.access_count += 1
        return super().has_secret(credential_id)

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        self.access_count += 1
        return super().get_secret(credential_id)

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        self.access_count += 1
        super().set_secret(credential_id, value)

    def delete_secret(self, credential_id: CredentialId) -> None:
        self.access_count += 1
        super().delete_secret(credential_id)


class _PetCommands:
    pet_visible = True
    pet_paused = False
    pet_always_on_top = True
    pet_closing = False

    def toggle_pet_visibility(self) -> None:
        self.pet_visible = not self.pet_visible

    def open_agent_window(self) -> None:
        pass

    def toggle_paused(self) -> None:
        self.pet_paused = not self.pet_paused

    def set_always_on_top(self, enabled: bool) -> None:
        self.pet_always_on_top = enabled

    def request_safe_exit(self) -> None:
        self.pet_closing = True


class _FakeTrayView:
    def __init__(self, callbacks: TrayCallbacks) -> None:
        self.callbacks = callbacks
        self.states: list[PetTrayState] = []
        self.closed = False

    def show(self) -> None:
        pass

    def update_state(self, state: PetTrayState) -> None:
        self.states.append(state)

    def close(self) -> None:
        self.closed = True


class _TrayFactory:
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


def _create_bridge(
    tmp_path: Path,
    backend: _FakeBackend,
    *,
    expected_status: AutostartStatus = AutostartStatus.DISABLED,
    platform_supported: bool = True,
    packaged_runtime: bool = True,
) -> tuple[QtRuntimeBridge, AutostartUiController]:
    executable = tmp_path / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "profiles.json",
            secret_store_factory=InMemorySecretStore,
        ),
        autostart_service_factory=lambda: AutostartService(
            backend,
            lambda: executable,
            platform_supported=platform_supported,
            packaged_runtime_probe=lambda: packaged_runtime,
        ),
    )
    controller = AutostartUiController(bridge, bridge)
    ready_spy = QSignalSpy(bridge.runtime_ready)
    bridge.start_runtime()
    assert _run_until(lambda: ready_spy.count() == 1)
    assert _run_until(
        lambda: controller.snapshot.status is expected_status
    )
    return bridge, controller


def _shutdown(bridge: QtRuntimeBridge) -> None:
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    bridge.shutdown(cancel_active=True)
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _run_until(lambda: not bridge.runtime_thread.isRunning())
    assert bridge.runtime_thread.pending_task_count_at_close == 0


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


def _autostart_checkbox_rect_in_viewport(
    dialog: ProviderSettingsDialog,
) -> QRect:
    checkbox = dialog.autostart_checkbox
    viewport = dialog.general_scroll_area.viewport()
    return QRect(
        checkbox.mapTo(viewport, QPoint(0, 0)),
        checkbox.size(),
    )


@pytest.mark.parametrize(
    "status",
    [
        AutostartStatus.DISABLED,
        AutostartStatus.ENABLED,
        AutostartStatus.UNAVAILABLE,
        AutostartStatus.INVALID_EXECUTABLE,
        AutostartStatus.OCCUPIED,
        AutostartStatus.OWNERSHIP_LOST,
        AutostartStatus.ERROR,
    ],
)
def test_dialog_renders_every_autostart_status_with_safe_interaction_state(
    qt_application: QApplication,
    tmp_path: Path,
    status: AutostartStatus,
) -> None:
    backend = _FakeBackend()
    executable = (tmp_path / "SJTUClaw.exe").resolve()
    if status is AutostartStatus.ENABLED:
        backend.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            f'"{executable}" --startup',
        )
    elif status in {
        AutostartStatus.OCCUPIED,
        AutostartStatus.OWNERSHIP_LOST,
    }:
        backend.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            '"C:\\Other\\other.exe" --startup',
        )
    elif status is AutostartStatus.ERROR:
        backend.fail_read = True
    initial_status = (
        AutostartStatus.ENABLED
        if status is AutostartStatus.OWNERSHIP_LOST
        else status
    )
    if status is AutostartStatus.OWNERSHIP_LOST:
        backend.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            f'"{executable}" --startup',
        )
    bridge, controller = _create_bridge(
        tmp_path,
        backend,
        expected_status=initial_status,
        platform_supported=status is not AutostartStatus.UNAVAILABLE,
        packaged_runtime=status is not AutostartStatus.INVALID_EXECUTABLE,
    )
    if status is AutostartStatus.OWNERSHIP_LOST:
        backend.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            '"C:\\Other\\other.exe" --startup',
        )
        controller.refresh()
        assert _run_until(
            lambda: (
                controller.snapshot.status
                is AutostartStatus.OWNERSHIP_LOST
            )
        )
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    dialog.show()
    dialog.settings_tabs.setCurrentWidget(dialog.general_page)
    qt_application.processEvents()

    assert controller.snapshot.status is status
    assert dialog.autostart_checkbox.isVisible()
    assert dialog.autostart_checkbox.isVisibleTo(dialog)
    assert dialog.autostart_checkbox.isChecked() is (
        status is AutostartStatus.ENABLED
    )
    assert dialog.autostart_checkbox.isEnabled() is (
        status
        in {
            AutostartStatus.DISABLED,
            AutostartStatus.ENABLED,
        }
    )
    assert dialog.autostart_status_label.text()
    assert "C:\\Other" not in dialog.autostart_status_label.text()

    _shutdown(bridge)
    dialog.close()


def test_general_page_checkbox_is_visible_keyboard_reachable_and_clickable(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    dialog.resize(560, 360)
    dialog.show()
    assert dialog.settings_tabs.currentWidget() is dialog.providers_page
    dialog.settings_tabs.setCurrentWidget(dialog.general_page)
    qt_application.processEvents()

    checkbox = dialog.autostart_checkbox
    viewport = dialog.general_scroll_area.viewport()
    checkbox_rect = _autostart_checkbox_rect_in_viewport(dialog)
    assert dialog.providers_scroll_area.widgetResizable()
    assert dialog.general_scroll_area.widgetResizable()
    assert checkbox.isVisible()
    assert checkbox.isVisibleTo(dialog)
    assert checkbox.isEnabled()
    assert not checkbox.geometry().isEmpty()
    assert viewport.rect().contains(checkbox_rect)

    dialog.settings_tabs.setFocus(Qt.FocusReason.OtherFocusReason)
    tab_focus_reached = False
    for _ in range(32):
        dialog.focusNextChild()
        if qt_application.focusWidget() is checkbox:
            tab_focus_reached = True
            break
    assert tab_focus_reached

    writes_before = backend.write_count
    QTest.mouseClick(
        checkbox,
        Qt.MouseButton.LeftButton,
        pos=checkbox.rect().center(),
    )
    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )
    assert backend.write_count == writes_before + 1

    _shutdown(bridge)
    dialog.close()


def test_long_safe_autostart_error_wraps_without_hiding_control(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    dialog.resize(520, 320)
    dialog.show()
    dialog.settings_tabs.setCurrentWidget(dialog.general_page)
    dialog.autostart_error_label.setText(
        "autostart_write_failed: The autostart setting could not be "
        "changed safely. " * 12
    )
    qt_application.processEvents()

    assert dialog.autostart_error_label.wordWrap()
    assert dialog.autostart_help_label.wordWrap()
    assert dialog.autostart_checkbox.isVisibleTo(dialog)
    assert dialog.general_scroll_area.horizontalScrollBar().maximum() == 0
    assert (
        dialog.autostart_error_label.width()
        <= dialog.general_scroll_area.viewport().width()
    )

    _shutdown(bridge)
    dialog.close()


@pytest.mark.parametrize("scale_factor", ["1", "1.25", "1.5", "2"])
def test_autostart_layout_probe_at_supported_scale_factors(
    tmp_path: Path,
    scale_factor: str,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    redirected = tmp_path / "process-environment"
    redirected.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_SCALE_FACTOR": scale_factor,
            "TEMP": str(redirected),
            "TMP": str(redirected),
            "TMPDIR": str(redirected),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(repository / "scripts" / "qt_autostart_layout_probe.py"),
        ],
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = completed.stdout + completed.stderr

    assert completed.returncode == 0, combined
    assert "qt_autostart_layout_probe=true" in combined
    assert "checkbox_visible=true" in combined
    assert "focus_reachable=true" in combined
    assert "set_autostart_count=1" in combined
    assert "pending_asyncio_tasks=0" in combined
    assert "real_registry_access_count=0" in combined
    assert "network_access_count=0" in combined
    assert "Traceback" not in combined


def test_three_ui_entries_share_one_runtime_owned_state(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    pet = PetWindow(autostart_controller=controller)
    tray_factory = _TrayFactory()
    tray = SystemTrayController(
        _PetCommands(),
        autostart_controller=controller,
        view_factory=tray_factory,
    )
    assert tray_factory.view is not None
    tray_view = tray_factory.view

    writes_before_show = backend.write_count
    deletes_before_show = backend.delete_count
    dialog.show()
    assert _run_until(lambda: backend.read_count >= 2)
    assert backend.write_count == writes_before_show
    assert backend.delete_count == deletes_before_show

    dialog.autostart_checkbox.click()
    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )
    pet_action = _pet_autostart_action(pet)
    assert dialog.autostart_checkbox.isChecked()
    assert tray_view.states[-1].autostart.enabled
    assert pet_action.isChecked()
    assert backend.write_count == 1
    assert backend.delete_count == 0

    assert tray_view.callbacks.set_autostart_enabled is not None
    tray_view.callbacks.set_autostart_enabled(False)
    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.DISABLED
        and not controller.busy
    )
    assert not dialog.autostart_checkbox.isChecked()
    assert not tray_view.states[-1].autostart.enabled
    assert not pet_action.isChecked()
    assert backend.write_count == 1
    assert backend.delete_count == 1

    pet_action.trigger()
    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )
    assert dialog.autostart_checkbox.isChecked()
    assert tray_view.states[-1].autostart.enabled
    assert pet_action.isChecked()
    assert backend.write_count == 2
    assert backend.delete_count == 1
    ui_visible = " ".join(
        (
            repr(controller.snapshot),
            repr(tray_view.states[-1]),
            dialog.autostart_status_label.text(),
            pet_action.toolTip(),
        )
    )
    assert str(tmp_path) not in ui_visible
    assert '"SJTUClaw.exe" --startup' not in ui_visible

    gui_thread_id = threading.get_ident()
    assert backend.thread_ids
    assert all(thread_id != gui_thread_id for thread_id in backend.thread_ids)
    _shutdown(bridge)
    assert backend.value is not None
    assert backend.delete_count == 1
    tray.complete_shutdown()
    pet.complete_safe_close()
    dialog.close()


def test_autostart_refresh_does_not_steal_current_dialog_focus(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    dialog.show()
    dialog.settings_tabs.setCurrentWidget(dialog.providers_page)
    dialog.display_name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    qt_application.processEvents()
    assert qt_application.focusWidget() is dialog.display_name_edit
    reads_before = backend.read_count

    command_id = controller.refresh()

    assert command_id is not None
    assert _run_until(lambda: not bridge.is_command_pending(command_id))
    assert backend.read_count == reads_before + 1
    assert qt_application.focusWidget() is dialog.display_name_edit
    assert backend.write_count == 0
    assert backend.delete_count == 0
    _shutdown(bridge)
    dialog.close()


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_failed_mutation_restores_last_confirmed_switch(
    qt_application: QApplication,
    tmp_path: Path,
    operation: str,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    failure_spy = QSignalSpy(controller.operation_failed)
    if operation == "delete":
        dialog.autostart_checkbox.click()
        assert _run_until(
            lambda: controller.snapshot.status is AutostartStatus.ENABLED
            and not controller.busy
        )
        backend.fail_delete = True
    else:
        backend.fail_write = True

    original = controller.snapshot
    dialog.autostart_checkbox.click()

    assert _run_until(lambda: failure_spy.count() == 1)
    assert _run_until(lambda: not controller.busy)
    assert controller.snapshot == original
    assert dialog.autostart_checkbox.isChecked() is original.enabled
    assert "unsafe-autostart-value-never-display" not in (
        dialog.autostart_error_label.text()
        + dialog.autostart_status_label.text()
        + repr(controller.snapshot)
    )
    _shutdown(bridge)
    dialog.close()


def test_occupied_and_ownership_lost_disable_all_mutation(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    backend.value = AutostartStoredValue(
        REGISTRY_STRING_VALUE_TYPE,
        '"C:\\Other\\other.exe" --startup',
    )
    bridge, controller = _create_bridge(
        tmp_path,
        backend,
        expected_status=AutostartStatus.OCCUPIED,
    )
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    assert controller.snapshot.status is AutostartStatus.OCCUPIED
    assert not dialog.autostart_checkbox.isEnabled()
    assert backend.write_count == 0
    assert backend.delete_count == 0
    _shutdown(bridge)
    dialog.close()


def test_external_change_after_enable_reports_ownership_lost(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    dialog.autostart_checkbox.click()
    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )
    backend.value = AutostartStoredValue(
        REGISTRY_STRING_VALUE_TYPE,
        '"C:\\Other\\other.exe" --startup',
    )

    controller.refresh()

    assert _run_until(
        lambda: (
            controller.snapshot.status
            is AutostartStatus.OWNERSHIP_LOST
        )
    )
    assert not dialog.autostart_checkbox.isEnabled()
    assert not dialog.autostart_checkbox.isChecked()
    assert backend.delete_count == 0
    _shutdown(bridge)
    dialog.close()


def test_runtime_shutdown_preserves_enabled_registration(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    controller.set_enabled(True)
    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )

    _shutdown(bridge)

    assert backend.value is not None
    assert backend.delete_count == 0


def test_closing_runtime_rejects_autostart_mutation_without_busy_leak(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)

    bridge.shutdown(cancel_active=True)
    command_id = controller.set_enabled(True)

    assert command_id is None
    assert controller.busy is False
    assert backend.write_count == 0
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _run_until(lambda: not bridge.runtime_thread.isRunning())


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_blocking_mutation_keeps_gui_responsive_and_shutdown_waits(
    qt_application: QApplication,
    tmp_path: Path,
    operation: str,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    if operation == "delete":
        controller.set_enabled(True)
        assert _run_until(
            lambda: controller.snapshot.status is AutostartStatus.ENABLED
            and not controller.busy
        )
        gate = threading.Event()
        backend.delete_gate = gate
        entered = backend.delete_entered
        command_id = controller.set_enabled(False)
    else:
        gate = threading.Event()
        backend.write_gate = gate
        entered = backend.write_entered
        command_id = controller.set_enabled(True)
    assert command_id is not None
    assert _run_until(entered.is_set)
    assert controller.busy
    assert controller.set_enabled(not controller.snapshot.enabled) is None

    gui_tick = threading.Event()
    QTimer.singleShot(0, gui_tick.set)
    assert _run_until(gui_tick.is_set)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    bridge.shutdown(cancel_active=True)
    assert shutdown_spy.count() == 0

    gate.set()

    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _run_until(lambda: not bridge.runtime_thread.isRunning())
    assert bridge.runtime_thread.pending_task_count_at_close == 0
    assert backend.write_count == 1
    assert backend.delete_count == (1 if operation == "delete" else 0)


def test_autostart_command_ids_have_one_terminal_result_each(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, controller = _create_bridge(tmp_path, backend)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)

    first = controller.refresh()
    second = controller.refresh()

    assert first is not None
    assert second is not None
    assert first != second
    assert _run_until(
        lambda: not bridge.is_command_pending(first)
        and not bridge.is_command_pending(second)
    )
    terminal_rows = [
        completed_spy.at(index)
        for index in range(completed_spy.count())
    ] + [
        failed_spy.at(index) for index in range(failed_spy.count())
    ]
    terminals = [
        str(arguments[0])
        for arguments in terminal_rows
        if str(arguments[0]) in {first, second}
    ]
    assert terminals.count(first) == 1
    assert terminals.count(second) == 1
    _shutdown(bridge)


def test_destroyed_controller_ignores_stale_runtime_result(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    backend = _FakeBackend()
    bridge, primary = _create_bridge(tmp_path, backend)
    del primary
    gate = threading.Event()
    backend.read_gate = gate
    backend.read_entered.clear()
    controller = AutostartUiController(bridge)
    destroyed_spy = QSignalSpy(controller.destroyed)

    command_id = controller.refresh()

    assert command_id is not None
    assert _run_until(backend.read_entered.is_set)
    controller.deleteLater()
    assert _run_until(lambda: destroyed_spy.count() == 1)
    gate.set()
    assert _run_until(lambda: not bridge.is_command_pending(command_id))
    _shutdown(bridge)


def test_startup_mode_keeps_agent_hidden_without_provider_or_secret_access(
    qt_application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    assert parse_startup_mode(["SJTUClaw.exe", "--startup"]) is True
    external_network_calls = 0
    original_connect = socket.socket.connect

    def guarded_connect(
        sock: socket.socket,
        address: object,
    ) -> None:
        nonlocal external_network_calls
        if isinstance(address, tuple) and address:
            host = str(address[0]).casefold()
            if host not in {"127.0.0.1", "::1", "localhost"}:
                external_network_calls += 1
                raise AssertionError(
                    "Startup mode must not access an external network."
                )
        original_connect(sock, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    backend = _FakeBackend()
    secret_store = _CountingSecretStore()
    executable = tmp_path / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "startup-profiles.json",
            secret_store_factory=lambda: secret_store,
        ),
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
    pet.show()

    assert _run_until(
        lambda: controller.snapshot.status is AutostartStatus.DISABLED
    )
    assert not main_window.isVisible()
    assert pet.isVisible()
    assert pet.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert pet.focusPolicy() is Qt.FocusPolicy.NoFocus
    assert secret_store.access_count == 0
    assert external_network_calls == 0
    assert backend.write_count == 0
    assert backend.delete_count == 0
    _shutdown(bridge)
    pet.complete_safe_close()
