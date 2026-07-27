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

import PySide6
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = _PROJECT_ROOT / "packaging" / "pysidedeploy.spec"
_ENTRY_PATH = _PROJECT_ROOT / "packaging" / "pet_entry.py"
_BUILD_SCRIPT_PATH = _PROJECT_ROOT / "packaging" / "build_standalone.ps1"
_PREPARE_SCRIPT_PATH = (
    _PROJECT_ROOT / "packaging" / "prepare_packaging_environment.ps1"
)
_INVENTORY_PATH = (
    _PROJECT_ROOT / "packaging" / "packaging_environment_inventory.py"
)
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
    assert not any(argument.startswith("--output-dir") for argument in extra_args)
    assert "--msvc=14.4" in extra_args
    assert "--disable-cache=ccache" in extra_args
    assert "--output-filename=SJTUClaw.exe" in extra_args
    assert (
        "--report=build/windows-standalone/compilation-report.xml"
        in extra_args
    )
    assert "--report-diffable" in extra_args
    assert "--assume-yes-for-downloads" not in extra_args
    assert not any("mingw" in argument.casefold() for argument in extra_args)
    assert "--onefile" not in extra_args
    assert not any(
        argument.startswith("--include-qt-plugins=")
        for argument in extra_args
    )
    for excluded in (
        "pydantic.mypy",
        "mypy",
        "mypy_extensions",
        "mypyc",
        "httpx._main",
        "pygments",
    ):
        assert extra_args.count(f"--nofollow-import-to={excluded}") == 1
    assert "--nofollow-import-to=pydantic" not in extra_args
    assert "--nofollow-import-to=httpx" not in extra_args
    assert "--nofollow-import-to=openai" not in extra_args
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
    assert set(parser["qt"]["plugins"].split(",")) == {
        "platforms",
        "styles",
    }
    assert "platformthemes" not in parser["qt"]["plugins"]


