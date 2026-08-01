from __future__ import annotations

import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from sjtuclaw.application.autostart_operation_journal import (
    AutostartOperationOrigin,
)
from sjtuclaw.application.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from sjtuclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


@pytest.fixture
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app


class _FakeBridge(QObject):
    runtime_ready = Signal()
    runtime_closing = Signal()
    autostart_state_changed = Signal(str, object)
    command_completed = Signal(str)
    command_failed = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.accepting_commands = True
        self.pending: set[str] = set()
        self.submissions: list[tuple[str, bool | None, int]] = []

    def is_command_pending(self, command_id: str) -> bool:
        return command_id in self.pending

    def request_autostart(
        self,
        *,
        operation_id: str = "",
        origin: AutostartOperationOrigin = AutostartOperationOrigin.UNKNOWN,
        controller_revision: int = 0,
    ) -> str:
        del operation_id, origin
        command_id = f"query-{len(self.submissions) + 1}"
        self.pending.add(command_id)
        self.submissions.append((command_id, None, controller_revision))
        return command_id

    def set_autostart_enabled(
        self,
        enabled: bool,
        *,
        operation_id: str = "",
        origin: AutostartOperationOrigin = AutostartOperationOrigin.UNKNOWN,
        controller_revision: int = 0,
    ) -> str:
        del operation_id, origin
        command_id = f"mutation-{len(self.submissions) + 1}"
        self.pending.add(command_id)
        self.submissions.append((command_id, enabled, controller_revision))
        return command_id


def _controller() -> tuple[_FakeBridge, AutostartUiController]:
    bridge = _FakeBridge()
    controller = AutostartUiController(cast(QtRuntimeBridge, bridge))
    return bridge, controller


def _publish(
    bridge: _FakeBridge,
    command_id: str,
    status: AutostartStatus,
) -> None:
    bridge.autostart_state_changed.emit(
        command_id,
        AutostartSnapshot.for_status(status),
    )


def test_late_initial_query_cannot_roll_back_enable_completion(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge, controller = _controller()
    initial = controller.refresh(
        origin=AutostartOperationOrigin.STARTUP_QUERY
    )
    assert initial is not None
    _publish(bridge, initial, AutostartStatus.DISABLED)
    bridge.command_completed.emit(initial)

    stale_query = controller.refresh()
    assert stale_query is not None
    mutation = controller.set_enabled(
        True,
        origin=AutostartOperationOrigin.SETTINGS_CHECKBOX,
    )
    assert mutation is not None
    _publish(bridge, mutation, AutostartStatus.ENABLED)
    bridge.command_completed.emit(mutation)
    _publish(bridge, stale_query, AutostartStatus.DISABLED)
    bridge.command_completed.emit(stale_query)

    assert controller.snapshot.status is AutostartStatus.ENABLED
    assert [enabled for _, enabled, _ in bridge.submissions].count(False) == 0


def test_newer_refresh_makes_late_enable_snapshot_stale(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge, controller = _controller()
    initial = controller.refresh()
    assert initial is not None
    _publish(bridge, initial, AutostartStatus.DISABLED)
    bridge.command_completed.emit(initial)
    mutation = controller.set_enabled(
        True,
        origin=AutostartOperationOrigin.SETTINGS_CHECKBOX,
    )
    assert mutation is not None
    refresh = controller.refresh()
    assert refresh is not None

    _publish(bridge, refresh, AutostartStatus.ENABLED)
    bridge.command_completed.emit(refresh)
    _publish(bridge, mutation, AutostartStatus.DISABLED)
    bridge.command_completed.emit(mutation)

    assert controller.snapshot.status is AutostartStatus.ENABLED
    assert not controller.busy


def test_closing_rejects_new_mutation_and_duplicate_terminal_is_ignored(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge, controller = _controller()
    query = controller.refresh()
    assert query is not None
    _publish(bridge, query, AutostartStatus.DISABLED)
    bridge.command_completed.emit(query)
    mutation = controller.set_enabled(
        True,
        origin=AutostartOperationOrigin.SETTINGS_CHECKBOX,
    )
    assert mutation is not None
    bridge.runtime_closing.emit()
    assert controller.set_enabled(
        False,
        origin=AutostartOperationOrigin.TRAY_ACTION,
    ) is None
    _publish(bridge, mutation, AutostartStatus.ENABLED)
    bridge.command_completed.emit(mutation)
    bridge.command_completed.emit(mutation)

    assert controller.snapshot.status is AutostartStatus.ENABLED
    assert not controller.user_toggle_allowed
    assert len([item for item in bridge.submissions if item[1] is not None]) == 1
