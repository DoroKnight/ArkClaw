"""Opt-in Windows subprocess smoke for the approved Schwarz idle slice."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest

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


def test_wrong_hash_phase_observes_zero_bridge_factory_calls() -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    assets = importlib.import_module(
        "sjtuclaw.application.pet_external_assets"
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
        "sjtuclaw.application.pet_external_assets"
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
    bridge_value = os.environ.get("SJTUCLAW_SPINE38_BRIDGE_DLL")
    asset_root_value = os.environ.get("SJTUCLAW_SPINE38_ASSET_ROOT")
    if bridge_value is None or asset_root_value is None:
        pytest.skip(
            "requires SJTUCLAW_SPINE38_BRIDGE_DLL and "
            "SJTUCLAW_SPINE38_ASSET_ROOT"
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

    assert evidence_path.is_file()
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == result
