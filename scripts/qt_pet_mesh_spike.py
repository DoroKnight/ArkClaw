"""Run the two programmatic mesh candidates without external resources."""

from __future__ import annotations

import json
import os
import time

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ.pop("QT_QPA_FONTDIR", None)

from PySide6.QtGui import QGuiApplication

from arkclaw.presentation.qt.pet.pet_mesh_spike import (
    MeshSpikeError,
    OffscreenOpenGLMeshRenderer,
    SoftwareTexturedMeshRenderer,
    generate_mesh_spike_scene,
)


def main() -> int:
    application = QGuiApplication.instance()
    if application is None:
        application = QGuiApplication([])
    scene = generate_mesh_spike_scene()
    software = SoftwareTexturedMeshRenderer()
    opengl = OffscreenOpenGLMeshRenderer()
    try:
        software_result = software.benchmark(scene, 5)
        opengl.render_scene(scene)
        started = time.perf_counter_ns()
        for _ in range(30):
            image = opengl.render_scene(scene)
        opengl_ms = (time.perf_counter_ns() - started) / 30 / 1_000_000.0
        result = {
            "schema_version": 1,
            "qt_pet_mesh_spike": True,
            "scene_width": image.width(),
            "scene_height": image.height(),
            "ground_baseline": scene.foot_baseline_y,
            "software_wall_ms_per_frame": round(software_result.wall_milliseconds_per_frame, 3),
            "software_cpu_ms_per_frame": round(software_result.cpu_milliseconds_per_frame, 3),
            "software_allocations": software_result.allocation_count,
            "software_30_fps": software_result.meets_30_fps_budget,
            "software_60_fps": software_result.meets_60_fps_budget,
            "opengl_readback_ms_per_frame": round(opengl_ms, 3),
            "opengl_30_fps": opengl_ms <= 1000.0 / 30.0,
            "opengl_60_fps": opengl_ms <= 1000.0 / 60.0,
            "transparent_corner": image.pixelColor(0, 0).alpha() == 0,
            "safe_code": "none",
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except MeshSpikeError as error:
        print(
            json.dumps(
                {"qt_pet_mesh_spike": False, "safe_code": error.code.value},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    finally:
        opengl.close()
        software.close()


if __name__ == "__main__":
    raise SystemExit(main())
