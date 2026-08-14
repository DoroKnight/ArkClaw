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
import shiboken6

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QEvent,
    QEventLoop,
    QMessageLogContext,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QTimer,
    QtMsgType,
    Signal,
)
from PySide6.QtGui import QContextMenuEvent, QImage, QMouseEvent, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget
from scripts.qt_pet_smoke import _QtMessageAudit

from arkclaw.application.pet_animation import (
    PetAnimationConfig,
    PetRenderFrame,
)
from arkclaw.application.pet_geometry import Point, Rect, Size
from arkclaw.application.pet_production_actions import (
    ActionSource,
    ProductionAction,
)
from arkclaw.application.pet_render_layout import (
    PetRenderLayout,
    PetRenderLayoutQuality,
    PetRenderSurfaceMode,
)
from arkclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
    placeholder_animation_capability,
)
from arkclaw.application.pet_role_pack import (
    AnimationRoleRegistry,
    RoleAnimationBinding,
    build_track0_animation_registry,
)
from arkclaw.application.pet_state import (
    PetFacing,
    PetLifecycleState,
    PetMotionState,
)
from arkclaw.application.pet_track0 import (
    ActionOutcome,
    PetTrack0Controller,
    PlaybackEvent,
)
from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.qt.main_window import MainWindow
from arkclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from arkclaw.presentation.qt.pet_renderer import (
    PlaceholderPetRenderer,
)
from arkclaw.presentation.qt.pet_window import PetWindow
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.system_tray import (
    PetTrayState,
    SystemTrayController,
    TrayCallbacks,
    _create_programmatic_tray_icon,
    _QtSystemTrayView,
)
from tests.fakes.pet_animation_player import FakeAnimationPlayer


class _ManualShutdownBridge(QObject):
    shutdown_finished = Signal(bool, str)


def test_workspace_exclusive_edges_are_derived_from_origin_plus_size() -> None:
    module = __import__(
        "arkclaw.presentation.qt.pet_window",
        fromlist=["workspace_rect_from_qrect"],
    )

    workspace = module.workspace_rect_from_qrect(QRect(7, 11, 100, 80))

    assert workspace.x == 7
    assert workspace.y == 11
    assert workspace.right == 7 + 100
    assert workspace.bottom == 11 + 80


def test_sit_workspace_and_display_are_selected_from_same_negative_screen() -> None:
    module = __import__(
        "arkclaw.presentation.qt.pet_window",
        fromlist=["select_workspace_display_pair"],
    )
    primary = (
        Rect(0.0, 0.0, 1920.0, 1040.0),
        Rect(0.0, 0.0, 1920.0, 1080.0),
    )
    negative_secondary = (
        Rect(-1280.0, 0.0, 1280.0, 984.0),
        Rect(-1280.0, 0.0, 1280.0, 1024.0),
    )

    workspace, display = module.select_workspace_display_pair(
        Point(-600.0, 804.0),
        Size(160.0, 180.0),
        (primary, negative_secondary),
    )

    assert workspace is negative_secondary[0]
    assert display is negative_secondary[1]


def test_pet_window_import_does_not_import_agent_loop() -> None:
    repository = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(repository / "src"), environment.get("PYTHONPATH", "")),
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, typing; "
                "from arkclaw.presentation.qt.pet_window import PetWindow; "
                "print('agent_loop_imported=' + "
                "str('arkclaw.application.agent_loop' in sys.modules).lower()); "
                "hints = typing.get_type_hints(PetWindow.__init__); "
                "print('autostart_hint_resolved=' + "
                "str('autostart_controller' in hints).lower()); "
                "from arkclaw.presentation.qt import QtRuntimeBridge; "
                "print('runtime_bridge=' + QtRuntimeBridge.__module__ + '.' + "
                "QtRuntimeBridge.__name__)"
            ),
        ],
        cwd=repository,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout == (
        "agent_loop_imported=false\n"
        "autostart_hint_resolved=true\n"
        "runtime_bridge=arkclaw.presentation.qt.runtime_bridge."
        "QtRuntimeBridge\n"
    )


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
        self.requests: list[PetRendererActionRequest] = []
        self.updates: list[float] = []
        self.pause_count = 0
        self.resume_count = 0
        self.closed = False
        self._events = events

    def initialize(self, viewport: Size) -> None:
        self.sizes.append(viewport)

    def set_viewport(self, viewport: Size) -> None:
        self.sizes.append(viewport)

    def set_state(self, request: PetRendererActionRequest) -> None:
        self.requests.append(request)

    def update(self, delta_seconds: float) -> None:
        self.updates.append(delta_seconds)

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del painter
        self.frames.append(frame)

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        self.pause_count += 1

    def resume(self) -> None:
        self.resume_count += 1

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._events is not None:
            self._events.append("renderer")


