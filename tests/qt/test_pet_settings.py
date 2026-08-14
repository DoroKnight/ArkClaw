"""Qt-boundary tests for owner-only desktop-pet settings coordination."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPainter
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet_animation import PetRenderFrame
from arkclaw.application.pet_geometry import Size
from arkclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
    placeholder_animation_capability,
)
from arkclaw.application.pet_settings import (
    PetSettings,
    PetSettingsLoadResult,
    PetSettingsRepository,
)
from arkclaw.presentation.qt import (
    pet_application,
    pet_settings_controller,
)
from arkclaw.presentation.qt.main_window import MainWindow
from arkclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from arkclaw.presentation.qt.pet_settings_controller import (
    PetSettingsController,
)
from arkclaw.presentation.qt.pet_window import PetWindow
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.system_tray import SystemTrayController


class _ManualShutdownBridge(QObject):
    shutdown_finished = Signal(bool, str)


class _RecordingMainWindow:
    def __init__(self) -> None:
        self.close_requests = 0

    def request_safe_close(self) -> None:
        self.close_requests += 1

    def show(self) -> None:
        pass

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


class _RecordingRenderer:
    def __init__(self) -> None:
        self.closed = False

    def initialize(self, viewport: Size) -> None:
        del viewport

    def set_viewport(self, viewport: Size) -> None:
        del viewport

    def set_state(self, request: PetRendererActionRequest) -> None:
        del request

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del painter, frame

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _RecordingTray:
    def __init__(self) -> None:
        self.complete_count = 0

    def refresh(self) -> None:
        pass

    def complete_shutdown(self) -> None:
        self.complete_count += 1

    def recover_failed_shutdown(self) -> None:
        pass


class _RecordingSettingsRepository(PetSettingsRepository):
    def __init__(
        self,
        result: PetSettingsLoadResult,
        *,
        load_failure: BaseException | None = None,
        save_failure: BaseException | None = None,
    ) -> None:
        self.result = result
        self.load_failure = load_failure
        self.save_failure = save_failure
        self.load_count = 0
        self.saved: list[PetSettings] = []

    def load(self) -> PetSettingsLoadResult:
        self.load_count += 1
        if self.load_failure is not None:
            raise self.load_failure
        return self.result

    def save(self, settings: PetSettings) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.saved.append(settings)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app


def _coordinator(
    pet: PetWindow,
    controller: PetSettingsController,
) -> tuple[
    _ManualShutdownBridge,
    _RecordingMainWindow,
    PetApplicationCoordinator,
]:
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
        settings_controller=controller,
    )
    return bridge, main_window, coordinator


def test_restore_applies_topmost_and_authoritative_motion_position(
    qt_application: QApplication,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(
            PetSettings(40, 50, False),
            "none",
            True,
        )
    )
    controller = PetSettingsController(repository)
    pet = PetWindow(always_on_top=True)
    _, _, coordinator = _coordinator(pet, controller)

    coordinator.restore_pet_settings()
    restored = pet.persisted_presentation_state()

    assert restored == (pet.x(), pet.y(), False)
    screen = QApplication.primaryScreen()
    assert screen is not None
    workspace = screen.availableGeometry()
    assert restored[0] == 40
    assert restored[1] + pet.height() == workspace.y() + workspace.height()
    assert repository.load_count == 1
    pet.physics_timer.timeout.emit()
    assert (pet.x(), pet.y()) == restored[:2]
    pet.complete_safe_close()


def test_restore_clamps_offscreen_coordinates_before_show(
    qt_application: QApplication,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(
            PetSettings(999_999, -999_999, True),
            "none",
            True,
        )
    )
    pet = PetWindow()
    _, _, coordinator = _coordinator(
        pet,
        PetSettingsController(repository),
    )

    coordinator.restore_pet_settings()

    assert pet.x() < 999_999
    assert pet.y() > -999_999
    assert pet.persisted_presentation_state()[:2] == (pet.x(), pet.y())
    pet.complete_safe_close()


def test_moving_and_topmost_changes_do_not_write_per_event(
    qt_application: QApplication,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(None, "none", True)
    )
    controller = PetSettingsController(repository)
    pet = PetWindow()
    _, _, coordinator = _coordinator(pet, controller)
    coordinator.restore_pet_settings()

    pet.restore_persisted_position(70, 80)
    pet.set_always_on_top(False)
    pet.physics_timer.timeout.emit()

    assert repository.saved == []
    assert controller.save_count == 0
    pet.complete_safe_close()


def test_successful_runtime_shutdown_saves_exactly_once(
    qt_application: QApplication,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(None, "none", True)
    )
    controller = PetSettingsController(repository)
    pet = PetWindow()
    bridge, main_window, coordinator = _coordinator(pet, controller)
    quit_spy = QSignalSpy(coordinator.quit_requested)
    coordinator.restore_pet_settings()
    pet.restore_persisted_position(90, 100)
    pet.set_always_on_top(False)
    expected_position = pet.persisted_presentation_state()[:2]

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")
    controller.save_once(PetSettings(1, 2, True))

    assert main_window.close_requests >= 1
    assert quit_spy.count() == 0
    QApplication.processEvents()
    assert quit_spy.count() == 1
    assert repository.saved == [
        PetSettings(expected_position[0], expected_position[1], False)
    ]
    assert controller.save_count == 1
    assert not pet.physics_timer.isActive()


def test_failed_runtime_shutdown_never_saves_and_retry_success_does(
    qt_application: QApplication,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(None, "none", True)
    )
    controller = PetSettingsController(repository)
    pet = PetWindow()
    bridge, _, coordinator = _coordinator(pet, controller)
    coordinator.restore_pet_settings()

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(False, "runtime_shutdown_failed")

    assert repository.saved == []
    assert controller.save_count == 0
    assert pet.physics_timer.isActive()

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")
    QApplication.processEvents()
    assert len(repository.saved) == 1
    assert controller.save_count == 1


def test_write_failure_does_not_block_other_shutdown_cleanup(
    qt_application: QApplication,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(None, "none", True),
        save_failure=OSError("controlled failure"),
    )
    controller = PetSettingsController(repository)
    renderer = _RecordingRenderer()
    pet = PetWindow(renderer=renderer)
    bridge, _, coordinator = _coordinator(pet, controller)
    tray = _RecordingTray()
    coordinator.attach_system_tray(
        cast(SystemTrayController, tray)
    )
    quit_spy = QSignalSpy(coordinator.quit_requested)
    coordinator.restore_pet_settings()

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")
    QApplication.processEvents()

    assert coordinator.settings_safe_code == "pet_settings_write_failed"
    assert quit_spy.count() == 1
    assert not pet.physics_timer.isActive()
    assert not pet.isVisible()
    assert renderer.closed
    assert tray.complete_count == 1


@pytest.mark.parametrize(
    "failed_method",
    [
        "set_always_on_top",
        "restore_persisted_position",
    ],
)
def test_restore_failure_returns_to_builtin_defaults_without_leak(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    failed_method: str,
) -> None:
    del qt_application
    sensitive = "sk-test-never-use-this-value CredentialBlob"
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(
            PetSettings(40, 50, False),
            "none",
            True,
        )
    )
    controller = PetSettingsController(repository)
    pet = PetWindow(always_on_top=True)
    default_state = pet.persisted_presentation_state()
    _, _, coordinator = _coordinator(pet, controller)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(sensitive)

    monkeypatch.setattr(pet, failed_method, fail)

    coordinator.restore_pet_settings()
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            coordinator.settings_safe_code,
            repr(coordinator),
            captured.out,
            captured.err,
            caplog.text,
            "".join(traceback.format_stack()),
        )
    )

    assert coordinator.settings_safe_code == "pet_settings_restore_failed"
    assert pet.persisted_presentation_state() == default_state
    assert repository.saved == []
    assert sensitive not in visible
    pet.complete_safe_close()


def test_snapshot_failure_still_completes_every_shutdown_step(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(None, "none", True)
    )
    controller = PetSettingsController(repository)
    pet = PetWindow()
    bridge, main_window, coordinator = _coordinator(pet, controller)
    quit_spy = QSignalSpy(coordinator.quit_requested)
    coordinator.restore_pet_settings()

    def fail_snapshot() -> tuple[int, int, bool]:
        raise OSError("sk-test-never-use-this-value CredentialBlob")

    monkeypatch.setattr(
        pet,
        "persisted_presentation_state",
        fail_snapshot,
    )
    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")
    QApplication.processEvents()

    assert coordinator.settings_safe_code == "pet_settings_snapshot_failed"
    assert repository.saved == []
    assert main_window.close_requests >= 2
    assert quit_spy.count() == 1
    assert not pet.physics_timer.isActive()
    assert not pet.isVisible()


def test_settings_model_construction_failure_still_quits(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(None, "none", True)
    )
    controller = PetSettingsController(repository)
    pet = PetWindow()
    bridge, _, coordinator = _coordinator(pet, controller)
    quit_spy = QSignalSpy(coordinator.quit_requested)
    coordinator.restore_pet_settings()

    def fail_settings(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise ValueError("controlled settings construction failure")

    monkeypatch.setattr(pet_application, "PetSettings", fail_settings)
    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")
    QApplication.processEvents()

    assert coordinator.settings_safe_code == "pet_settings_snapshot_failed"
    assert repository.saved == []
    assert quit_spy.count() == 1
    assert not pet.physics_timer.isActive()


@pytest.mark.parametrize(
    "failure_point",
    ["path", "factory"],
)
def test_optional_settings_initialization_failure_is_inert_and_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    failure_point: str,
) -> None:
    sensitive = "sk-test-never-use-this-value C:\\private\\settings.json"

    def fail(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise OSError(sensitive)

    if failure_point == "path":
        monkeypatch.setattr(
            pet_settings_controller,
            "default_pet_settings_path",
            fail,
        )
    else:
        monkeypatch.setattr(
            pet_application,
            "create_production_pet_settings_controller",
            fail,
        )

    controller = (
        pet_application._create_optional_pet_settings_controller()
    )
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            controller.safe_code,
            repr(controller),
            captured.out,
            captured.err,
            caplog.text,
        )
    )

    assert controller.safe_code == "pet_settings_initialization_failed"
    assert not controller.write_allowed
    assert sensitive not in visible


def test_optional_boundaries_preserve_process_control_exceptions(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application

    def interrupt_factory() -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        pet_application,
        "create_production_pet_settings_controller",
        interrupt_factory,
    )
    with pytest.raises(KeyboardInterrupt):
        pet_application._create_optional_pet_settings_controller()

    repository = _RecordingSettingsRepository(
        PetSettingsLoadResult(
            PetSettings(40, 50, False),
            "none",
            True,
        )
    )
    pet = PetWindow()
    _, _, coordinator = _coordinator(
        pet,
        PetSettingsController(repository),
    )

    def interrupt_restore(enabled: bool) -> None:
        del enabled
        raise KeyboardInterrupt

    monkeypatch.setattr(pet, "set_always_on_top", interrupt_restore)
    with pytest.raises(KeyboardInterrupt):
        coordinator.restore_pet_settings()
    pet.complete_safe_close()


@pytest.mark.parametrize(
    "load_result",
    [
        PetSettingsLoadResult(None, "pet_settings_corrupted", False),
        PetSettingsLoadResult(
            None,
            "pet_settings_schema_unsupported",
            False,
        ),
    ],
)
def test_invalid_existing_document_is_not_overwritten_on_shutdown(
    qt_application: QApplication,
    load_result: PetSettingsLoadResult,
) -> None:
    del qt_application
    repository = _RecordingSettingsRepository(load_result)
    controller = PetSettingsController(repository)
    pet = PetWindow()
    bridge, _, coordinator = _coordinator(pet, controller)
    coordinator.restore_pet_settings()

    pet.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")
    QApplication.processEvents()

    assert repository.saved == []
    assert coordinator.settings_safe_code == load_result.safe_code


def test_settings_smoke_runs_two_isolated_lifecycles() -> None:
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).parents[2]
                / "scripts"
                / "qt_pet_settings_smoke.py"
            ),
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "qt_pet_settings_smoke=True" in result.stdout
    assert "settings_schema_version=1" in result.stdout
    assert "first_save_count=1" in result.stdout
    assert "second_load_count=1" in result.stdout
    assert "position_restored=True" in result.stdout
    assert "position_in_workspace=True" in result.stdout
    assert "always_on_top_restored=True" in result.stdout
    assert "secondary_settings_access_count=0" in result.stdout
    assert "atomic_write=True" in result.stdout
    assert "thread_running=False" in result.stdout
    assert "pending_asyncio_tasks=0" in result.stdout
    assert "unexpected_qt_warnings=0" in result.stdout
    assert "failed_checks=" in result.stdout
    assert "Traceback" not in result.stderr
