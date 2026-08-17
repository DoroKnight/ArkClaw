from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.frontend_presentation import (
    ConversationOpenOrRestoreIntent,
    ForegroundOverlay,
    PrimaryPresentation,
    SemanticFocusTarget,
)
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.ui.main_window import MainWindow


@pytest.fixture
def qt_application() -> Iterator[QApplication]:
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    yield app
    app.processEvents()
    if owns_application:
        app.quit()


def _wait_until(predicate, *, timeout_ms: int = 5000) -> bool:
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


def test_pet_application_composition_owns_inert_frontend_seam(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        FakeQtRuntimeCompositionRoot(tmp_path / "profiles.json")
    )
    main_window = MainWindow(bridge, hide_on_close=True)
    pet_window = PetWindow()

    frontend_before = len(QApplication.topLevelWidgets())
    _ = FrontendPresentationCoordinator()
    frontend_after = len(QApplication.topLevelWidgets())
    assert frontend_after == frontend_before

    coordinator = PetApplicationCoordinator(bridge, main_window, pet_window)
    assert isinstance(
        coordinator.frontend_presentation,
        FrontendPresentationCoordinator,
    )
    snapshot = coordinator.frontend_presentation.snapshot
    assert snapshot.primary_presentation is PrimaryPresentation.CHARACTER
    assert snapshot.foreground_overlay is ForegroundOverlay.NONE
    assert snapshot.conversation_context is None
    assert snapshot.semantic_focus_target is SemanticFocusTarget.NONE

    dispatch_before = len(QApplication.topLevelWidgets())
    result = coordinator.frontend_presentation.dispatch(
        ConversationOpenOrRestoreIntent()
    )
    dispatch_after = len(QApplication.topLevelWidgets())

    assert dispatch_after == dispatch_before
    assert result.snapshot.primary_presentation is PrimaryPresentation.CAPSULE
    assert result.snapshot.semantic_focus_target is (
        SemanticFocusTarget.CONVERSATION_INPUT
    )

    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    main_window.request_safe_close()
    assert _wait_until(lambda: shutdown_spy.count() >= 1)
    assert _wait_until(lambda: not bridge.runtime_thread.isRunning())

    pet_window.complete_safe_close()
