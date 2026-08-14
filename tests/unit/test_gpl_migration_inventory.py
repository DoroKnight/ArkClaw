from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _PROJECT_ROOT / "scripts" / "gpl_migration_inventory.py"


def _load_inventory_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_gpl_migration_inventory_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _temporary_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "inventory-fixture"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "scripts").mkdir()
    (repo / "assets").mkdir()
    (repo / "audio").mkdir()
    (repo / "models").mkdir()
    (repo / "runtime").mkdir()

    (repo / "src" / "app.py").write_text("print('fixture')\n", encoding="utf-8")
    (repo / "scripts" / "tool.ps1").write_text("Write-Output fixture\n", encoding="utf-8")
    (repo / "assets" / "icon.png").write_bytes(b"fixture png")
    (repo / "audio" / "alert.wav").write_bytes(b"fixture wav")
    (repo / "models" / "pet.glb").write_bytes(b"fixture glb")
    (repo / "runtime" / "rig.spine").write_bytes(b"fixture spine")
    (repo / "runtime" / "helper.dll").write_bytes(b"fixture dll")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=75"]

[project]
dependencies = ["openai==2.48.0"]

[project.optional-dependencies]
dev = ["pytest>=8.3"]
gui = ["PySide6==6.11.1"]
packaging = ["Nuitka==4.0"]
""".lstrip(),
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "openai"
version = "2.48.0"

[[package]]
name = "pyside6"
version = "6.11.1"
""".lstrip(),
        encoding="utf-8",
    )

    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Fixture Author")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def test_inventory_is_deterministic_and_classifies_repository(tmp_path: Path) -> None:
    inventory_module: Any = _load_inventory_module()
    repo = _temporary_repository(tmp_path)

    first = inventory_module.build_inventory(repo)
    second = inventory_module.build_inventory(repo)

    assert first == second
    assert first["code_files"] == ["scripts/tool.ps1", "src/app.py"]
    assert first["dependencies"]["direct"] == ["openai==2.48.0"]
    assert first["dependencies"]["optional"]["gui"] == ["PySide6==6.11.1"]
    assert first["dependencies"]["packaging"] == ["Nuitka==4.0"]
    assert first["dependencies"]["build"] == ["setuptools>=75"]
    assert first["dependencies"]["locked"] == [
        {"name": "openai", "version": "2.48.0"},
        {"name": "pyside6", "version": "6.11.1"},
    ]
    assert first["assets"] == {
        "animation": ["runtime/rig.spine"],
        "audio": ["audio/alert.wav"],
        "binary": ["runtime/helper.dll"],
        "font": [],
        "image": ["assets/icon.png"],
        "model": ["models/pet.glb"],
    }
    assert first["native_runtime_files"] == ["runtime/helper.dll"]
    assert first["git"] == {
        "commit_count": 1,
        "contributors": ["Fixture Author <fixture@example.invalid>"],
    }


def test_json_output_contains_only_relative_paths_and_no_environment_values(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    inventory_module: Any = _load_inventory_module()
    repo = _temporary_repository(tmp_path)
    secret = "inventory-secret-must-not-leak"
    monkeypatch.setenv("ARKCLAW_INVENTORY_TEST_SECRET", secret)

    rendered = json.dumps(inventory_module.build_inventory(repo), sort_keys=True)

    assert str(repo) not in rendered
    assert secret not in rendered
    for value in inventory_module.iter_inventory_paths(json.loads(rendered)):
        assert not Path(value).is_absolute()
        assert ".." not in Path(value).parts
    assert os.environ["ARKCLAW_INVENTORY_TEST_SECRET"] == secret
