"""Opt-in Windows subprocess smoke for the approved Schwarz idle slice."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import importlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest

from arkclaw.application.pet_action_sequence import PetActionName
from arkclaw.application.pet_geometry import Point, Rect, Size
from arkclaw.application.pet_render_layout import PetRenderLayout
from arkclaw.application.pet_renderer_model import (
    PetRendererAction,
    PetRendererActionRequest,
)
from arkclaw.application.pet_state import PetFacing
from arkclaw.application.pet_track0 import PlaybackRequest

_SAMPLE_LABELS = [
    "loop_1_start",
    "loop_1_mid",
    "loop_1_before_end",
    "loop_2_after_start",
    "loop_2_mid",
    "loop_2_before_end",
    "loop_3_after_start",
    "loop_3_mid",
    "loop_3_before_end",
    "loop_3_after_end",
]


def _physical_alpha_points(image: Any) -> tuple[tuple[int, int], ...]:
    converted = image.convertToFormat(image.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    data = memoryview(converted.constBits())[: converted.sizeInBytes()]
    return tuple(
        (x, y)
        for y in range(height)
        for x in range(width)
        if data[y * stride + x * 4 + 3] > 0
    )


def _outside_body_alpha_points(
    image: Any,
    layout: PetRenderLayout,
) -> tuple[tuple[int, int], tuple[int, int]]:
    body = layout.body_window_offset
    for y in range(1, image.height() - 1):
        for x in range(1, image.width() - 1):
            if (
                body.x <= x < body.x + 160.0
                and body.y <= y < body.y + 180.0
            ):
                continue
            if all(
                image.pixelColor(x + dx, y + dy).alpha() >= 8
                for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))
            ):
                visible = (x, y)
                break
        else:
            continue
        break
    else:
        raise AssertionError("real frame has no visible pixel outside BODY")
    for y in range(1, image.height() - 1):
        for x in range(1, image.width() - 1):
            if all(
                image.pixelColor(x + dx, y + dy).alpha() == 0
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
            ):
                return visible, (x, y)
    raise AssertionError("real frame has no transparent padding")


@pytest.mark.parametrize(
    ("facing", "expected_surface", "expected_offset"),
    [
        (PetFacing.RIGHT, Rect(482.0, 905.0, 167.0, 148.0), Point(18.0, -66.0)),
        (PetFacing.LEFT, Rect(511.0, 905.0, 167.0, 148.0), Point(-11.0, -66.0)),
    ],
)
def test_real_schwarz_sit_240hz_final_pixels_cover_tail_and_foot_regions(
    facing: PetFacing,
    expected_surface: Rect,
    expected_offset: Point,
) -> None:
    if (
        os.environ.get("ARKCLAW_SPINE38_BRIDGE_DLL") is None
        or os.environ.get("ARKCLAW_PET_ROLE_MANIFEST") is None
    ):
        pytest.skip("requires the production Schwarz manifest and bridge")

    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from arkclaw.bootstrap.pet_production import (
        create_optional_production_pet_composition,
    )

    application = QApplication.instance() or QApplication([])
    del application
    composition = create_optional_production_pet_composition()
    assert composition is not None
    renderer = composition.renderer
    player = composition.playback_event_source
    runtime = cast(Any, player)._runtime
    duration = runtime.catalog.require_animation("Sit").duration_seconds
    dpr = 1.5
    layout: PetRenderLayout | None = None
    try:
        renderer.initialize(Size(160.0, 180.0))
        renderer.set_device_pixel_ratio(dpr)
        player.play(
            PlaybackRequest(
                generation=1,
                track=0,
                logical_action=PetActionName.SIT_IDLE,
                physical_name="Sit",
                loop=True,
                speed=1.0,
                mix_seconds=0.0,
            )
        )
        renderer.set_state(
            PetRendererActionRequest(
                PetRendererAction.SITTING,
                facing,
                True,
                0.0,
            )
        )
        planned = renderer.plan_layout(
            Rect(500.0, 839.0, 160.0, 180.0),
            Rect(0.0, 0.0, 1707.0, 1019.0),
            dpr,
            display=Rect(0.0, 0.0, 1707.0, 1067.0),
        )
        assert isinstance(planned, PetRenderLayout)
        layout = planned
        assert layout.surface_rect == expected_surface
        assert layout.body_window_offset == expected_offset
        renderer.set_render_layout(layout)

        tail_seen = False
        foot_seen = False
        frame_count = math.ceil(duration * 240.0)
        for frame_index in range(frame_count + 1):
            if frame_index:
                player.update(1.0 / 240.0)
            renderer.update(0.0)
            physical_width = math.ceil(layout.surface_rect.width * dpr)
            physical_height = math.ceil(layout.surface_rect.height * dpr)
            image = QImage(
                physical_width,
                physical_height,
                QImage.Format.Format_RGBA8888,
            )
            image.fill(0)
            painter = QPainter(image)
            painter.scale(dpr, dpr)
            renderer.render_surface(painter)
            painter.end()
            alpha_points = _physical_alpha_points(image)
            assert alpha_points
            xs = tuple(point[0] for point in alpha_points)
            ys = tuple(point[1] for point in alpha_points)
            assert min(xs) >= 1
            assert min(ys) >= 1
            assert max(xs) <= physical_width - 2
            assert max(ys) <= physical_height - 2

            body_left = math.floor(expected_offset.x * dpr)
            body_right = math.ceil((expected_offset.x + 160.0) * dpr)
            body_bottom = math.floor((expected_offset.y + 180.0) * dpr)
            if facing is PetFacing.RIGHT:
                tail_seen |= any(x < body_left for x, _y in alpha_points)
            else:
                tail_seen |= any(x >= body_right for x, _y in alpha_points)
            foot_seen |= any(
                body_left <= x < body_right and y >= body_bottom
                for x, y in alpha_points
            )

        assert tail_seen
        assert foot_seen
    finally:
        renderer.close()


def test_real_schwarz_overflow_alpha_hit_reuses_one_render_scene() -> None:
    if (
        os.environ.get("ARKCLAW_SPINE38_BRIDGE_DLL") is None
        or os.environ.get("ARKCLAW_PET_ROLE_MANIFEST") is None
    ):
        pytest.skip("requires the production Schwarz manifest and bridge")

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    from arkclaw.bootstrap.pet_production import (
        create_optional_production_pet_composition,
    )
    from arkclaw.presentation.qt.pet_effect_overlay import PetEffectOverlayWindow

    application = QApplication.instance() or QApplication([])
    if application.platformName() != "windows":
        pytest.skip("requires the Windows native hit-test path")
    composition = create_optional_production_pet_composition()
    assert composition is not None
    renderer = composition.renderer
    player = composition.playback_event_source
    runtime = cast(Any, player)._runtime
    input_target = QWidget()
    overlay = PetEffectOverlayWindow(renderer, input_target=input_target)

    def assert_frame(layout: PetRenderLayout) -> None:
        input_target.setGeometry(
            round(layout.resolved_body_position.x),
            round(layout.resolved_body_position.y),
            160,
            180,
        )
        input_target.show()
        overlay.show_layout(layout, always_on_top=True)
        application.processEvents()
        backend = cast(Any, renderer)._backend
        original = backend.render_scene
        calls = 0

        def counted() -> QImage:
            nonlocal calls
            calls += 1
            return original()

        backend.render_scene = counted
        image = QImage(
            overlay.width(), overlay.height(), QImage.Format.Format_RGBA8888
        )
        image.fill(0)
        painter = QPainter(image)
        try:
            overlay.render(painter, QPoint())
        finally:
            painter.end()
            backend.render_scene = original
            assert calls == 1
            visible, transparent = _outside_body_alpha_points(image, layout)
            for (x, y), expected in ((visible, 1), (transparent, -1)):
                handle = int(overlay.winId())
                native_rect = ctypes.wintypes.RECT()
                assert ctypes.windll.user32.GetClientRect(
                    handle,
                    ctypes.byref(native_rect),
                )
                native_point = ctypes.wintypes.POINT(
                    round(x * native_rect.right / overlay.width()),
                    round(y * native_rect.bottom / overlay.height()),
                )
                assert ctypes.windll.user32.ClientToScreen(
                    handle,
                    ctypes.byref(native_point),
                )
                packed = (
                    ((native_point.y & 0xFFFF) << 16)
                    | (native_point.x & 0xFFFF)
                )
                assert (
                    ctypes.windll.user32.SendMessageW(
                        handle, 0x0084, 0, packed
                    )
                    == expected
                )

    try:
        renderer.initialize(Size(160.0, 180.0))
        samples = (
            (
                PetActionName.SIT_IDLE,
                "Sit",
                PetRendererAction.SITTING,
                True,
                (0.5,),
            ),
            (
                PetActionName.WAVE,
                "Special",
                PetRendererAction.SPECIAL,
                False,
                (0.01, 0.5, 0.99),
            ),
        )
        for generation, (logical, physical, action, loop, fractions) in enumerate(
            samples,
            start=1,
        ):
            duration = runtime.catalog.require_animation(physical).duration_seconds
            player.play(
                PlaybackRequest(
                    generation=generation,
                    track=0,
                    logical_action=logical,
                    physical_name=physical,
                    loop=loop,
                    speed=1.0,
                    mix_seconds=0.0,
                )
            )
            renderer.set_state(
                PetRendererActionRequest(action, PetFacing.RIGHT, loop, 0.0)
            )
            planned = renderer.plan_layout(
                Rect(500.0, 700.0, 160.0, 180.0),
                Rect(0.0, 0.0, 1920.0, 880.0),
                1.0,
                display=Rect(0.0, 0.0, 1920.0, 1080.0),
            )
            assert isinstance(planned, PetRenderLayout)
            renderer.set_render_layout(planned)
            previous = 0.0
            for fraction in fractions:
                current = duration * fraction
                player.update(current - previous)
                previous = current
                renderer.update(0.0)
                assert_frame(planned)
    finally:
        overlay.close()
        input_target.close()
        renderer.close()


def test_wrong_hash_phase_observes_zero_bridge_factory_calls() -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    assets = importlib.import_module(
        "arkclaw.application.pet_external_assets"
    )
    bridge_calls: list[object] = []

    class HashMismatchLoader:
        def load(self, descriptor: object) -> object:
            del descriptor
            return SimpleNamespace(
                succeeded=False,
                bundle=None,
                status=assets.ExternalPetAssetStatus.HASH_MISMATCH,
            )

    def forbidden_bridge_factory(snapshot: object) -> NoReturn:
        bridge_calls.append(snapshot)
        raise AssertionError("wrong-hash phase must not construct the bridge")

    evidence = script._forced_hash_failure_evidence(
        Path("X:/approved-assets"),
        asset_loader=HashMismatchLoader(),
        bridge_factory=forbidden_bridge_factory,
    )

    assert bridge_calls == []
    assert evidence == {
        "bridge_constructed": False,
        "loader_status": "external_asset_hash_mismatch",
        "renderer_safe_code": "pet_renderer_construction_failed",
        "using_placeholder": True,
    }


def test_wrong_hash_phase_attempts_monitored_bridge_on_loader_success() -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    assets = importlib.import_module(
        "arkclaw.application.pet_external_assets"
    )
    bridge_calls: list[object] = []

    class UnexpectedBundle:
        snapshot = object()

        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    bundle = UnexpectedBundle()

    class UnexpectedSuccessLoader:
        def load(self, descriptor: object) -> object:
            del descriptor
            return SimpleNamespace(
                succeeded=True,
                bundle=bundle,
                status=assets.ExternalPetAssetStatus.OK,
            )

    def forbidden_bridge_factory(snapshot: object) -> NoReturn:
        bridge_calls.append(snapshot)
        raise AssertionError("monitored bridge boundary reached")

    with pytest.raises(AssertionError, match="monitored bridge boundary reached"):
        script._forced_hash_failure_evidence(
            Path("X:/approved-assets"),
            asset_loader=UnexpectedSuccessLoader(),
            bridge_factory=forbidden_bridge_factory,
        )

    assert bridge_calls == [bundle.snapshot]
    assert bundle.close_count == 1


def test_three_loop_runner_keeps_wrong_hash_probe_before_native_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    snapshot = object()
    probe_calls: list[object] = []
    probe_rejections: list[str] = []
    native_bridge_calls: list[object] = []

    class NativeLibrary:
        def create(self, received_snapshot: object) -> object:
            native_bridge_calls.append(received_snapshot)
            return SimpleNamespace(close=lambda: None)

    def from_dll_path(path: Path) -> NativeLibrary:
        del path
        return NativeLibrary()

    def unexpected_success_probe(
        asset_root: Path,
        *,
        asset_loader: object,
        bridge_factory: object,
    ) -> NoReturn:
        del asset_root, asset_loader
        probe_calls.append(snapshot)
        try:
            cast(Any, bridge_factory)(snapshot)
        except AssertionError as exc:
            probe_rejections.append(str(exc))
        raise RuntimeError

    monkeypatch.setattr(
        script.Spine38NativeLibrary,
        "from_dll_path",
        staticmethod(from_dll_path),
    )
    monkeypatch.setattr(
        script,
        "_forced_hash_failure_evidence",
        unexpected_success_probe,
    )

    result = script._run_three_loop_smoke(
        script._Arguments(
            list_only=False,
            bridge_dll=Path("X:/spine38_bridge.dll"),
            asset_root=Path("X:/approved-assets"),
            animation="Relax",
            loops=3,
        ),
        script._BuildManifest(
            commit=script._RUNTIME_COMMIT,
            configuration="Release",
            architecture="x64",
            bridge_abi=1,
        ),
    )

    assert result == (1, "spine38_runtime_failure", None)
    assert probe_calls == [snapshot]
    assert probe_rejections == [
        "wrong-hash phase must not construct the bridge"
    ]
    assert native_bridge_calls == []


def test_real_schwarz_renders_three_relax_loops_and_proves_fallback() -> None:
    bridge_value = os.environ.get("ARKCLAW_SPINE38_BRIDGE_DLL")
    asset_root_value = os.environ.get("ARKCLAW_SPINE38_ASSET_ROOT")
    if bridge_value is None or asset_root_value is None:
        pytest.skip(
            "requires ARKCLAW_SPINE38_BRIDGE_DLL and "
            "ARKCLAW_SPINE38_ASSET_ROOT"
        )

    bridge_path = Path(bridge_value)
    asset_root = Path(asset_root_value)
    if not bridge_path.is_absolute() or not bridge_path.is_file():
        pytest.fail("spine38_bridge_dll_invalid", pytrace=False)
    if not asset_root.is_absolute() or not asset_root.is_dir():
        pytest.fail("spine38_asset_root_invalid", pytrace=False)

    project_root = Path(__file__).resolve().parents[2]
    evidence_path = (
        project_root
        / "build"
        / "spine38"
        / "evidence"
        / "schwarz-smoke.json"
    )
    evidence_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    environment["PYTHONUNBUFFERED"] = "1"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts" / "qt_spine38_vertical_slice.py"),
                "--bridge-dll",
                str(bridge_path),
                "--asset-root",
                str(asset_root),
                "--animation",
                "Relax",
                "--loops",
                "3",
            ],
            cwd=project_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120.0,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("spine38_smoke_subprocess_timeout", pytrace=False)
    if completed.returncode != 0:
        pytest.fail(
            f"spine38_smoke_subprocess_failed:{completed.returncode}",
            pytrace=False,
        )
    if completed.stderr != "":
        pytest.fail("spine38_smoke_stderr_not_empty", pytrace=False)
    lines = [line for line in completed.stdout.splitlines() if line]
    if len(lines) != 1:
        pytest.fail("spine38_smoke_stdout_schema_invalid", pytrace=False)
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError:
        pytest.fail("spine38_smoke_stdout_schema_invalid", pytrace=False)
    if not isinstance(value, dict):
        pytest.fail("spine38_smoke_stdout_schema_invalid", pytrace=False)
    result = cast(dict[str, Any], value)

    assert set(result) == {
        "agent_modules_imported",
        "animation",
        "completed_elapsed_seconds",
        "duration_seconds",
        "forced_hash_failure",
        "loops_requested",
        "renderer_safe_code",
        "sampled_nontransparent_frames",
        "samples",
        "schema_version",
        "status",
        "visual_review_required",
        "window_count",
        "window_transparent",
    }
    assert result["schema_version"] == 1
    assert result["status"] == "visual_review_required"
    assert result["animation"] == "Relax"
    assert result["loops_requested"] == 3
    duration = result["duration_seconds"]
    observed = result["completed_elapsed_seconds"]
    assert isinstance(duration, float) and duration > 0.0
    assert isinstance(observed, float) and observed >= 3.0 * duration
    assert result["sampled_nontransparent_frames"] == len(_SAMPLE_LABELS)
    assert result["window_count"] == 1
    assert result["window_transparent"] is True
    assert result["renderer_safe_code"] == "none"
    assert result["agent_modules_imported"] is False
    assert result["visual_review_required"] is True

    fallback = result["forced_hash_failure"]
    assert fallback == {
        "bridge_constructed": False,
        "loader_status": "external_asset_hash_mismatch",
        "renderer_safe_code": "pet_renderer_construction_failed",
        "using_placeholder": True,
    }

    samples = result["samples"]
    assert isinstance(samples, list)
    assert [sample["label"] for sample in samples] == _SAMPLE_LABELS
    for sample in samples:
        assert set(sample) == {
            "alpha_bounds",
            "label",
            "observed_elapsed_seconds",
            "target_elapsed_seconds",
            "vertex_checksum",
        }
        assert sample["observed_elapsed_seconds"] >= 0.0
        assert sample["target_elapsed_seconds"] >= 0.0
        checksum = sample["vertex_checksum"]
        assert isinstance(checksum, str) and len(checksum) == 16
        assert all(character in "0123456789abcdef" for character in checksum)
        bounds = sample["alpha_bounds"]
        assert set(bounds) == {
            "height",
            "nonzero_pixels",
            "width",
            "x",
            "y",
        }
        assert 0 <= bounds["x"] < 160
        assert 0 <= bounds["y"] < 180
        assert bounds["width"] > 0
        assert bounds["height"] > 0
        assert bounds["x"] + bounds["width"] <= 160
        assert bounds["y"] + bounds["height"] <= 180
        assert bounds["nonzero_pixels"] > 0
        assert bounds["width"] >= 80
        assert 153 <= bounds["height"] <= 171
        assert 178 <= bounds["y"] + bounds["height"] <= 180

    assert evidence_path.is_file()
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == result