class _FailingStateRenderer(_FakeRenderer):
    def set_state(self, request: PetRendererActionRequest) -> None:
        del request
        raise RuntimeError("controlled animation state failure")


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

    def is_visible(self) -> bool:
        return self.show_count > 0 and self.close_count == 0

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


def test_animation_failure_does_not_close_restart_or_wake_agent(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _FailingStateRenderer()
    window = PetWindow(renderer=renderer)
    open_agent_spy = QSignalSpy(window.open_agent_requested)
    safe_exit_spy = QSignalSpy(window.safe_exit_requested)

    window.request_thinking_animation()
    window.physics_timer.timeout.emit()

    assert window.lifecycle_state is PetLifecycleState.ACTIVE
    assert window.physics_timer.isActive()
    assert open_agent_spy.count() == 0
    assert safe_exit_spy.count() == 0
    assert window.renderer_safe_code.value == "pet_renderer_state_failed"
    window.complete_safe_close()


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
    assert tray.visible
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
        "Pause",
        "Always on top",
        "Start with Windows",
        "Open Agent window",
        "Exit",
    } <= {
        action.text() for action in menu.actions() if action.text()
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


class _EdgeAvoidanceRenderer:
    """Overflow/BODY layout fake that records the composition order."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.avoid = True
        self.window: QWidget | None = None
        self.installed_layouts: list[PetRenderLayout] = []
        self.body_render_positions: list[tuple[int, int]] = []
        self.render_generation = 0
        self.device_pixel_ratio = 1.0
        self._request: object | None = None
        self.surface_image = QImage(200, 220, QImage.Format.Format_RGBA8888)
        self.surface_image.fill(Qt.GlobalColor.transparent)
        self.surface_image.setPixelColor(5, 5, Qt.GlobalColor.white)

    def initialize(self, viewport: Size) -> None:
        del viewport

    def set_viewport(self, viewport: Size) -> None:
        del viewport

    def set_state(self, request: object) -> None:
        action = getattr(request, "action", None)
        previous_action = getattr(self._request, "action", None)
        if self._request is not None and action != previous_action:
            self.render_generation += 1
        self._request = request

    def update(self, delta_seconds: float) -> None:
        del delta_seconds
        self.events.append("frame_ready")

    def render(self, painter: object, frame: object) -> None:
        del painter, frame
        if self.window is not None:
            self.body_render_positions.append(
                (self.window.x(), self.window.y())
            )

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        return

    def resume(self) -> None:
        return

    def close(self) -> None:
        return

    def plan_layout(
        self,
        body_rect: Rect,
        workspace: Rect,
        device_pixel_ratio: float,
        *,
        display: Rect | None = None,
    ) -> PetRenderLayout:
        del device_pixel_ratio, display
        if self.avoid:
            resolved_x = min(
                body_rect.x + 32.0,
                workspace.right - body_rect.width,
            )
            resolved_x = max(resolved_x, workspace.x)
            return PetRenderLayout(
                PetRenderSurfaceMode.OVERFLOW,
                Rect(
                    resolved_x - 20.0,
                    body_rect.y - 30.0,
                    200.0,
                    220.0,
                ),
                Point(20.0, 30.0),
                Point(resolved_x, body_rect.y),
                0.0,
                PetFacing.RIGHT,
                1.0,
                PetRenderLayoutQuality.FULL_SCALE,
            )
        return PetRenderLayout(
            PetRenderSurfaceMode.BODY,
            body_rect,
            Point(0.0, 0.0),
            Point(body_rect.x, body_rect.y),
            0.0,
            PetFacing.RIGHT,
            1.0,
            PetRenderLayoutQuality.FULL_SCALE,
        )

    def set_render_layout(self, layout: PetRenderLayout) -> None:
        self.installed_layouts.append(layout)
        self.events.append("set_render_layout")

    def render_surface(self, painter: QPainter) -> QImage:
        painter.drawImage(0, 0, self.surface_image)
        return self.surface_image


class _SitDisplayCaptureRenderer(_EdgeAvoidanceRenderer):
    def __init__(self) -> None:
        super().__init__(events=[])
        self.captured_display: Rect | None = None

    def plan_layout(
        self,
        body_rect: Rect,
        workspace: Rect,
        device_pixel_ratio: float,
        *,
        display: Rect | None = None,
    ) -> PetRenderLayout:
        del workspace, device_pixel_ratio
        self.captured_display = display
        return PetRenderLayout(
            PetRenderSurfaceMode.BODY,
            body_rect,
            Point(0.0, 0.0),
            Point(body_rect.x, body_rect.y),
            0.0,
            PetFacing.RIGHT,
            1.0,
            PetRenderLayoutQuality.FULL_SCALE,
        )


class _SpecialCompletionFacingRenderer(_EdgeAvoidanceRenderer):
    def __init__(self, effective_facing: PetFacing) -> None:
        super().__init__(events=[])
        self._effective_facing = effective_facing

    def plan_layout(
        self,
        body_rect: Rect,
        workspace: Rect,
        device_pixel_ratio: float,
        *,
        display: Rect | None = None,
    ) -> PetRenderLayout:
        del workspace, device_pixel_ratio, display
        return PetRenderLayout(
            PetRenderSurfaceMode.OVERFLOW,
            Rect(body_rect.x - 20.0, body_rect.y - 30.0, 200.0, 220.0),
            Point(20.0, 30.0),
            Point(body_rect.x, body_rect.y),
            0.0,
            self._effective_facing,
            1.0,
            PetRenderLayoutQuality.FULL_SCALE,
        )


class _QueuedPlaybackEvents:
    def __init__(self) -> None:
        self.events: tuple[PlaybackEvent, ...] = ()

    def update(self, delta_seconds: float) -> tuple[PlaybackEvent, ...]:
        del delta_seconds
        events = self.events
        self.events = ()
        return events


@pytest.mark.parametrize(
    ("initial_facing", "effective_facing"),
    [
        (PetFacing.RIGHT, PetFacing.LEFT),
        (PetFacing.LEFT, PetFacing.RIGHT),
        (PetFacing.RIGHT, PetFacing.RIGHT),
        (PetFacing.LEFT, PetFacing.LEFT),
    ],
)
def test_special_effective_facing_becomes_official_only_after_completion(
    qt_application: QApplication,
    initial_facing: PetFacing,
    effective_facing: PetFacing,
) -> None:
    renderer = _SpecialCompletionFacingRenderer(effective_facing)
    roles = AnimationRoleRegistry(
        {
            action: RoleAnimationBinding(
                action,
                "Move"
                if action in {
                    ProductionAction.MOVE_LEFT,
                    ProductionAction.MOVE_RIGHT,
                }
                else action.value.title(),
            )
            for action in ProductionAction
        }
    )
    player = FakeAnimationPlayer()
    controller = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            roles,
            source_durations={action: 1.0 for action in ProductionAction},
        ),
        clock=_FakeClock(),
    )
    events = _QueuedPlaybackEvents()
    window = PetWindow(
        renderer=renderer,
        clock=_FakeClock(),
        track0=controller,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
        playback_event_source=events,
    )
    if initial_facing is PetFacing.LEFT:
        assert (
            window.request_user_pet_action(ProductionAction.MOVE_LEFT)
            is ActionOutcome.ACCEPTED
        )
    assert window.render_frame.intent.facing is initial_facing
    assert (
        window.request_user_pet_action(ProductionAction.SPECIAL)
        is ActionOutcome.ACCEPTED
    )
    window.show()
    window.physics_timer.timeout.emit()
    qt_application.processEvents()

    assert window._active_render_layout is not None
    assert window._active_render_layout.effective_facing is effective_facing
    assert window.render_frame.intent.facing is initial_facing
    confirmed = controller.state.confirmed_epoch
    assert confirmed is not None
    events.events = (
        PlaybackEvent(
            generation=confirmed.generation,
            logical_action=confirmed.logical_action,
            physical_name=confirmed.physical_name,
            playback_token=confirmed.playback_token,
        ),
    )

    window.physics_timer.timeout.emit()
    qt_application.processEvents()

    assert window.render_frame.intent.facing is effective_facing
    window.complete_safe_close()
    qt_application.processEvents()


def test_pet_window_forwards_full_geometry_only_for_sit(
    qt_application: QApplication,
) -> None:
    del qt_application
    renderer = _SitDisplayCaptureRenderer()
    window = PetWindow(renderer=renderer, clock=_FakeClock())
    selected_workspace = Rect(0.0, 0.0, 1707.0, 1019.0)
    selected_display = Rect(0.0, 0.0, 1707.0, 1067.0)
    window._workspace_display_pairs = lambda: (  # type: ignore[method-assign]
        (selected_workspace, selected_display),
    )

    result = window._prepare_render_layout(
        PetRendererActionRequest(
            PetRendererAction.SITTING,
            PetFacing.RIGHT,
            True,
            0.0,
        )
    )

    assert isinstance(result, PetRenderLayout)
    assert renderer.captured_display is selected_display
    window.complete_safe_close()


class _CompositionRecorderWindow(PetWindow):
    """PetWindow that records window moves and forwarded mouse events."""

    def __init__(self, events: list[str], **kwargs: object) -> None:
        self._recorder_events = events
        super().__init__(**kwargs)

    def move(self, *args: int) -> None:
        self._recorder_events.append("window_move")
        super().move(*args)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._recorder_events.append("window_press")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._recorder_events.append("window_mouse_move")
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._recorder_events.append("window_release")
        super().mouseReleaseEvent(event)


def _production_overflow_window(
    action: ProductionAction,
) -> tuple[PetWindow, _EdgeAvoidanceRenderer, PetTrack0Controller, FakeAnimationPlayer]:
    roles = AnimationRoleRegistry(
        {
            candidate: RoleAnimationBinding(
                candidate,
                "Move"
                if candidate in {
                    ProductionAction.MOVE_LEFT,
                    ProductionAction.MOVE_RIGHT,
                }
                else candidate.value.title(),
            )
            for candidate in ProductionAction
        }
    )
    player = FakeAnimationPlayer()
    controller = PetTrack0Controller(
        player=player,
        registry=build_track0_animation_registry(
            roles,
            source_durations={candidate: 1.0 for candidate in ProductionAction},
        ),
        clock=_FakeClock(),
    )
    renderer = _EdgeAvoidanceRenderer(events=[])
    window = PetWindow(
        renderer=renderer,
        clock=_FakeClock(),
        track0=controller,
        active_role_pack_id="schwarz-production",
        available_production_actions=frozenset(ProductionAction),
    )
    assert window.request_pet_action(action) is ActionOutcome.ACCEPTED
    window.show()
    window.physics_timer.timeout.emit()
    QApplication.processEvents()
    overlay = window._effect_overlay
    assert overlay is not None
    paint_target = QImage(
        overlay.width(),
        overlay.height(),
        QImage.Format.Format_RGBA8888,
    )
    painter = QPainter(paint_target)
    try:
        overlay.render(painter, QPoint())
    finally:
        painter.end()
    return window, renderer, controller, player


@pytest.mark.parametrize(
    "initial_action",
    [ProductionAction.SIT, ProductionAction.SPECIAL],
)
def test_visible_overflow_pixel_clicks_through_pet_window_to_interact_once(
    qt_application: QApplication,
    initial_action: ProductionAction,
) -> None:
    window, renderer, controller, player = _production_overflow_window(
        initial_action
    )
    overlay = window._effect_overlay
    assert overlay is not None
    generation_before_click = renderer.render_generation
    play_count_before_click = len(player.calls)

    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    qt_application.processEvents()

    active = controller.active_request
    confirmed = controller.state.confirmed_epoch
    assert active is not None
    assert confirmed is not None
    assert confirmed.physical_name == "Interact"
    assert active.source is ActionSource.USER
    assert len(player.calls) == play_count_before_click + 1
    assert renderer.render_generation == generation_before_click + 1
    assert window.motion_state is PetMotionState.IDLE
    window.complete_safe_close()
    qt_application.processEvents()
    shiboken6.delete(overlay)


@pytest.mark.parametrize(
    "initial_action",
    [ProductionAction.SIT, ProductionAction.SPECIAL],
)
def test_visible_overflow_pixel_drag_enters_relax_motion_fallback(
    qt_application: QApplication,
    initial_action: ProductionAction,
) -> None:
    window, _renderer, controller, _player = _production_overflow_window(
        initial_action
    )
    overlay = window._effect_overlay
    assert overlay is not None
    press = QPoint(5, 5)
    moved = QPointF(65.0, 45.0)
    moved_global = QPointF(overlay.x() + moved.x(), overlay.y() + moved.y())

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=press)
    QApplication.sendEvent(
        overlay,
        QMouseEvent(
            QEvent.Type.MouseMove,
            moved,
            moved_global,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    active = controller.active_request
    confirmed = controller.state.confirmed_epoch
    assert active is not None
    assert confirmed is not None
    assert confirmed.physical_name == "Relax"
    assert window.motion_state is PetMotionState.DRAGGING

    QApplication.sendEvent(
        overlay,
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            moved,
            moved_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert window.motion_state in {
        PetMotionState.FALLING,
        PetMotionState.LANDING,
    }
    window.complete_safe_close()
    qt_application.processEvents()
    shiboken6.delete(overlay)


@pytest.mark.parametrize(
    "initial_action",
    [ProductionAction.SIT, ProductionAction.SPECIAL],
)
def test_visible_overflow_pixel_opens_pet_context_menu_without_action_change(
    qt_application: QApplication,
    initial_action: ProductionAction,
) -> None:
    window, renderer, controller, player = _production_overflow_window(
        initial_action
    )
    overlay = window._effect_overlay
    assert overlay is not None
    active_before = controller.active_request
    generation_before = renderer.render_generation
    play_count_before = len(player.calls)
    local = QPoint(5, 5)
    global_point = overlay.mapToGlobal(local)

    QApplication.sendEvent(
        overlay,
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            local,
            global_point,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qt_application.processEvents()

    menu = window.findChild(QMenu)
    assert menu is not None
    assert menu.isVisible()
    overlay_id = int(overlay.winId())
    for _ in range(3):
        window.physics_timer.timeout.emit()
        qt_application.processEvents()
    assert menu.isVisible()
    assert int(overlay.winId()) == overlay_id
    assert controller.active_request is active_before
    assert renderer.render_generation == generation_before
    assert len(player.calls) == play_count_before
    menu.close()
    window.complete_safe_close()
    qt_application.processEvents()
    shiboken6.delete(overlay)


def test_overflow_commit_order_moves_window_before_layout_and_overlay(
    qt_application: QApplication,
) -> None:
    events: list[str] = []
    renderer = _EdgeAvoidanceRenderer(events)
    window = _CompositionRecorderWindow(
        renderer=renderer,
        clock=_FakeClock(),
        events=events,
    )
    window.show()
    motion = window._animation.motion
    original_commit = motion.place_for_render_layout

    def recording_commit(position: Point, workspace: Rect) -> object:
        events.append("motion_commit")
        return original_commit(position, workspace)

    motion.place_for_render_layout = recording_commit  # type: ignore[method-assign]
    overlay = window._effect_overlay
    original_show = overlay.show_layout

    def recording_show(
        layout: PetRenderLayout,
        *,
        always_on_top: bool,
    ) -> None:
        events.append("overlay_show")
        original_show(layout, always_on_top=always_on_top)

    overlay.show_layout = recording_show  # type: ignore[method-assign]
    events.clear()

    window.physics_timer.timeout.emit()
    qt_application.processEvents()

    assert events == [
        "motion_commit",
        "window_move",
        "set_render_layout",
        "frame_ready",
        "overlay_show",
    ]
    assert window.pos().x() == round(motion.position.x)
    assert overlay.isVisible()
    window.complete_safe_close()
    qt_application.processEvents()
    shiboken6.delete(overlay)


def test_special_end_keeps_avoided_position_without_intermediate_shrink_frame(
    qt_application: QApplication,
) -> None:
    renderer = _EdgeAvoidanceRenderer(events=[])
    window = PetWindow(renderer=renderer, clock=_FakeClock())
    renderer.window = window
    window.show()
    overlay = window._effect_overlay
    motion = window._animation.motion
    before = motion.position

    window.physics_timer.timeout.emit()
    qt_application.processEvents()

    assert motion.position != before
    avoided = motion.position
    assert overlay.isVisible()
    assert window.pos().x() == round(avoided.x)

    renderer.avoid = False
    window.physics_timer.timeout.emit()
    qt_application.processEvents()

    assert motion.position == avoided
    assert window.pos().x() == round(avoided.x)
    assert not overlay.isVisible()
    assert renderer.body_render_positions[-1] == (
        round(avoided.x),
        round(avoided.y),
    )
    assert all(
        layout.quality is PetRenderLayoutQuality.FULL_SCALE
        and layout.scale_multiplier == 1.0
        for layout in renderer.installed_layouts
    )
    window.complete_safe_close()
    qt_application.processEvents()
    shiboken6.delete(overlay)


def test_avoided_overflow_proxies_body_press_move_release_and_context_menu(
    qt_application: QApplication,
) -> None:
    events: list[str] = []
    renderer = _EdgeAvoidanceRenderer(events=[])
    window = _CompositionRecorderWindow(
        renderer=renderer,
        clock=_FakeClock(),
        events=events,
    )
    window.show()
    overlay = window._effect_overlay
    window.physics_timer.timeout.emit()
    qt_application.processEvents()
    layout = renderer.installed_layouts[-1]
    offset = layout.body_window_offset

    # The overlay body hit rect must reference the resolved body position so
    # the input proxy stays aligned with the moved window.
    assert overlay.x() + round(offset.x) == window.x()
    assert overlay.y() + round(offset.y) == window.y()

    body_center = QPoint(round(offset.x) + 80, round(offset.y) + 90)
    outside_local = QPointF(round(offset.x) + 400, round(offset.y) + 400)
    outside_global = QPointF(
        overlay.x() + outside_local.x(),
        overlay.y() + outside_local.y(),
    )
    start_pos = window.pos()
    events.clear()

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=body_center)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        outside_local,
        outside_global,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(overlay, move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        outside_local,
        outside_global,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(overlay, release)
    qt_application.processEvents()

    assert "window_press" in events
    assert "window_mouse_move" in events
    assert "window_release" in events
    assert window.pos() != start_pos

    context = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        body_center,
        QPoint(overlay.x() + body_center.x(), overlay.y() + body_center.y()),
    )
    QApplication.sendEvent(overlay, context)
    qt_application.processEvents()

    assert window.findChild(QMenu) is not None
    window.complete_safe_close()
    qt_application.processEvents()
    shiboken6.delete(overlay)
