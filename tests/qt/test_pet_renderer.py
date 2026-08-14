"""Qt tests for the replaceable renderer lifecycle and fallback boundary."""

from __future__ import annotations

import os
import traceback
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet.pet_animation import PetRenderFrame
from arkclaw.application.pet.pet_geometry import Size
from arkclaw.application.pet.pet_renderer_model import (
    ExternalPetAssetDescriptor,
    PetRendererAction,
    PetRendererActionRequest,
    PetRendererAnimationCapability,
    PetRendererConfig,
    PetRendererKind,
    placeholder_animation_capability,
)
from arkclaw.presentation.qt.pet.pet_renderer import (
    PetRendererSafeCode,
    SafePetRenderer,
    create_configured_pet_renderer,
    create_safe_pet_renderer,
)
from arkclaw.presentation.qt.pet.pet_window import PetWindow


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app


class _RecordingRenderer:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.initialized: list[Size] = []
        self.viewports: list[Size] = []
        self.states: list[PetRendererActionRequest] = []
        self.updates: list[float] = []
        self.frames: list[PetRenderFrame] = []
        self.pause_count = 0
        self.resume_count = 0
        self.close_count = 0

    def _maybe_fail(self, operation: str) -> None:
        if self.fail_at == operation:
            raise RuntimeError("sensitive-renderer-detail")

    def initialize(self, viewport: Size) -> None:
        self._maybe_fail("initialize")
        self.initialized.append(viewport)

    def set_viewport(self, viewport: Size) -> None:
        self._maybe_fail("viewport")
        self.viewports.append(viewport)

    def set_state(self, request: PetRendererActionRequest) -> None:
        self._maybe_fail("state")
        self.states.append(request)

    def update(self, delta_seconds: float) -> None:
        self._maybe_fail("update")
        self.updates.append(delta_seconds)

    def render(self, painter: QPainter, frame: PetRenderFrame) -> None:
        del painter
        self._maybe_fail("render")
        self.frames.append(frame)

    def animation_capability(
        self,
        action: PetRendererAction,
    ) -> PetRendererAnimationCapability:
        self._maybe_fail("capability")
        return placeholder_animation_capability(action)

    def pause(self) -> None:
        self._maybe_fail("pause")
        self.pause_count += 1

    def resume(self) -> None:
        self._maybe_fail("resume")
        self.resume_count += 1

    def close(self) -> None:
        self._maybe_fail("close")
        self.close_count += 1


def _paint(renderer: SafePetRenderer, frame: PetRenderFrame) -> None:
    image = QImage(160, 180, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        renderer.render(painter, frame)
    finally:
        painter.end()


def test_factory_construction_failure_uses_placeholder_without_details() -> None:
    def fail() -> _RecordingRenderer:
        raise RuntimeError("sensitive-construction-detail")

    renderer = create_safe_pet_renderer(fail)

    assert renderer.using_placeholder
    assert renderer.safe_code is PetRendererSafeCode.CONSTRUCTION_FAILED
    assert "sensitive" not in repr(renderer)


def test_external_configuration_falls_back_without_disk_access() -> None:
    renderer = create_configured_pet_renderer(
        PetRendererConfig(
            renderer_kind=PetRendererKind.SPINE38,
            external_assets=ExternalPetAssetDescriptor(
                opaque_asset_id="fictional-bundle",
                asset_root="X:\\fictional-pet-assets",
                skeleton_filename="fictional.skel",
                atlas_filename="fictional.atlas",
                texture_filename="fictional.png",
            ),
        )
    )

    assert renderer.using_placeholder
    assert renderer.safe_code is PetRendererSafeCode.RUNTIME_UNAVAILABLE


def test_renderer_lifecycle_is_forwarded_and_close_is_idempotent(
    qt_application: QApplication,
) -> None:
    del qt_application
    delegate = _RecordingRenderer()
    renderer = SafePetRenderer(delegate)
    window = PetWindow(renderer=renderer)
    frame = window.render_frame

    renderer.set_viewport(Size(200, 220))
    renderer.set_state(delegate.states[-1])
    renderer.update(0.05)
    _paint(renderer, frame)
    renderer.pause()
    renderer.update(0.05)
    renderer.resume()
    renderer.close()
    renderer.close()

    assert delegate.initialized == [Size(160, 180)]
    assert Size(200, 220) in delegate.viewports
    assert delegate.updates == [0.05]
    assert delegate.frames == [frame]
    assert delegate.pause_count == 1
    assert delegate.resume_count == 1
    assert delegate.close_count == 1
    assert renderer.closed
    window.complete_safe_close()


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("initialize", PetRendererSafeCode.INITIALIZATION_FAILED),
        ("update", PetRendererSafeCode.UPDATE_FAILED),
        ("render", PetRendererSafeCode.RENDER_FAILED),
        ("pause", PetRendererSafeCode.PAUSE_FAILED),
    ],
)
def test_renderer_failure_is_redacted_and_falls_back(
    qt_application: QApplication,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    expected: PetRendererSafeCode,
) -> None:
    del qt_application
    delegate = _RecordingRenderer(fail_at=operation)
    renderer = SafePetRenderer(delegate)
    window = PetWindow(renderer=renderer)
    if operation == "update":
        renderer.update(0.01)
    elif operation == "render":
        _paint(renderer, window.render_frame)
    elif operation == "pause":
        renderer.pause()

    captured = capsys.readouterr()
    visible = "\n".join(
        (
            repr(renderer),
            renderer.safe_code.value,
            captured.out,
            captured.err,
            caplog.text,
            "".join(traceback.format_stack()),
        )
    )
    assert renderer.using_placeholder
    assert renderer.safe_code is expected
    assert "sensitive-renderer-detail" not in visible
    window.complete_safe_close()


def test_pet_window_forwards_state_time_pause_and_resume(
    qt_application: QApplication,
) -> None:
    del qt_application
    delegate = _RecordingRenderer()
    window = PetWindow(renderer=delegate)

    window.physics_timer.timeout.emit()
    window.toggle_paused()
    window.physics_timer.timeout.emit()
    window.toggle_paused()

    assert delegate.states[0].action is PetRendererAction.IDLE
    assert delegate.updates
    assert delegate.pause_count == 1
    assert delegate.resume_count == 1
    assert window.renderer_safe_code is PetRendererSafeCode.NONE
    window.complete_safe_close()


def test_renderer_replacement_does_not_own_workspace_clamping(
    qt_application: QApplication,
) -> None:
    del qt_application
    delegate = _RecordingRenderer()
    window = PetWindow(renderer=delegate)

    window.restore_persisted_position(50_000, 50_000)
    x, y, _ = window.persisted_presentation_state()
    workspace = window._primary_workspace()

    assert workspace.x <= x <= workspace.right - window.width()
    assert workspace.y <= y <= workspace.bottom - window.height()
    assert delegate.initialized == [Size(160, 180)]
    window.complete_safe_close()
