from __future__ import annotations

import os
import subprocess
import sys
import traceback
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QEventLoop,
    QMessageLogContext,
    QObject,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QTimer,
    QtMsgType,
    Signal,
)
from PySide6.QtGui import QContextMenuEvent, QImage, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu
from scripts.qt_pet_smoke import _QtMessageAudit

from sjtuclaw.application.pet_animation import (
    PetAnimationConfig,
    PetRenderFrame,
)
from sjtuclaw.application.pet_geometry import Size
from sjtuclaw.application.pet_state import (
    PetLifecycleState,
    PetMotionState,
)
from sjtuclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from sjtuclaw.presentation.qt.pet_renderer import (
    PlaceholderPetRenderer,
)
from sjtuclaw.presentation.qt.pet_window import PetWindow
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from sjtuclaw.presentation.qt.system_tray import (
    PetTrayState,
    SystemTrayController,
    TrayCallbacks,
    _create_programmatic_tray_icon,
    _QtSystemTrayView,
)


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


class _FakeClock:
    def __init__(self) -> None:
        self.value = 10.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _FakeRenderer:
    def __init__(self, events: list[str] | None = None) -> None:
        self.frames: list[PetRenderFrame] = []
        self.sizes: list[Size] = []
        self.closed = False
        self._events = events

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del painter
        self.frames.append(frame)

    def resize(self, size: Size) -> None:
        self.sizes.append(size)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._events is not None:
            self._events.append("renderer")


class _FakeTrayView:
    def __init__(
        self,
        callbacks: TrayCallbacks,
        events: list[str] | None = None,
        *,
        failure: Exception | None = None,
        fail_show: bool = False,
        fail_update_after: int | None = None,
        fail_close_count: int = 0,
    ) -> None:
        self.callbacks = callbacks
        self.show_count = 0
        self.close_count = 0
        self.states: list[PetTrayState] = []
        self._events = events
        self._failure = failure or RuntimeError("controlled tray failure")
        self._fail_show = fail_show
        self._fail_update_after = fail_update_after
        self._fail_close_count = fail_close_count

    def show(self) -> None:
        self.show_count += 1
        if self._fail_show:
            raise self._failure

    def update_state(self, state: PetTrayState) -> None:
        if (
            self._fail_update_after is not None
            and len(self.states) >= self._fail_update_after
        ):
            raise self._failure
        self.states.append(state)

    def close(self) -> None:
        self.close_count += 1
        if self.close_count <= self._fail_close_count:
            raise self._failure
        if self._events is not None:
            self._events.append("tray")


class _FakeTrayFactory:
    def __init__(
        self,
        *,
        available: bool = True,
        events: list[str] | None = None,
        failure: Exception | None = None,
        fail_factory: bool = False,
        fail_show: bool = False,
        fail_update_after: int | None = None,
        fail_close_count: int = 0,
    ) -> None:
        self.available = available
        self.call_count = 0
        self.view: _FakeTrayView | None = None
        self._events = events
        self._failure = failure or RuntimeError("controlled tray failure")
        self._fail_factory = fail_factory
        self._fail_show = fail_show
        self._fail_update_after = fail_update_after
        self._fail_close_count = fail_close_count

    def __call__(
        self,
        callbacks: TrayCallbacks,
        parent: QObject,
    ) -> _FakeTrayView | None:
        del parent
        self.call_count += 1
        if self._fail_factory:
            raise self._failure
        if not self.available:
            return None
        self.view = _FakeTrayView(
            callbacks,
            self._events,
            failure=self._failure,
            fail_show=self._fail_show,
            fail_update_after=self._fail_update_after,
            fail_close_count=self._fail_close_count,
        )
        return self.view


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
    assert window.lifecycle_state is PetLifecycleState.PAUSED
    assert window.pos() == before
    assert window.physics_timer.isActive()

    window.complete_safe_close()


