from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMenu

from sjtuclaw.application.pet_state import PetState
from sjtuclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


class _ManualShutdownBridge(QObject):
    shutdown_finished = Signal(bool, str)


class _RecordingMainWindow:
    def __init__(self) -> None:
        self.close_requests = 0
        self.show_requests = 0

    def request_safe_close(self) -> None:
        self.close_requests += 1

    def show(self) -> None:
        self.show_requests += 1

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


@pytest.fixture(scope="module")
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


def test_placeholder_window_has_safe_desktop_flags(
    qt_application: QApplication,
) -> None:
    del qt_application
    window = PetWindow(always_on_top=True)

    assert window.testAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground
    )
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.physics_timer.isActive()

    window.complete_safe_close()
    assert not window.physics_timer.isActive()


def test_pause_stops_motion_timer_updates_without_stopping_event_loop(
    qt_application: QApplication,
) -> None:
    del qt_application
    window = PetWindow()
    fired = False

    def mark_fired() -> None:
        nonlocal fired
        fired = True

    window.toggle_paused()
    before = window.pos()
    QTimer.singleShot(0, mark_fired)

    assert _run_until(lambda: fired)
    assert window.state is PetState.PAUSED
    assert window.pos() == before
    assert window.physics_timer.isActive()

    window.complete_safe_close()


def test_right_click_exit_waits_for_shutdown_result(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    pet = PetWindow()
    pet.show()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    quit_spy = QSignalSpy(coordinator.quit_requested)

    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        pet.rect().center(),
        pet.mapToGlobal(pet.rect().center()),
    )
    QApplication.sendEvent(pet, event)
    menu = pet.findChild(QMenu)
    assert menu is not None
    assert {
        action.text() for action in menu.actions() if action.text()
    } == {
        "Pause",
        "Always on top",
        "Open Agent window",
        "Exit",
    }
    exit_action = next(
        action for action in menu.actions() if action.text() == "Exit"
    )
    exit_action.trigger()

    assert pet.state is PetState.CLOSING
    assert pet.isVisible()
    assert main_window.close_requests == 1
    assert quit_spy.count() == 0

    bridge.shutdown_finished.emit(True, "none")
    assert _run_until(lambda: quit_spy.count() == 1)
    assert not pet.isVisible()
    assert not pet.physics_timer.isActive()


def test_failed_shutdown_keeps_pet_available_for_explicit_retry(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    pet = PetWindow()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    quit_spy = QSignalSpy(coordinator.quit_requested)

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(False, "runtime_shutdown_failed")

    assert pet.state is PetState.PAUSED
    assert pet.physics_timer.isActive()
    assert quit_spy.count() == 0

    pet.complete_safe_close()


def test_fake_runtime_pet_shutdown_leaves_no_thread_or_async_task(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "profiles.json")
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    main_window = MainWindow(bridge, hide_on_close=True)
    pet = PetWindow()
    coordinator = PetApplicationCoordinator(bridge, main_window, pet)
    quit_spy = QSignalSpy(coordinator.quit_requested)
    pet.show()

    assert _run_until(lambda: ready_spy.count() == 1)
    pet.request_safe_exit()

    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _run_until(lambda: quit_spy.count() == 1)
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0
    assert not pet.physics_timer.isActive()


def test_closing_agent_window_hides_it_without_stopping_pet_runtime(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "hide-agent.json")
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    main_window = MainWindow(bridge, hide_on_close=True)
    pet = PetWindow()
    coordinator = PetApplicationCoordinator(bridge, main_window, pet)
    quit_spy = QSignalSpy(coordinator.quit_requested)
    main_window.show()
    pet.show()
    assert _run_until(lambda: ready_spy.count() == 1)

    assert main_window.close() is False

    assert not main_window.isVisible()
    assert pet.isVisible()
    assert pet.physics_timer.isActive()
    assert bridge.runtime_thread.isRunning()
    assert shutdown_spy.count() == 0
    assert quit_spy.count() == 0

    coordinator.open_agent_window()
    assert main_window.isVisible()

    pet.request_safe_exit()
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _run_until(lambda: quit_spy.count() == 1)
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0
    assert not pet.physics_timer.isActive()


def test_standalone_main_window_close_still_shuts_down_runtime(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "standalone-close.json")
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    main_window = MainWindow(bridge)
    main_window.show()
    assert _run_until(lambda: ready_spy.count() == 1)

    assert main_window.close() is False

    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _run_until(lambda: not main_window.isVisible())
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0
