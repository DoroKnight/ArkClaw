from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from sjtuclaw.presentation.qt.owner_ui_readiness import (
    OwnerStartupStage,
    OwnerUiCheckpointRecorder,
)
from sjtuclaw.presentation.qt.pet_application import (
    _OwnerUiStartupObserver,
)

_NONCE = "fedcba9876543210fedcba9876543210"


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


class _FakeBridge(QObject):
    runtime_ready = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.accepting_commands = False


class _FakeCoordinator(QObject):
    application_ready = Signal()

    def __init__(self, *, publish: bool = True) -> None:
        super().__init__()
        self._publish = publish
        self.publish_count = 0

    def publish_application_ready(self) -> None:
        self.publish_count += 1
        if self._publish:
            self.application_ready.emit()


class _FakeTray:
    def __init__(self, *, available: bool, visible: bool) -> None:
        self.available = available
        self.visible = visible


def _recorder_ready_for_qt(
    tmp_path: Path,
) -> OwnerUiCheckpointRecorder:
    recorder = OwnerUiCheckpointRecorder(tmp_path, _NONCE)
    for stage in (
        OwnerStartupStage.STARTED,
        OwnerStartupStage.ARGUMENTS_VALIDATED,
        OwnerStartupStage.SINGLE_INSTANCE_OWNER,
        OwnerStartupStage.COMPOSITION_ROOT_CREATED,
        OwnerStartupStage.RUNTIME_STARTING,
        OwnerStartupStage.PET_WINDOW_CREATED,
        OwnerStartupStage.SETTINGS_LOADED,
    ):
        assert recorder.record(stage)
    return recorder


def _last_event(tmp_path: Path) -> dict[str, object]:
    document: object = json.loads(
        (tmp_path / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert isinstance(document, dict)
    events = document.get("events")
    assert isinstance(events, list)
    event = events[-1]
    assert isinstance(event, dict)
    return cast(dict[str, object], event)


def _visible_pet(app: QApplication) -> QWidget:
    pet = QWidget()
    pet.resize(120, 160)
    screen = app.primaryScreen()
    assert screen is not None
    pet.move(screen.availableGeometry().topLeft())
    pet.show()
    app.processEvents()
    return pet


def test_runtime_not_ready_is_distinct_from_ui_visibility(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    recorder = _recorder_ready_for_qt(tmp_path)
    pet = _visible_pet(qt_application)
    bridge = _FakeBridge()
    coordinator = _FakeCoordinator()
    observer = _OwnerUiStartupObserver(
        recorder,
        bridge,  # type: ignore[arg-type]
        pet,  # type: ignore[arg-type]
        _FakeTray(available=True, visible=True),  # type: ignore[arg-type]
        coordinator,  # type: ignore[arg-type]
    )

    observer.begin_closing()

    assert _last_event(tmp_path)["failure_category"] == "runtime_not_ready"
    pet.close()


def test_runtime_ready_with_hidden_pet_fails_at_pet_visibility(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    recorder = _recorder_ready_for_qt(tmp_path)
    pet = QWidget()
    bridge = _FakeBridge()
    coordinator = _FakeCoordinator()
    _OwnerUiStartupObserver(
        recorder,
        bridge,  # type: ignore[arg-type]
        pet,  # type: ignore[arg-type]
        _FakeTray(available=True, visible=True),  # type: ignore[arg-type]
        coordinator,  # type: ignore[arg-type]
    )

    bridge.runtime_ready.emit()

    assert _last_event(tmp_path)["failure_category"] == (
        "pet_window_not_visible"
    )
    assert coordinator.publish_count == 0


def test_visible_pet_with_unavailable_tray_has_independent_reason(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    recorder = _recorder_ready_for_qt(tmp_path)
    pet = _visible_pet(qt_application)
    bridge = _FakeBridge()
    coordinator = _FakeCoordinator()
    _OwnerUiStartupObserver(
        recorder,
        bridge,  # type: ignore[arg-type]
        pet,  # type: ignore[arg-type]
        _FakeTray(available=False, visible=False),  # type: ignore[arg-type]
        coordinator,  # type: ignore[arg-type]
    )

    bridge.runtime_ready.emit()

    assert _last_event(tmp_path)["failure_category"] == (
        "system_tray_unavailable"
    )
    pet.close()


def test_tray_qt_visibility_can_reach_ready_without_window_enumeration(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    recorder = _recorder_ready_for_qt(tmp_path)
    pet = _visible_pet(qt_application)
    bridge = _FakeBridge()
    coordinator = _FakeCoordinator()
    _OwnerUiStartupObserver(
        recorder,
        bridge,  # type: ignore[arg-type]
        pet,  # type: ignore[arg-type]
        _FakeTray(available=True, visible=True),  # type: ignore[arg-type]
        coordinator,  # type: ignore[arg-type]
    )

    bridge.runtime_ready.emit()

    assert _last_event(tmp_path)["stage"] == "application_ready"
    assert coordinator.publish_count == 1
    pet.close()


def test_missing_application_ready_signal_is_recorded_on_close(
    qt_application: QApplication,
    tmp_path: Path,
) -> None:
    recorder = _recorder_ready_for_qt(tmp_path)
    pet = _visible_pet(qt_application)
    bridge = _FakeBridge()
    coordinator = _FakeCoordinator(publish=False)
    observer = _OwnerUiStartupObserver(
        recorder,
        bridge,  # type: ignore[arg-type]
        pet,  # type: ignore[arg-type]
        _FakeTray(available=True, visible=True),  # type: ignore[arg-type]
        coordinator,  # type: ignore[arg-type]
    )

    bridge.runtime_ready.emit()
    observer.begin_closing()

    assert _last_event(tmp_path)["failure_category"] == (
        "application_ready_missing"
    )
    pet.close()
