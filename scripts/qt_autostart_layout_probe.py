"""Offline subprocess probe for the autostart settings control layout."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
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
from sjtuclaw.presentation.qt.provider_settings_dialog import (
    ProviderSettingsDialog,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


class _FakeAutostartBackend:
    def __init__(self) -> None:
        self.value: AutostartStoredValue | None = None
        self.read_count = 0
        self.write_count = 0
        self.delete_count = 0

    def read_value(self) -> AutostartStoredValue | None:
        self.read_count += 1
        return self.value

    def write_value(self, command: str) -> None:
        self.write_count += 1
        self.value = AutostartStoredValue(
            REGISTRY_STRING_VALUE_TYPE,
            command,
        )

    def delete_value(self) -> None:
        self.delete_count += 1
        self.value = None


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


def _run_probe(root: Path) -> int:
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
    dialog = ProviderSettingsDialog(
        bridge,
        autostart_controller=controller,
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    bridge.start_runtime()
    ready = _run_until(
        lambda: ready_spy.count() == 1
        and controller.snapshot.status is AutostartStatus.DISABLED
    )
    dialog.resize(560, 360)
    dialog.show()
    dialog.settings_tabs.setCurrentWidget(dialog.general_page)
    app.processEvents()

    checkbox = dialog.autostart_checkbox
    viewport = dialog.general_scroll_area.viewport()
    checkbox_rect = QRect(
        checkbox.mapTo(viewport, QPoint(0, 0)),
        checkbox.size(),
    )
    visible = (
        checkbox.isVisible()
        and checkbox.isVisibleTo(dialog)
        and viewport.rect().contains(checkbox_rect)
    )
    dialog.settings_tabs.setFocus(Qt.FocusReason.OtherFocusReason)
    focus_reachable = False
    for _ in range(32):
        dialog.focusNextChild()
        if app.focusWidget() is checkbox:
            focus_reachable = True
            break

    writes_before = backend.write_count
    QTest.mouseClick(
        checkbox,
        Qt.MouseButton.LeftButton,
        pos=checkbox.rect().center(),
    )
    enabled = _run_until(
        lambda: controller.snapshot.status is AutostartStatus.ENABLED
        and not controller.busy
    )
    checkbox_enabled_before_shutdown = checkbox.isEnabled()
    one_write = backend.write_count == writes_before + 1
    bridge.shutdown(cancel_active=True)
    shutdown = (
        _run_until(lambda: shutdown_spy.count() == 1)
        and _run_until(lambda: not bridge.runtime_thread.isRunning())
    )
    pending_tasks = bridge.runtime_thread.pending_task_count_at_close
    dialog.close()
    success = (
        ready
        and visible
        and checkbox_enabled_before_shutdown
        and focus_reachable
        and enabled
        and one_write
        and backend.delete_count == 0
        and shutdown
        and pending_tasks == 0
    )
    print(
        f"qt_autostart_layout_probe={str(success).lower()} "
        f"checkbox_visible={str(visible).lower()} "
        f"focus_reachable={str(focus_reachable).lower()} "
        f"set_autostart_count={backend.write_count} "
        f"delete_autostart_count={backend.delete_count} "
        f"pending_asyncio_tasks={pending_tasks} "
        "real_registry_access_count=0 network_access_count=0"
    )
    return 0 if success else 2


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    temporary_parent = repository / "build" / "qt-autostart-layout-probe"
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
                    "The autostart layout probe cannot use external network."
                )
        original_connect(sock, address)  # type: ignore[arg-type]

    with (
        patch.object(socket.socket, "connect", reject_network),
        tempfile.TemporaryDirectory(
            prefix="run-",
            dir=temporary_parent,
        ) as directory,
    ):
        result = _run_probe(Path(directory))
    if external_network_calls:
        return 2
    return result


if __name__ == "__main__":
    sys.exit(main())
