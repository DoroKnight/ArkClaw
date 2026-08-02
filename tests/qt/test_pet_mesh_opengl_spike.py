"""Subprocess smoke for the real Windows OpenGL FBO candidate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_programmatic_opengl_spike_has_transparent_readback() -> None:
    repository = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    environment.pop("QT_QPA_FONTDIR", None)

    completed = subprocess.run(
        [sys.executable, str(repository / "scripts" / "qt_pet_mesh_spike.py")],
        cwd=repository,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["qt_pet_mesh_spike"] is True
    assert result["safe_code"] == "none"
    assert result["scene_width"] == 160
    assert result["scene_height"] == 180
    assert result["ground_baseline"] == 160.0
    assert result["transparent_corner"] is True
    assert result["opengl_30_fps"] is True
