from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast


def test_console_and_gui_entry_points_keep_reviewed_names_and_roles() -> None:
    project_root = Path(__file__).parents[2]
    document = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = cast(dict[str, object], document["project"])

    assert project["scripts"] == {
        "arkclaw-agent-demo": "arkclaw.__main__:main",
    }
    assert project["gui-scripts"] == {
        "arkclaw-gui": "arkclaw.presentation.qt.application:run",
        "arkclaw-pet": "arkclaw.presentation.qt.pet_application:run",
    }