def test_packaging_output_directories_are_git_ignored() -> None:
    ignore_text = (_PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    parser = _load_spec()

    assert "build/" in ignore_text
    assert "dist/" in ignore_text
    assert "packaging/deployment/" in ignore_text
    assert parser["app"]["exec_directory"] == "dist"
    assert not any(
        argument.startswith("--output-dir")
        for argument in parser["nuitka"]["extra_args"].split()
    )


def test_pyside_dry_run_has_exactly_one_output_directory_source() -> None:
    helper_path = (
        Path(PySide6.__file__).resolve().parent
        / "scripts"
        / "deploy_lib"
        / "nuitka_helper.py"
    )
    helper_text = helper_path.read_text(encoding="utf-8")
    extra_args = _load_spec()["nuitka"]["extra_args"].split()

    assert helper_text.count('f"--output-dir={output_dir}"') == 1
    assert not any(argument.startswith("--output-dir") for argument in extra_args)
    assert 'output_dir = source_file.parent / "deployment"' in helper_text


def test_configured_qt_plugin_families_exist_in_pinned_pyside() -> None:
    parser = _load_spec()
    plugin_root = Path(PySide6.__file__).resolve().parent / "plugins"
    configured = parser["qt"]["plugins"].split(",")

    assert configured == ["platforms", "styles"]
    assert all((plugin_root / family).is_dir() for family in configured)
    assert (plugin_root / "platforms" / "qwindows.dll").is_file()
    assert not (plugin_root / "platformthemes").exists()


def test_build_script_uses_repository_local_nuitka_cache() -> None:
    text = _BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "$PSScriptRoot" in text
    assert '"build\\nuitka-cache"' in text
    assert "$env:NUITKA_CACHE_DIR = $NuitkaCachePath" in text
    assert "AppData" not in text
    assert re.search(r"(?im)^[^#\r\n]*[\"'][a-z]:[\\/]", text) is None


def test_build_script_defaults_to_dry_run_and_requires_confirmation() -> None:
    text = _BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "[switch]$ConfirmBuild" in text
    assert "if (-not $ConfirmBuild)" in text
    assert '"--dry-run"' in text
    assert "--prepare-dry-run-workspace" in text
    assert "--finalize-dry-run-workspace" in text
    assert "standalone_dry_run_side_effect_detected" not in text
    assert "mode=dry_run" in text
    assert "--assume-yes-for-downloads" not in text
    assert "--mingw64" not in text
    assert "--onefile" not in text
    assert text.index("if (-not $ConfirmBuild)") < text.index(
        "foreach ($ProtectedOutputPath in $ProtectedOutputPaths)"
    )
    dry_run_branch = text.index("if (-not $ConfirmBuild)")
    msvc_activation = text.index(
        "$SelectedVisualStudio = Find-VisualStudioInstallation"
    )
    dependency_walker = text.index(
        "& $PythonPath $DependencyWalkerCacheValidator --validate-cache"
    )
    assert dry_run_branch < msvc_activation < dependency_walker
    assert "-StandardOutputPath $DryRunStdoutPath" in text
    assert "-StandardErrorPath $DryRunStderrPath" in text


def test_packaging_environment_entry_is_fixed_offline_and_no_dev() -> None:
    text = _PREPARE_SCRIPT_PATH.read_text(encoding="utf-8")

    assert (
        '"safe_code=packaging_environment_prepare_disabled"' in text
    )
    assert '".venv-packaging"' in text
    assert "--locked" in text
    assert "--offline" in text
    assert "--no-python-downloads" in text
    assert "--no-dev" in text
    assert "--extra gui" in text
    assert "--extra packaging" in text
    assert "--extra dev" not in text
    assert '$env:UV_OFFLINE = "1"' in text
    assert '$env:PIP_NO_INDEX = "1"' in text
    assert "Remove-Item" not in text


def test_packaging_inventory_uses_all_four_isolation_views() -> None:
    text = _INVENTORY_PATH.read_text(encoding="utf-8")

    assert "importlib_metadata.distributions()" in text
    assert "importlib.util.find_spec" in text
    assert "site_packages.iterdir()" in text
    assert "sys.path" in text
    assert '"environment_values_recorded": False' in text
    for forbidden in (
        "mypy",
        "mypy_extensions",
        "mypyc",
        "pytest",
        "pygments",
        "ruff",
    ):
        assert f'"{forbidden}"' in text


def test_real_build_checks_dependency_walker_before_deploy() -> None:
    text = _BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    dependency_check = text.index(
        "& $PythonPath $DependencyWalkerCacheValidator --validate-cache"
    )
    build_invocation = text.index(
        "& $PythonPath $StandaloneBuildController --confirm-build"
    )

    assert '"downloads\\depends\\x86_64\\depends.exe"' in text
    assert (
        'Stop-Safe -SafeCode "standalone_toolchain_invalid"' in text
    )
    assert "dependency_walker_not_cached" not in text
    assert dependency_check < build_invocation
    assert "$Process.StandardInput.Close()" in text
    assert "--confirm-audit" in text


def test_build_script_enforces_exact_msvc_x64_toolchain() -> None:
    text = _BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '$RequiredMsvcToolsVersion = "14.44.35207"' in text
    assert '$RequiredCompilerVersionPrefix = "19.44."' in text
    assert '$RequiredPythonCompiler = "MSC v.1944"' in text
    assert (
        '"VC\\Tools\\MSVC\\$RequiredMsvcToolsVersion\\bin\\Hostx64\\x64"'
        in text
    )
    assert '@("cl.exe", "link.exe", "dumpbin.exe")' in text
    assert '$env:VSCMD_ARG_HOST_ARCH -ne "x64"' in text
    assert '$env:VSCMD_ARG_TGT_ARCH -ne "x64"' in text
    assert '$HostArch = "amd64"' in text
    assert '$Arch = "amd64"' in text
    assert "msys_link_rejected" in text
    assert "msvc_toolchain_mismatch" in text
    assert '$RequiredQtPluginFamilies = @("platforms", "styles")' in text
    assert '".venv-packaging\\Lib\\site-packages\\PySide6\\plugins"' in text
    assert '".venv-packaging"' in text
    assert '$env:VIRTUAL_ENV = $PackagingEnvironment' in text
    assert "$env:PYTHONPATH = $null" in text
    assert '"platforms\\qwindows.dll"' in text


def test_build_script_checks_nuitka_version_and_never_compiles_on_parse() -> None:
    text = _BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "& $PythonPath -m nuitka --version" in text
    assert "$LASTEXITCODE -ne 0" in text
    assert "if (-not $ConfirmBuild)" in text

    if os.name != "nt":
        pytest.skip("PowerShell parser probe is Windows-specific")
    parse_command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::"
        f"ParseFile('{_BUILD_SCRIPT_PATH}',[ref]$tokens,[ref]$errors)"
        " | Out-Null; "
        "if ($errors.Count -ne 0) { $errors | ForEach-Object { "
        "[Console]::Error.WriteLine($_.Message) }; exit 1 }"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            parse_command,
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""


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
