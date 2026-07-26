from __future__ import annotations

import ast
import configparser
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = _PROJECT_ROOT / "packaging" / "pysidedeploy.spec"
_ENTRY_PATH = _PROJECT_ROOT / "packaging" / "pet_entry.py"
_PYPROJECT_PATH = _PROJECT_ROOT / "pyproject.toml"
_LOCK_PATH = _PROJECT_ROOT / "uv.lock"


def _load_spec() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    loaded = parser.read(_SPEC_PATH, encoding="utf-8")
    assert loaded == [str(_SPEC_PATH)]
    return parser


def test_packaging_spec_uses_only_relative_repository_paths() -> None:
    text = _SPEC_PATH.read_text(encoding="utf-8")
    parser = _load_spec()

    assert re.search(r"(?im)^[a-z]:[\\/]", text) is None
    assert "D:\\SJTUClaw" not in text
    assert "C:\\Users\\" not in text
    for key in ("project_dir", "input_file", "exec_directory"):
        assert not Path(parser["app"][key]).is_absolute()


def test_packaging_spec_has_fixed_standalone_gui_configuration() -> None:
    parser = _load_spec()
    extra_args = parser["nuitka"]["extra_args"].split()

    assert parser["app"]["title"] == "SJTUClaw"
    assert parser["app"]["input_file"] == "packaging/pet_entry.py"
    assert parser["app"]["exec_directory"] == "dist"
    assert parser["python"]["packages"] == "Nuitka==4.0"
    assert parser["nuitka"]["mode"] == "standalone"
    assert "--windows-console-mode=disable" in extra_args
    assert "--output-dir=build/windows-standalone" in extra_args
    assert "--include-qt-plugins=platforms,platformthemes,styles" in extra_args
    assert {
        "--include-module=PySide6.QtCore",
        "--include-module=PySide6.QtGui",
        "--include-module=PySide6.QtWidgets",
        "--include-module=PySide6.QtNetwork",
    }.issubset(extra_args)
    assert set(parser["qt"]["modules"].split(",")) == {
        "Core",
        "Gui",
        "Widgets",
        "Network",
    }


def test_packaging_output_directories_are_git_ignored() -> None:
    ignore_text = (_PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    parser = _load_spec()

    assert "build/" in ignore_text
    assert "dist/" in ignore_text
    assert "packaging/deployment/" in ignore_text
    assert parser["app"]["exec_directory"] == "dist"
    assert (
        "--output-dir=build/windows-standalone"
        in parser["nuitka"]["extra_args"].split()
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "manual_openai_verification",
        "manual_deepseek_verification",
        "qt_pet_smoke",
        "qt_gui_smoke",
        "CredentialBlob",
        "SJTUClaw/Test/",
        "ark-model",
        ".env",
        ".log",
        ".tmp",
        ".png",
        ".atlas",
        ".skel",
    ],
)
def test_packaging_spec_contains_no_forbidden_include(
    forbidden: str,
) -> None:
    assert forbidden.casefold() not in _SPEC_PATH.read_text(
        encoding="utf-8"
    ).casefold()


def test_packaging_entry_has_exact_minimal_structure() -> None:
    tree = ast.parse(_ENTRY_PATH.read_text(encoding="utf-8"))
    imported_names = [
        (node.module, tuple(alias.name for alias in node.names))
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module != "__future__"
    ]
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert imported_names == [
        ("sjtuclaw.presentation.qt.pet_application", ("run",))
    ]
    assert len(calls) == 1
    assert isinstance(calls[0].func, ast.Name)
    assert calls[0].func.id == "run"
    assert calls[0].args == []
    assert calls[0].keywords == []


def test_packaging_entry_import_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_calls = 0
    fake_application = ModuleType(
        "sjtuclaw.presentation.qt.pet_application"
    )

    def fake_run() -> None:
        nonlocal run_calls
        run_calls += 1

    fake_application.run = fake_run  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "sjtuclaw.presentation.qt.pet_application",
        fake_application,
    )
    spec = importlib.util.spec_from_file_location(
        "_sjtuclaw_packaging_entry_test",
        _ENTRY_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert run_calls == 0
    assert vars(module).get("run") is fake_run


def test_packaging_entry_real_import_has_no_runtime_or_io_side_effect() -> None:
    code = f"""
import importlib.util
import socket
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from sjtuclaw.bootstrap.qt_runtime import ProductionQtRuntimeCompositionRoot
from sjtuclaw.infrastructure.security.windows_credential_store import (
    WindowsCredentialSecretStore,
)
from sjtuclaw.presentation.qt.runtime_thread import RuntimeThread

def forbidden(*args, **kwargs):
    raise AssertionError("packaging entry import crossed a runtime or I/O boundary")

socket.socket = forbidden
WindowsCredentialSecretStore.__init__ = forbidden
ProductionQtRuntimeCompositionRoot.__init__ = forbidden
RuntimeThread.__init__ = forbidden
entry_path = Path({str(_ENTRY_PATH)!r})
spec = importlib.util.spec_from_file_location("_packaging_entry_probe", entry_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert QCoreApplication.instance() is None
print("entry_import_inert=True")
"""
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stdout == "entry_import_inert=True\n"
    assert completed.stderr == ""


def test_nuitka_pin_matches_pyproject_and_lock() -> None:
    pyproject_text = _PYPROJECT_PATH.read_text(encoding="utf-8")
    lock_text = _LOCK_PATH.read_text(encoding="utf-8")

    assert 'packaging = [\n  "Nuitka==4.0",\n]' in pyproject_text
    assert re.search(
        r'(?ms)\[\[package\]\]\nname = "nuitka"\nversion = "4\.0"\n',
        lock_text,
    )
    assert "pyinstaller" not in pyproject_text.casefold()
    assert 'name = "pyinstaller"' not in lock_text.casefold()
    assert "file:///" not in lock_text.casefold()


@pytest.mark.parametrize(
    ("package_name", "expected_version"),
    [
        ("openai", "2.48.0"),
        ("pyside6", "6.11.1"),
        ("httpx", "0.28.1"),
        ("certifi", "2026.7.22"),
    ],
)
def test_existing_locked_dependency_versions_are_unchanged(
    package_name: str,
    expected_version: str,
) -> None:
    lock_text = _LOCK_PATH.read_text(encoding="utf-8")

    assert re.search(
        rf'(?ms)\[\[package\]\]\nname = "{package_name}"\n'
        rf'version = "{re.escape(expected_version)}"\n',
        lock_text,
    )


def test_lock_uses_only_official_pypi_domains() -> None:
    lock_text = _LOCK_PATH.read_text(encoding="utf-8")
    domains = set(
        re.findall(r"https://([^/]+)/", lock_text)
    )

    assert domains == {"pypi.org", "files.pythonhosted.org"}


def test_production_source_contains_no_manual_target_prefix() -> None:
    source_root = _PROJECT_ROOT / "src" / "sjtuclaw"
    matches = [
        path
        for path in source_root.rglob("*.py")
        if "SJTUClaw/Test/" in path.read_text(encoding="utf-8")
    ]

    assert matches == []


def test_packaging_entry_does_not_expose_dynamic_inputs() -> None:
    text = _ENTRY_PATH.read_text(encoding="utf-8")
    forbidden_names = (
        "argv",
        "environ",
        "getenv",
        "SecretStore",
        "Credential",
        "Provider",
        "socket",
        "http",
    )

    assert all(name not in text for name in forbidden_names)
    assert _load_spec()["app"]["input_file"] == (
        "packaging/pet_entry.py"
    )
