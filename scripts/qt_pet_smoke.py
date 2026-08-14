"""Fully offline subprocess smoke for the placeholder desktop pet."""

from __future__ import annotations

import os
import random
import sys
import tempfile
from collections import Counter
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("QT_QPA_FONTDIR", None)

import PySide6
from PySide6.QtCore import (
    QMessageLogContext,
    Qt,
    QTimer,
    QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtGui import QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet_animation import (
    PetAnimationConfig,
    PetRenderFrame,
)
from arkclaw.application.pet_state import (
    PetBehaviorState,
    PetFacing,
    PetMotionState,
)
from arkclaw.bootstrap.qt_runtime import FakeQtRuntimeCompositionRoot
from arkclaw.presentation.qt.main_window import MainWindow
from arkclaw.presentation.qt.pet_application import (
    PetApplicationCoordinator,
)
from arkclaw.presentation.qt.pet_renderer import PlaceholderPetRenderer
from arkclaw.presentation.qt.pet_window import PetWindow
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge

_PYSIDE_FONT_DIRECTORY = (
    Path(PySide6.__file__).resolve().parent / "lib" / "fonts"
).as_posix()
_EXPECTED_QT_PLATFORM_WARNING_COUNTS = {
        (
            "QFontDatabase: Cannot find font directory "
            f"{_PYSIDE_FONT_DIRECTORY}.\n"
            "Note that Qt no longer ships fonts. Deploy some "
            "(from https://dejavu-fonts.github.io/ for example) "
            "or switch to fontconfig."
        ): 1,
        "This plugin does not support raise()": 1,
        "This plugin does not support propagateSizeHints()": 1,
}


class _QtMessageAudit:
    def __init__(self, expected_warnings: dict[str, int]) -> None:
        self._expected_warnings = expected_warnings.copy()
        self._observed_expected_warnings: Counter[str] = Counter()
        self.unexpected_warnings: list[str] = []
        self.critical_messages: list[str] = []
        self.other_messages: list[str] = []

    @property
    def expected_warning_count(self) -> int:
        return sum(
            min(
                self._observed_expected_warnings[message],
                expected_count,
            )
            for message, expected_count in self._expected_warnings.items()
        )

    @property
    def missing_warning_count(self) -> int:
        return sum(
            max(
                0,
                expected_count
                - self._observed_expected_warnings[message],
            )
            for message, expected_count in self._expected_warnings.items()
        )

    @property
    def duplicate_warning_count(self) -> int:
        return sum(
            max(
                0,
                self._observed_expected_warnings[message]
                - expected_count,
            )
            for message, expected_count in self._expected_warnings.items()
        )

    def handle(
        self,
        message_type: QtMsgType,
        context: QMessageLogContext,
        message: str,
    ) -> None:
        del context
        if message_type is QtMsgType.QtWarningMsg:
            if message in self._expected_warnings:
                self._observed_expected_warnings[message] += 1
                return
            self.unexpected_warnings.append(message)
            print(message, file=sys.stderr)
            return
        if message_type in {
            QtMsgType.QtCriticalMsg,
            QtMsgType.QtFatalMsg,
        }:
            self.critical_messages.append(message)
            print(message, file=sys.stderr)
            return
        self.other_messages.append(message)
        print(message, file=sys.stderr)


class _SmokeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _RecordingPlaceholderRenderer(PlaceholderPetRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.frames: list[PetRenderFrame] = []

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        self.frames.append(frame)
        super().render(painter, frame)


def _run_smoke(message_audit: _QtMessageAudit) -> int:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    timed_out = False
    shutdown_results: list[tuple[bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="arkclaw-pet-smoke-") as directory:
        bridge = QtRuntimeBridge(
            FakeQtRuntimeCompositionRoot(
                Path(directory) / "profiles.json"
            )
        )
        main_window = MainWindow(bridge, hide_on_close=True)
        clock = _SmokeClock()
        renderer = _RecordingPlaceholderRenderer()
        pet_window = PetWindow(
            always_on_top=False,
            renderer=renderer,
            clock=clock,
            rng=random.Random(17),
            animation_config=PetAnimationConfig(
                maximum_delta_seconds=0.1,
                breathing_cycle_seconds=0.2,
                blinking_duration_seconds=0.01,
                blinking_interval_min_seconds=0.01,
                blinking_interval_max_seconds=0.01,
                walking_duration_seconds=0.2,
                thinking_duration_seconds=0.02,
                reminder_duration_seconds=0.02,
                random_action_interval_min_seconds=100,
                random_action_interval_max_seconds=100,
            ),
        )
        coordinator = PetApplicationCoordinator(
            bridge,
            main_window,
            pet_window,
        )
        observed = {
            "breathing": False,
            "blinking": False,
            "walking": False,
            "drag_struggle_entered": False,
            "drag_struggle_exited": False,
            "reminder_completed": False,
            "agent_reopened": False,
            "agent_hidden": False,
        }

        def timeout() -> None:
            nonlocal timed_out
            timed_out = True
            app.quit()

        def advance(seconds: float) -> None:
            clock.advance(seconds)
            pet_window.physics_timer.timeout.emit()
            pet_window.repaint()

        def exercise_pet() -> None:
            pet_window.repaint()
            observed["breathing"] = (
                PetBehaviorState.BREATHING
                in pet_window.render_frame.state.behaviors
            )
            advance(0.01)
            observed["blinking"] = (
                PetBehaviorState.BLINKING
                in pet_window.render_frame.state.behaviors
            )
            assert pet_window.request_walk(PetFacing.RIGHT)
            advance(0.01)
            observed["walking"] = (
                pet_window.motion_state is PetMotionState.WALKING_RIGHT
            )
            center = pet_window.rect().center()
            QTest.mousePress(
                pet_window,
                Qt.MouseButton.LeftButton,
                pos=center,
            )
            observed["drag_struggle_entered"] = (
                PetBehaviorState.DRAG_STRUGGLE
                in pet_window.render_frame.state.behaviors
            )
            QTest.mouseRelease(
                pet_window,
                Qt.MouseButton.LeftButton,
                pos=center,
            )
            observed["drag_struggle_exited"] = (
                pet_window.motion_state is PetMotionState.FALLING
                and PetBehaviorState.DRAG_STRUGGLE
                not in pet_window.render_frame.state.behaviors
            )
            advance(0.1)
            advance(0.1)
            advance(0.1)
            assert pet_window.request_reminder_animation()
            advance(0.03)
            observed["reminder_completed"] = (
                pet_window.motion_state is PetMotionState.IDLE
                and PetBehaviorState.REMINDING
                not in pet_window.render_frame.state.behaviors
            )
            main_window.show()
            observed["agent_reopened"] = main_window.isVisible()
            main_window.close()
            observed["agent_hidden"] = (
                not main_window.isVisible()
                and bridge.runtime_thread.isRunning()
            )
            pet_window.request_safe_exit()

        bridge.runtime_ready.connect(exercise_pet)
        bridge.shutdown_finished.connect(
            lambda success, safe_code: shutdown_results.append(
                (success, safe_code)
            )
        )
        coordinator.quit_requested.connect(app.quit)
        pet_window.show()
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(timeout)
        watchdog.start(10_000)
        exit_code = app.exec()
        watchdog.stop()

        success = (
            exit_code == 0
            and not timed_out
            and shutdown_results == [(True, "none")]
            and not bridge.runtime_thread.isRunning()
            and bridge.runtime_thread.pending_task_count_at_close == 0
            and not pet_window.physics_timer.isActive()
            and renderer.closed
            and bool(renderer.frames)
            and all(observed.values())
            and message_audit.missing_warning_count == 0
            and message_audit.duplicate_warning_count == 0
            and not message_audit.unexpected_warnings
            and not message_audit.critical_messages
            and not message_audit.other_messages
        )
        print(
            f"qt_pet_smoke={success} "
            "expected_qt_platform_warnings="
            f"{message_audit.expected_warning_count} "
            "missing_qt_platform_warnings="
            f"{message_audit.missing_warning_count} "
            "duplicate_qt_platform_warnings="
            f"{message_audit.duplicate_warning_count} "
            "unexpected_qt_warnings="
            f"{len(message_audit.unexpected_warnings)} "
            "qt_critical_messages="
            f"{len(message_audit.critical_messages)} "
            "qt_other_messages="
            f"{len(message_audit.other_messages)} "
            f"shutdown_count={len(shutdown_results)} "
            f"thread_running={bridge.runtime_thread.isRunning()} "
            "pending_asyncio_tasks="
            f"{bridge.runtime_thread.pending_task_count_at_close} "
            f"timer_active={pet_window.physics_timer.isActive()} "
            f"renderer_closed={renderer.closed} "
            f"animations_complete={all(observed.values())} "
            "failed_checks="
            + ",".join(
                name for name, passed in observed.items() if not passed
            )
        )
        return 0 if success else 2


def main() -> int:
    message_audit = _QtMessageAudit(
        _EXPECTED_QT_PLATFORM_WARNING_COUNTS
    )
    previous_handler = qInstallMessageHandler(message_audit.handle)
    try:
        return _run_smoke(message_audit)
    finally:
        qInstallMessageHandler(previous_handler)


if __name__ == "__main__":
    sys.exit(main())
