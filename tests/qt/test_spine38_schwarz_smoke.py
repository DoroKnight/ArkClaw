"""Opt-in Windows subprocess smoke for the approved Schwarz idle slice."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

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