def test_paused_window_allows_manual_drag_without_falling(
    qt_application: QApplication,
) -> None:
    del qt_application
    window = PetWindow()
    window.show()
    window.toggle_paused()
    start = window.pos()
    center = window.rect().center()

    QTest.mousePress(
        window,
        Qt.MouseButton.LeftButton,
        pos=center,
    )
    QTest.mouseMove(window, center + QPoint(30, 20))
    QTest.mouseRelease(
        window,
        Qt.MouseButton.LeftButton,
        pos=center + QPoint(30, 20),
    )

    assert window.lifecycle_state is PetLifecycleState.PAUSED
    assert window.motion_state is PetMotionState.IDLE
    assert window.pos() != start
    window.complete_safe_close()


def test_replaceable_renderer_captures_non_sensitive_frames(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _FakeClock()
    renderer = _FakeRenderer()
    window = PetWindow(
        renderer=renderer,
        clock=clock,
        animation_config=PetAnimationConfig(
            blinking_interval_min_seconds=100,
            blinking_interval_max_seconds=100,
            random_action_interval_min_seconds=100,
            random_action_interval_max_seconds=100,
        ),
    )
    window.show()
    clock.advance(0.05)
    window.physics_timer.timeout.emit()
    window.repaint()

    assert _run_until(lambda: bool(renderer.frames))
    assert renderer.frames[-1].state.motion is PetMotionState.IDLE
    assert renderer.sizes[-1] == Size(160, 180)
    assert renderer.frames[-1].window_size == Size(160, 180)

    window.complete_safe_close()
    assert renderer.closed


def test_breathing_transform_keeps_foot_baseline_fixed(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _FakeClock()
    window = PetWindow(clock=clock)
    for _ in range(12):
        clock.advance(0.1)
        window.physics_timer.timeout.emit()
    frame = window.render_frame
    renderer = PlaceholderPetRenderer()
    mapped_foot = renderer._breathing_point(
        QPointF(80, renderer.foot_baseline_y),
        frame,
    )
    mapped_top = renderer._breathing_point(
        QPointF(80, 24),
        frame,
    )

    assert frame.visual.breathing_amount == pytest.approx(1.0)
    assert mapped_foot == QPointF(80, renderer.foot_baseline_y)
    assert mapped_top.y() < 20
    window.complete_safe_close()


def _render_placeholder_frame(
    renderer: PlaceholderPetRenderer,
    frame: PetRenderFrame,
) -> QImage:
    image = QImage(
        round(frame.window_size.width),
        round(frame.window_size.height),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter, frame)
    finally:
        painter.end()
    return image


def _region_pixels(
    image: QImage,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> tuple[int, ...]:
    return tuple(
        image.pixel(x, y)
        for y in range(top, bottom)
        for x in range(left, right)
    )


def _opaque_bounds(
    image: QImage,
    *,
    minimum_alpha: int,
) -> tuple[int, int, int, int]:
    points = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() >= minimum_alpha
    ]
    assert points
    return (
        min(x for x, _ in points),
        min(y for _, y in points),
        max(x for x, _ in points),
        max(y for _, y in points),
    )


def test_final_pixels_show_local_breathing_with_stable_feet_and_shadow(
    qt_application: QApplication,
) -> None:
    del qt_application
    window = PetWindow()
    base = window.render_frame
    low = replace(
        base,
        visual=replace(base.visual, breathing_amount=0.0),
    )
    high = replace(
        base,
        visual=replace(base.visual, breathing_amount=1.0),
    )
    renderer = PlaceholderPetRenderer()

    low_image = _render_placeholder_frame(renderer, low)
    high_image = _render_placeholder_frame(renderer, high)
    differing_pixels = sum(
        low_image.pixel(x, y) != high_image.pixel(x, y)
        for y in range(low_image.height())
        for x in range(low_image.width())
    )
    opaque_union_pixels = sum(
        low_image.pixelColor(x, y).alpha() >= 200
        or high_image.pixelColor(x, y).alpha() >= 200
        for y in range(low_image.height())
        for x in range(low_image.width())
    )
    low_bounds = _opaque_bounds(low_image, minimum_alpha=200)
    high_bounds = _opaque_bounds(high_image, minimum_alpha=200)

    assert low_image.size() == high_image.size()
    assert differing_pixels > 300
    assert 0.05 < differing_pixels / opaque_union_pixels < 0.35
    assert _region_pixels(
        low_image,
        left=28,
        top=164,
        right=132,
        bottom=173,
    ) == _region_pixels(
        high_image,
        left=28,
        top=164,
        right=132,
        bottom=173,
    )
    assert _region_pixels(
        low_image,
        left=35,
        top=151,
        right=125,
        bottom=164,
    ) == _region_pixels(
        high_image,
        left=35,
        top=151,
        right=125,
        bottom=164,
    )
    assert low_bounds[3] == high_bounds[3]
    assert (low_bounds[0] + low_bounds[2]) / 2 == pytest.approx(
        (high_bounds[0] + high_bounds[2]) / 2
    )
    assert low_bounds[1] - high_bounds[1] >= 4
    window.complete_safe_close()


def test_smoke_qt_message_audit_uses_exact_fail_closed_classification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit = _QtMessageAudit(
        {
            "known exact warning": 1,
            "missing exact warning": 1,
        }
    )
    context = cast(QMessageLogContext, object())

    audit.handle(
        QtMsgType.QtWarningMsg,
        context,
        "known exact warning",
    )
    audit.handle(
        QtMsgType.QtWarningMsg,
        context,
        "known exact warning",
    )
    audit.handle(
        QtMsgType.QtWarningMsg,
        context,
        "unknown warning",
    )
    audit.handle(
        QtMsgType.QtCriticalMsg,
        context,
        "critical message",
    )
    audit.handle(
        QtMsgType.QtInfoMsg,
        context,
        "other message",
    )
    captured = capsys.readouterr()

    assert audit.expected_warning_count == 1
    assert audit.missing_warning_count == 1
    assert audit.duplicate_warning_count == 1
    assert audit.unexpected_warnings == ["unknown warning"]
    assert audit.critical_messages == ["critical message"]
    assert audit.other_messages == ["other message"]
    assert "known exact warning" not in captured.err
    assert "unknown warning" in captured.err
    assert "critical message" in captured.err
    assert "other message" in captured.err


def test_pet_smoke_isolates_inherited_qt_environment() -> None:
    probe = Path(__file__).parents[2] / "scripts" / "qt_pet_smoke.py"
    clean_environment = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
    }
    clean_environment.pop("QT_QPA_FONTDIR", None)
    contaminated_environment = {
        **clean_environment,
        "QT_QPA_PLATFORM": "invalid-parent-platform",
        "QT_QPA_FONTDIR": r"C:\Windows\Fonts",
    }

    clean_result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=probe.parents[1],
        env=clean_environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    contaminated_result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=probe.parents[1],
        env=contaminated_environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert clean_result.returncode == 0
    assert contaminated_result.returncode == 0
    assert clean_result.stderr == ""
    assert contaminated_result.stderr == ""
    assert contaminated_result.stdout == clean_result.stdout
    assert "FT_New_Face failed" not in (
        contaminated_result.stdout + contaminated_result.stderr
    )
    assert "qt_pet_smoke=True" in clean_result.stdout
    assert "expected_qt_platform_warnings=3" in clean_result.stdout
    assert "missing_qt_platform_warnings=0" in clean_result.stdout
    assert "duplicate_qt_platform_warnings=0" in clean_result.stdout
    assert "unexpected_qt_warnings=0" in clean_result.stdout
    assert "qt_critical_messages=0" in clean_result.stdout
    assert "qt_other_messages=0" in clean_result.stdout
    assert "pending_asyncio_tasks=0" in clean_result.stdout
    assert "timer_active=False" in clean_result.stdout
    assert "renderer_closed=True" in clean_result.stdout
    fields = dict(
        field.split("=", maxsplit=1)
        for field in clean_result.stdout.split()
        if "=" in field
    )
    assert int(fields["expected_qt_platform_warnings"]) == 3


def test_fake_clock_drives_animation_without_blocking_qt_event_loop(
    qt_application: QApplication,
) -> None:
    del qt_application
    clock = _FakeClock()
    window = PetWindow(clock=clock)
    fired = False

    def mark_fired() -> None:
        nonlocal fired
        fired = True

    before = window.render_frame.animation_time
    clock.advance(0.08)
    window.physics_timer.timeout.emit()
    QTimer.singleShot(0, mark_fired)

    assert _run_until(lambda: fired)
    assert window.render_frame.animation_time == pytest.approx(before + 0.08)
    window.complete_safe_close()


def test_closing_stops_single_timer_and_finalizes_renderer(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _FakeRenderer()
    window = PetWindow(renderer=renderer)

    window.request_safe_exit()

    assert window.lifecycle_state is PetLifecycleState.CLOSING
    assert not window.physics_timer.isActive()
    assert not renderer.closed

    window.complete_safe_close()
    assert renderer.closed


def test_unavailable_system_tray_degrades_without_hiding_pet(
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
    factory = _FakeTrayFactory(available=False)

    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    tray.refresh()
    tray.refresh()

    assert factory.call_count == 1
    assert not tray.available
    assert tray.safe_code == "system_tray_unavailable"
    assert pet.isVisible()
    assert pet.physics_timer.isActive()
    pet.complete_safe_close()


def test_tray_factory_failure_degrades_without_reconstruction(
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
    factory = _FakeTrayFactory(fail_factory=True)

    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    tray.refresh()

    assert factory.call_count == 1
    assert not tray.available
    assert not tray.cleanup_pending
    assert tray.safe_code == "system_tray_initialization_failed"
    assert pet.isVisible()
    assert pet.physics_timer.isActive()
    tray.complete_shutdown()
    assert tray.closed
    pet.complete_safe_close()


@pytest.mark.parametrize(
    ("fail_show", "fail_update_after", "expected_show_count"),
    [
        (True, None, 1),
        (False, 0, 0),
    ],
)
def test_tray_initial_view_failure_retains_cleanup_reference(
    qt_application: QApplication,
    fail_show: bool,
    fail_update_after: int | None,
    expected_show_count: int,
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
    factory = _FakeTrayFactory(
        fail_show=fail_show,
        fail_update_after=fail_update_after,
    )

    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    view = factory.view
    assert view is not None

    assert factory.call_count == 1
    assert view.show_count == expected_show_count
    assert not tray.available
    assert tray.cleanup_pending
    assert tray.safe_code == "system_tray_initialization_failed"
    assert pet.isVisible()
    assert pet.physics_timer.isActive()

    tray.complete_shutdown()
    assert tray.closed
    assert view.close_count == 1
    pet.complete_safe_close()


def test_tray_refresh_failure_is_contained_and_commands_are_not_repeated(
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
    factory = _FakeTrayFactory(fail_update_after=1)
    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    view = factory.view
    assert view is not None

    coordinator.attach_system_tray(tray)
    assert tray.safe_code == "system_tray_refresh_failed"
    assert len(view.states) == 1

    view.callbacks.toggle_pet_visibility()
    tray.refresh()
    tray.refresh()

    assert not pet.isVisible()
    assert len(view.states) == 1
    assert factory.call_count == 1
    tray.complete_shutdown()
    pet.complete_safe_close()


def test_tray_exception_boundary_does_not_expose_sensitive_details(
    qt_application: QApplication,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del qt_application
    sensitive = (
        "sk-test-never-use-this-value "
        r"C:\Users\private\CredentialBlob"
    )
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    pet = PetWindow()
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    factory = _FakeTrayFactory(
        failure=RuntimeError(sensitive),
        fail_factory=True,
    )

    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    tray.refresh()
    captured = capsys.readouterr()
    visible_outputs = "\n".join(
        (
            tray.safe_code,
            repr(tray),
            captured.out,
            captured.err,
            caplog.text,
            "".join(traceback.format_stack()),
        )
    )

    assert sensitive not in visible_outputs
    assert "sk-test-never-use-this-value" not in visible_outputs
    assert "CredentialBlob" not in visible_outputs
    assert "Traceback" not in captured.err
    assert tray.safe_code == "system_tray_initialization_failed"
    tray.complete_shutdown()
    pet.complete_safe_close()


def test_programmatic_tray_icon_has_multiple_pixel_sizes(
    qt_application: QApplication,
) -> None:
    del qt_application

    icon = _create_programmatic_tray_icon()

    assert not icon.isNull()
    available = {(size.width(), size.height()) for size in icon.availableSizes()}
    assert {
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
    }.issubset(available)
    assert not icon.pixmap(QSize(32, 32)).isNull()


def test_qt_tray_view_builds_reviewed_menu_and_synchronizes_labels(
    qt_application: QApplication,
) -> None:
    del qt_application
    callbacks = TrayCallbacks(
        refresh=lambda: None,
        toggle_pet_visibility=lambda: None,
        open_agent_window=lambda: None,
        toggle_paused=lambda: None,
        set_always_on_top=lambda enabled: None,
        request_safe_exit=lambda: None,
    )
    parent = QObject()
    view = _QtSystemTrayView(callbacks, parent)

    assert [
        action.text()
        for action in view._menu.actions()
        if not action.isSeparator()
    ] == [
        "Hide Pet",
        "Open Agent Window",
        "Pause",
        "Always on Top",
        "Start with Windows",
        "Exit",
    ]

    view.update_state(
        PetTrayState(
            pet_visible=False,
            paused=True,
            always_on_top=True,
            closing=False,
        )
    )

    assert view._visibility_action.text() == "Show Pet"
    assert view._pause_action.text() == "Continue"
    assert view._always_on_top_action.isChecked()

    view.update_state(
        PetTrayState(
            pet_visible=True,
            paused=False,
            always_on_top=False,
            closing=True,
        )
    )
    assert all(
        not action.isEnabled()
        for action in view._menu.actions()
        if not action.isSeparator()
    )
    view.close()
    view.close()


def test_fake_tray_commands_share_pet_state_and_reclaim_workspace(
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
    factory = _FakeTrayFactory()
    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    view = factory.view
    assert view is not None

    view.callbacks.toggle_pet_visibility()
    assert not pet.isVisible()
    assert pet.physics_timer.isActive()
    assert view.states[-1].pet_visible is False

    pet.move(50_000, 50_000)
    view.callbacks.toggle_pet_visibility()
    assert pet.isVisible()
    assert pet.pos().x() < 50_000
    assert pet.pos().y() < 50_000
    assert view.states[-1].pet_visible is True

    view.callbacks.open_agent_window()
    assert main_window.show_requests == 1

    view.callbacks.toggle_paused()
    assert pet.lifecycle_state is PetLifecycleState.PAUSED
    assert view.states[-1].paused
    pause_menu_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        pet.rect().center(),
        pet.mapToGlobal(pet.rect().center()),
    )
    QApplication.sendEvent(pet, pause_menu_event)
    pause_menu = pet.findChild(QMenu)
    assert pause_menu is not None
    pause_action = next(
        action
        for action in pause_menu.actions()
        if action.text() == "Continue"
    )
    pause_action.trigger()
    assert pet.lifecycle_state is PetLifecycleState.ACTIVE
    assert not view.states[-1].paused

    view.callbacks.set_always_on_top(False)
    assert not pet.always_on_top
    assert not view.states[-1].always_on_top
    top_menu_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        pet.rect().center(),
        pet.mapToGlobal(pet.rect().center()),
    )
    QApplication.sendEvent(pet, top_menu_event)
    top_action = next(
        action
        for menu in pet.findChildren(QMenu)
        for action in menu.actions()
        if action.text() == "Always on top"
        and not action.isChecked()
    )
    top_action.setChecked(True)
    assert pet.always_on_top
    assert view.states[-1].always_on_top

    assert factory.call_count == 1
    assert view.show_count == 1
    pet.complete_safe_close()


def test_tray_exit_is_idempotent_and_closes_view_after_shutdown(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    close_events: list[str] = []
    renderer = _FakeRenderer(close_events)
    pet = PetWindow(renderer=renderer)
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    factory = _FakeTrayFactory(events=close_events)
    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    view = factory.view
    assert view is not None
    quit_spy = QSignalSpy(coordinator.quit_requested)

    view.callbacks.request_safe_exit()
    view.callbacks.request_safe_exit()

    assert main_window.close_requests == 1
    assert pet.lifecycle_state is PetLifecycleState.CLOSING
    assert view.close_count == 0
    bridge.shutdown_finished.emit(True, "none")

    assert _run_until(lambda: quit_spy.count() == 1)
    assert tray.closed
    assert view.close_count == 1
    assert renderer.closed
    assert close_events == ["tray", "renderer"]
    assert not pet.physics_timer.isActive()


def test_failed_tray_exit_preserves_view_and_allows_retry(
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
    factory = _FakeTrayFactory()
    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    view = factory.view
    assert view is not None

    view.callbacks.request_safe_exit()
    bridge.shutdown_finished.emit(False, "runtime_shutdown_failed")

    assert not tray.closed
    assert view.close_count == 0
    assert pet.lifecycle_state is PetLifecycleState.PAUSED
    assert pet.physics_timer.isActive()

    view.callbacks.request_safe_exit()
    assert main_window.close_requests == 2
    bridge.shutdown_finished.emit(True, "none")
    assert view.close_count == 1


def test_tray_close_failure_does_not_block_application_cleanup(
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = _ManualShutdownBridge()
    main_window = _RecordingMainWindow()
    close_events: list[str] = []
    renderer = _FakeRenderer(close_events)
    pet = PetWindow(renderer=renderer)
    coordinator = PetApplicationCoordinator(
        cast(QtRuntimeBridge, bridge),
        cast(MainWindow, main_window),
        pet,
    )
    factory = _FakeTrayFactory(
        events=close_events,
        fail_close_count=1,
    )
    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    view = factory.view
    assert view is not None
    quit_spy = QSignalSpy(coordinator.quit_requested)

    view.callbacks.request_safe_exit()
    bridge.shutdown_finished.emit(True, "none")

    assert _run_until(lambda: quit_spy.count() == 1)
    assert tray.cleanup_pending
    assert not tray.closed
    assert tray.safe_code == "system_tray_cleanup_failed"
    assert view.close_count == 1
    assert renderer.closed
    assert close_events == ["renderer"]
    assert not pet.physics_timer.isActive()

    assert tray.retry_pending_cleanup()
    assert tray.closed
    assert not tray.cleanup_pending
    assert tray.safe_code == "none"
    assert view.close_count == 2
    assert close_events == ["renderer", "tray"]
    assert quit_spy.count() == 1


def test_runtime_shutdown_failure_contains_tray_refresh_failure(
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
    factory = _FakeTrayFactory(fail_update_after=2)
    tray = SystemTrayController(
        coordinator,
        view_factory=factory,
        parent=coordinator,
    )
    coordinator.attach_system_tray(tray)
    view = factory.view
    assert view is not None

    view.callbacks.request_safe_exit()
    bridge.shutdown_finished.emit(False, "runtime_shutdown_failed")

    assert tray.safe_code == "system_tray_refresh_failed"
    assert not tray.closed
    assert not tray.cleanup_pending
    assert pet.lifecycle_state is PetLifecycleState.PAUSED
    assert pet.physics_timer.isActive()
    assert main_window.close_requests == 1

    view.callbacks.request_safe_exit()
    assert main_window.close_requests == 2
    tray.complete_shutdown()
    pet.complete_safe_close()


def test_tray_smoke_uses_fake_tray_and_cleans_all_resources() -> None:
    probe = Path(__file__).parents[2] / "scripts" / "qt_tray_smoke.py"
    environment = {
        **os.environ,
        "QT_QPA_PLATFORM": "invalid-parent-platform",
        "QT_QPA_FONTDIR": r"C:\Windows\Fonts",
    }

    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=probe.parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "qt_tray_smoke=True" in result.stdout
    assert "fake_tray=True" in result.stdout
    assert "tray_factory_calls=1" in result.stdout
    assert "tray_close_count=1" in result.stdout
    assert "missing_qt_platform_warnings=0" in result.stdout
    assert "duplicate_qt_platform_warnings=0" in result.stdout
    assert "unexpected_qt_warnings=0" in result.stdout
    assert "qt_critical_messages=0" in result.stdout
    assert "qt_other_messages=0" in result.stdout
    assert "thread_running=False" in result.stdout
    assert "pending_asyncio_tasks=0" in result.stdout
    assert "timer_active=False" in result.stdout
    assert "FT_New_Face failed" not in result.stdout


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
        "Start with Windows",
        "Open Agent window",
        "Exit",
    }
    exit_action = next(
        action for action in menu.actions() if action.text() == "Exit"
    )
    exit_action.trigger()

    assert pet.lifecycle_state is PetLifecycleState.CLOSING
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

    assert pet.lifecycle_state is PetLifecycleState.PAUSED
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
