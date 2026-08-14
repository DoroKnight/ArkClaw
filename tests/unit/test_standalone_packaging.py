from __future__ import annotations

import configparser
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PACKAGING = _PROJECT_ROOT / "packaging"
_CACHE_PATH = _PACKAGING / "dependency_walker_cache.py"
_ARCHIVE_PATH = _PACKAGING / "archive_standalone_attempt.py"
_BUILD_PATH = _PACKAGING / "standalone_build.py"
_AUDIT_PATH = _PACKAGING / "standalone_artifact_audit.py"
_POWERSHELL_PATH = _PACKAGING / "build_standalone.ps1"
_IMPORT_SMOKE_PATH = _PACKAGING / "production_import_smoke.py"
_PACKAGING_PYTHON = (
    _PROJECT_ROOT / ".venv-packaging/Scripts/python.exe"
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_CACHE: Any = _load("dependency_walker_cache", _CACHE_PATH)
_ARCHIVE: Any = _load("_archive_standalone_attempt_test", _ARCHIVE_PATH)
_BUILD: Any = _load("_standalone_build_test", _BUILD_PATH)
_AUDIT: Any = _load("_standalone_artifact_audit_test", _AUDIT_PATH)


def _minimal_pe(*, subsystem: int = 2) -> bytes:
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, 0x8664)
    struct.pack_into("<H", data, 0x86, 1)
    struct.pack_into("<H", data, 0x84 + 16, 0xF0)
    optional = 0x84 + 20
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<H", data, optional + 68, subsystem)
    struct.pack_into("<H", data, optional + 70, 0x0160)
    struct.pack_into("<I", data, optional + 108, 16)
    section = optional + 0xF0
    data[section : section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x100, 0x1000, 0x100, 0x200)
    return bytes(data)


def _minimal_pe_with_imports() -> bytes:
    data = bytearray(_minimal_pe())
    optional = 0x84 + 20
    import_descriptor_rva = 0x1020
    delay_descriptor_rva = 0x1060
    normal_name_rva = 0x10C0
    delay_name_rva = 0x10D0
    struct.pack_into(
        "<II",
        data,
        optional + 112 + 8,
        import_descriptor_rva,
        40,
    )
    struct.pack_into(
        "<II",
        data,
        optional + 112 + 13 * 8,
        delay_descriptor_rva,
        64,
    )
    struct.pack_into(
        "<IIIII",
        data,
        0x200 + import_descriptor_rva - 0x1000,
        1,
        0,
        0,
        normal_name_rva,
        0,
    )
    struct.pack_into(
        "<IIIIIIII",
        data,
        0x200 + delay_descriptor_rva - 0x1000,
        1,
        delay_name_rva,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    normal_name_offset = 0x200 + normal_name_rva - 0x1000
    delay_name_offset = 0x200 + delay_name_rva - 0x1000
    normal_name = b"normal.dll\0"
    delay_name = b"delay.dll\0"
    data[
        normal_name_offset : normal_name_offset + len(normal_name)
    ] = normal_name
    data[delay_name_offset : delay_name_offset + len(delay_name)] = (
        delay_name
    )
    return bytes(data)


def _prepare_build_root(root: Path) -> None:
    (root / ".venv-packaging/Scripts").mkdir(parents=True)
    (
        root / ".venv-packaging/Scripts/pyside6-deploy.exe"
    ).write_bytes(b"fake")
    (root / "packaging").mkdir()
    (root / "packaging/pysidedeploy.spec").write_text(
        (
            "[app]\n"
            "input_file=packaging/pet_entry.py\n"
            "[qt]\n"
            "plugins=platforms,styles\n"
            "[nuitka]\n"
            "extra_args=--standalone\n"
        ),
        encoding="utf-8",
    )
    (root / _BUILD.THIRD_BUILD_TEMP_RELATIVE_PATH).mkdir(parents=True)


def _prepare_dry_run_root(root: Path) -> None:
    (root / "packaging").mkdir()
    (root / "packaging/pet_entry.py").write_bytes(b"print('fixed')\n")
    (root / "packaging/pysidedeploy.spec").write_text(
        (
            "[app]\n"
            "title=ArkClaw\n"
            "project_dir=..\n"
            "input_file=packaging/pet_entry.py\n"
            "exec_directory=dist\n"
            "[qt]\n"
            "plugins=platforms,styles\n"
            "[nuitka]\n"
            "extra_args=--standalone "
            "--report=build/windows-standalone/compilation-report.xml "
            "--nofollow-import-to=pydantic.mypy "
            "--nofollow-import-to=mypy "
            "--nofollow-import-to=mypy_extensions "
            "--nofollow-import-to=mypyc "
            "--nofollow-import-to=httpx._main "
            "--nofollow-import-to=pygments\n"
        ),
        encoding="utf-8",
    )
    (root / "dist/ArkClaw.dist").mkdir(parents=True)
    (root / "dist/ArkClaw.dist/sentinel.bin").write_bytes(b"final")
    (root / "build/windows-standalone").mkdir(parents=True)
    (
        root / "build/windows-standalone/build_report.json"
    ).write_bytes(b"report")


def _prepare_archive_root(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, tuple[int, str]]:
    source = root / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    source.mkdir(parents=True)
    (root / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH).mkdir(parents=True)
    expected: dict[str, tuple[int, str]] = {}
    for index, name in enumerate(_ARCHIVE.EXPECTED_BUILD_FILES):
        content = f"fixed-failed-attempt-{index}".encode()
        path = source / name
        path.write_bytes(content)
        expected[name] = (len(content), hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(_ARCHIVE, "EXPECTED_BUILD_FILES", expected)
    return expected


def test_standalone_attempt_archive_default_entry_is_inert() -> None:
    result = subprocess.run(
        [
            str(_PACKAGING_PYTHON),
            "-I",
            str(_ARCHIVE_PATH),
        ],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == (
        "safe_code=standalone_attempt_archive_disabled"
    )
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            _IMPORT_SMOKE_PATH,
            "safe_code=production_import_smoke_disabled\n",
        ),
    ],
)
def test_new_packaging_helpers_default_to_inert(
    path: Path,
    expected: str,
) -> None:
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == expected
    assert result.stderr == ""


def test_standalone_attempt_archive_moves_only_fixed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _prepare_archive_root(tmp_path, monkeypatch)

    outcome = _ARCHIVE.archive_failed_standalone_attempt(tmp_path)

    target = (
        tmp_path
        / _ARCHIVE.ARCHIVE_PARENT_RELATIVE_PATH
        / _ARCHIVE.ARCHIVE_NAME
    )
    assert outcome.completed
    assert outcome.safe_code == "standalone_attempt_archive_complete"
    assert not (tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH).exists()
    assert not (
        tmp_path / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    ).exists()
    assert _ARCHIVE._directory_manifest(
        target / _ARCHIVE.ARCHIVED_BUILD_NAME
    ) == expected
    assert _ARCHIVE._directory_manifest(
        target / _ARCHIVE.ARCHIVED_DEPLOYMENT_NAME
    ) == {}
    manifest = json.loads(
        (target / _ARCHIVE.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["file_count"] == len(expected)
    assert manifest["total_size"] == sum(
        size for size, _digest in expected.values()
    )
    assert manifest["manifest_sha256"] == outcome.manifest_sha256
    assert manifest["same_volume_renames"] is True


def test_unpruned_archive_moves_and_revalidates_all_fixed_sources(
    tmp_path: Path,
) -> None:
    build = tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    raw = tmp_path / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    final = tmp_path / _ARCHIVE.DIST_RELATIVE_PATH
    build.mkdir(parents=True)
    raw.mkdir(parents=True)
    final.mkdir()
    for name in (
        "artifact_audit.json",
        "build_report.json",
        "compilation-report.xml",
    ):
        (build / name).write_text(name, encoding="utf-8")
    for directory in (raw, final):
        (directory / "ArkClaw.exe").write_bytes(b"same-artifact")

    outcome = _ARCHIVE.archive_unpruned_standalone(tmp_path)

    target = (
        tmp_path
        / _ARCHIVE.UNPRUNED_ARCHIVE_PARENT_RELATIVE_PATH
        / _ARCHIVE.UNPRUNED_ARCHIVE_NAME
    )
    assert outcome.completed
    assert outcome.safe_code == "standalone_unpruned_archive_complete"
    assert not build.exists()
    assert not raw.exists()
    assert not final.exists()
    assert (
        target / _ARCHIVE.UNPRUNED_MANIFEST_NAME
    ).is_file()
    assert _ARCHIVE._directory_manifest(
        target / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    ) == _ARCHIVE._directory_manifest(
        target / _ARCHIVE.DIST_RELATIVE_PATH
    )


def test_unpruned_archive_rejects_raw_final_mismatch(
    tmp_path: Path,
) -> None:
    build = tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    raw = tmp_path / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    final = tmp_path / _ARCHIVE.DIST_RELATIVE_PATH
    build.mkdir(parents=True)
    raw.mkdir(parents=True)
    final.mkdir()
    for name in (
        "artifact_audit.json",
        "build_report.json",
        "compilation-report.xml",
    ):
        (build / name).write_text(name, encoding="utf-8")
    (raw / "ArkClaw.exe").write_bytes(b"raw")
    (final / "ArkClaw.exe").write_bytes(b"final")

    outcome = _ARCHIVE.archive_unpruned_standalone(tmp_path)

    assert not outcome.completed
    assert (
        outcome.safe_code
        == "standalone_unpruned_archive_source_invalid"
    )
    assert build.exists()
    assert raw.exists()
    assert final.exists()


def _prepare_degraded_archive_root(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = root / "dist/ArkClaw.dist"
    build = root / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    final.mkdir(parents=True)
    build.mkdir(parents=True)
    executable = b"fixed-final-executable"
    (final / "ArkClaw.exe").write_bytes(executable)
    final_manifest = _ARCHIVE._directory_manifest(final)
    (build / "artifact_audit.json").write_text(
        json.dumps(
            {
                "manifest": {
                    name: {"size": size, "sha256": digest}
                    for name, (size, digest) in final_manifest.items()
                }
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "build_attempt_started.marker",
        "build_report.json",
        "compilation-report.xml",
        "pyside6-deploy.stderr.log",
        "pyside6-deploy.stdout.log",
        "pysidedeploy.spec",
    ):
        (build / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(_ARCHIVE, "EXPECTED_FINAL_FILE_COUNT", 1)
    monkeypatch.setattr(
        _ARCHIVE,
        "EXPECTED_FINAL_TOTAL_SIZE",
        len(executable),
    )
    monkeypatch.setattr(
        _ARCHIVE,
        "EXPECTED_FINAL_EXE_SHA256",
        hashlib.sha256(executable).hexdigest(),
    )


def test_degraded_archive_preserves_only_surviving_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_degraded_archive_root(tmp_path, monkeypatch)
    incident = _ARCHIVE.record_dry_run_incident(tmp_path)

    outcome = _ARCHIVE.archive_degraded_surviving_evidence(
        tmp_path
    )

    target = (
        tmp_path
        / _ARCHIVE.DEGRADED_ARCHIVE_PARENT_RELATIVE_PATH
        / _ARCHIVE.DEGRADED_ARCHIVE_NAME
    )
    assert incident.completed
    assert outcome.completed
    assert outcome.safe_code == "standalone_degraded_archive_complete"
    assert not (tmp_path / "dist").exists()
    assert not (
        tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    ).exists()
    assert not (
        tmp_path / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    ).exists()
    report = json.loads(
        (
            target / _ARCHIVE.DEGRADED_ARCHIVE_MANIFEST_NAME
        ).read_text(encoding="utf-8")
    )
    assert report["archive_mode"] == "degraded_surviving_evidence"
    assert report["raw_dist_present"] is False
    assert report["raw_dist_reconstructed"] is False
    assert report["current_raw_final_equality_reverified"] is False
    assert not list(target.parent.glob("*.part"))


def test_degraded_archive_rolls_back_second_move_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_degraded_archive_root(tmp_path, monkeypatch)
    assert _ARCHIVE.record_dry_run_incident(tmp_path).completed
    calls = 0

    def fail_second_move(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated-secret-never-publish")
        os.rename(source, target)

    outcome = _ARCHIVE.archive_degraded_surviving_evidence(
        tmp_path,
        renamer=fail_second_move,
    )

    assert not outcome.completed
    assert outcome.safe_code == "standalone_degraded_archive_failed"
    assert (tmp_path / "dist/ArkClaw.dist").is_dir()
    assert (
        tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    ).is_dir()
    assert "simulated-secret-never-publish" not in repr(outcome)


@pytest.mark.parametrize("mutation", ["extra", "changed", "occupied"])
def test_standalone_attempt_archive_fails_closed_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _prepare_archive_root(tmp_path, monkeypatch)
    source = tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    if mutation == "extra":
        (source / "unexpected.bin").write_bytes(b"unexpected")
    elif mutation == "changed":
        next(source.iterdir()).write_bytes(b"changed")
    else:
        (
            tmp_path
            / _ARCHIVE.ARCHIVE_PARENT_RELATIVE_PATH
            / _ARCHIVE.ARCHIVE_NAME
        ).mkdir(parents=True)

    outcome = _ARCHIVE.archive_failed_standalone_attempt(tmp_path)

    assert not outcome.completed
    assert outcome.safe_code in {
        "standalone_attempt_archive_occupied",
        "standalone_attempt_archive_source_invalid",
    }
    assert source.is_dir()
    assert (
        tmp_path / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    ).is_dir()


def test_standalone_attempt_archive_rejects_hardlinked_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_archive_root(tmp_path, monkeypatch)
    source = tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    existing = next(source.iterdir())
    try:
        os.link(existing, source / "hardlink")
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    outcome = _ARCHIVE.archive_failed_standalone_attempt(tmp_path)

    assert not outcome.completed
    assert outcome.safe_code == "standalone_attempt_archive_source_invalid"
    assert source.is_dir()


def test_standalone_attempt_archive_rolls_back_rename_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _prepare_archive_root(tmp_path, monkeypatch)
    calls = 0

    def fail_second_rename(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated rename failure with sensitive text")
        os.rename(source, target)

    outcome = _ARCHIVE.archive_failed_standalone_attempt(
        tmp_path,
        renamer=fail_second_rename,
    )

    assert not outcome.completed
    assert outcome.safe_code == "standalone_attempt_archive_failed"
    assert _ARCHIVE._directory_manifest(
        tmp_path / _ARCHIVE.SOURCE_BUILD_RELATIVE_PATH
    ) == expected
    assert _ARCHIVE._directory_manifest(
        tmp_path / _ARCHIVE.SOURCE_DEPLOYMENT_RELATIVE_PATH
    ) == {}


@pytest.mark.parametrize("manifest", [_BUILD._manifest, _AUDIT._manifest])
def test_standalone_manifests_reject_hardlinks(
    tmp_path: Path,
    manifest: Any,
) -> None:
    directory = tmp_path / "artifact"
    directory.mkdir()
    original = directory / "payload.dll"
    original.write_bytes(b"payload")
    try:
        os.link(original, directory / "duplicate.dll")
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    with pytest.raises(OSError, match="non_regular"):
        manifest(directory)


@pytest.mark.parametrize("manifest", [_BUILD._manifest, _AUDIT._manifest])
def test_standalone_manifests_reject_reparse_like_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: Any,
) -> None:
    directory = tmp_path / "artifact"
    directory.mkdir()
    linked = directory / "linked.dll"
    linked.write_bytes(b"payload")
    original = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        return path == linked or original(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(OSError, match="link_rejected"):
        manifest(directory)


def _write_compilation_report(root: Path, *, extra: str = "") -> None:
    path = root / _BUILD.BUILD_RELATIVE_PATH / _BUILD.REPORT_NAME
    required_autostart_modules = "".join(
        f'<module name="{name}" source_path="repository"/>'
        for name in sorted(_AUDIT._REQUIRED_AUTOSTART_MODULES)
    )
    path.write_text(
        (
            '<nuitka-compilation-report nuitka_version="4.0" '
            'mode="standalone" completion="yes">'
            '<command_line><option value="packaging/pet_entry.py"/>'
            '<option value="--standalone"/></command_line>'
            '<plugins><plugin name="pyside6"/></plugins>'
            '<distributions><distribution name="PySide6" version="6.11.1" '
            'installer="uv"/></distributions>'
            '<python arch_name="x86_64"/>'
            f"{required_autostart_modules}{extra}"
            "</nuitka-compilation-report>"
        ),
        encoding="utf-8",
    )


def _write_build_artifacts(root: Path) -> None:
    raw = root / _BUILD.RAW_DIST_RELATIVE_PATH
    final = root / _BUILD.FINAL_DIST_RELATIVE_PATH
    raw.mkdir(parents=True)
    final.mkdir(parents=True)
    for directory in (raw, final):
        (directory / "ArkClaw.exe").write_bytes(_minimal_pe())


def _successful_execution() -> Any:
    return _BUILD.BuildExecutionResult(
        started=True,
        job_configured=True,
        active_process_limit=128,
        kill_on_job_close=True,
        exit_code=0,
        timed_out=False,
        process_remaining=False,
        active_process_limit_hit=False,
        total_processes=12,
        peak_active_processes=4,
        stdout_sha256="0" * 64,
        stdout_bytes=0,
        stderr_sha256="0" * 64,
        stderr_bytes=0,
        safe_code="none",
    )


def test_materialized_spec_has_one_derived_qt_plugin_argument(
    tmp_path: Path,
) -> None:
    _prepare_build_root(tmp_path)
    source = tmp_path / _BUILD.TRACKED_SPEC_RELATIVE_PATH
    destination = tmp_path / "materialized.spec"

    assert _BUILD._materialize_spec(source, destination)

    text = destination.read_text(encoding="utf-8")
    assert text.count("--include-qt-plugins=platforms,styles") == 1
    assert "platformthemes" not in text
    assert "--standalone" in text
    assert "--include-qt-plugins" not in source.read_text(encoding="utf-8")


def test_tracked_spec_materialization_preserves_exact_nofollow_rules(
    tmp_path: Path,
) -> None:
    source = _PROJECT_ROOT / _BUILD.TRACKED_SPEC_RELATIVE_PATH
    destination = tmp_path / "materialized.spec"

    assert _BUILD._materialize_spec(source, destination)

    parser = configparser.ConfigParser()
    parser.read(destination, encoding="utf-8")
    arguments = parser["nuitka"]["extra_args"].split()
    for excluded in (
        "pydantic.mypy",
        "mypy",
        "mypy_extensions",
        "mypyc",
        "httpx._main",
        "pygments",
    ):
        assert arguments.count(
            f"--nofollow-import-to={excluded}"
        ) == 1
    assert arguments.count(
        "--include-qt-plugins=platforms,styles"
    ) == 1


def test_dry_run_workspace_isolates_entry_report_and_output(
    tmp_path: Path,
) -> None:
    _prepare_dry_run_root(tmp_path)
    production_entry = tmp_path / "packaging/pet_entry.py"
    production_spec = tmp_path / "packaging/pysidedeploy.spec"
    entry_hash = hashlib.sha256(production_entry.read_bytes()).hexdigest()
    spec_hash = hashlib.sha256(production_spec.read_bytes()).hexdigest()

    outcome = _BUILD.prepare_dry_run_workspace(tmp_path)

    workspace = tmp_path / _BUILD.DRY_RUN_WORKSPACE_RELATIVE_PATH
    assert outcome.completed
    assert (
        hashlib.sha256(
            (workspace / "input/pet_entry.py").read_bytes()
        ).hexdigest()
        == entry_hash
    )
    assert hashlib.sha256(production_spec.read_bytes()).hexdigest() == spec_hash
    parser = configparser.ConfigParser()
    parser.read(workspace / "pysidedeploy.spec", encoding="utf-8")
    assert parser["app"]["input_file"] == (
        "build/standalone-dry-run/input/pet_entry.py"
    )
    assert parser["app"]["project_dir"] == "input"
    assert parser["app"]["exec_directory"] == (
        "build/standalone-dry-run/dist"
    )
    arguments = parser["nuitka"]["extra_args"].split()
    assert (
        "--report=build/standalone-dry-run/compilation-report.xml"
        in arguments
    )
    rendered = (workspace / "pysidedeploy.spec").read_text(
        encoding="utf-8"
    )
    assert "packaging/deployment" not in rendered
    assert "dist/ArkClaw.dist" not in rendered
    assert "build/windows-standalone" not in rendered


def test_dry_run_lifecycle_preserves_protected_artifacts(
    tmp_path: Path,
) -> None:
    _prepare_dry_run_root(tmp_path)
    before = _BUILD.protected_artifact_snapshot(tmp_path)
    prepared = _BUILD.prepare_dry_run_workspace(tmp_path)
    workspace = tmp_path / _BUILD.DRY_RUN_WORKSPACE_RELATIVE_PATH
    (workspace / "input/deployment").rmdir()
    (workspace / _BUILD.DRY_RUN_STDOUT_NAME).write_bytes(b"command")
    (workspace / _BUILD.DRY_RUN_STDERR_NAME).write_bytes(b"warning")

    finalized = _BUILD.finalize_dry_run_workspace(tmp_path)

    assert prepared.completed
    assert finalized.completed
    assert _BUILD.protected_artifact_snapshot(tmp_path) == before
    assert not workspace.exists()


def test_dry_run_unknown_file_blocks_owned_cleanup(
    tmp_path: Path,
) -> None:
    _prepare_dry_run_root(tmp_path)
    assert _BUILD.prepare_dry_run_workspace(tmp_path).completed
    workspace = tmp_path / _BUILD.DRY_RUN_WORKSPACE_RELATIVE_PATH
    (workspace / "unexpected.bin").write_bytes(b"evidence")

    outcome = _BUILD.finalize_dry_run_workspace(tmp_path)

    assert not outcome.completed
    assert outcome.safe_code == "standalone_dry_run_cleanup_failed"
    assert (workspace / "unexpected.bin").read_bytes() == b"evidence"


def test_dry_run_protected_mutation_is_detected_before_cleanup(
    tmp_path: Path,
) -> None:
    _prepare_dry_run_root(tmp_path)
    assert _BUILD.prepare_dry_run_workspace(tmp_path).completed
    protected = tmp_path / "dist/ArkClaw.dist/sentinel.bin"
    protected.write_bytes(b"changed")

    outcome = _BUILD.finalize_dry_run_workspace(tmp_path)

    assert not outcome.completed
    assert outcome.safe_code == (
        "standalone_dry_run_side_effect_detected"
    )
    assert (
        tmp_path / _BUILD.DRY_RUN_WORKSPACE_RELATIVE_PATH
    ).is_dir()


class _FakeBuildRunner:
    def __init__(
        self,
        *,
        result: Any | None = None,
        artifacts: bool = True,
        sensitive_log: str = "",
        mutate_spec: bool = False,
    ) -> None:
        self.result = result or _successful_execution()
        self.artifacts = artifacts
        self.sensitive_log = sensitive_log
        self.mutate_spec = mutate_spec
        self.calls = 0

    def run(
        self,
        command: Any,
        *,
        working_directory: Path,
        environment: Any,
        timeout_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> Any:
        self.calls += 1
        assert timeout_seconds == 5400.0
        assert "--keep-deployment-files" in command
        assert "--onefile" not in command
        assert environment["PIP_NO_INDEX"] == "1"
        assert environment["UV_OFFLINE"] == "1"
        assert environment["VIRTUAL_ENV"].endswith(".venv-packaging")
        assert ".venv-packaging" in environment["PATH"]
        expected_temp = (
            working_directory
            / _BUILD.THIRD_BUILD_TEMP_RELATIVE_PATH
        ).resolve()
        assert Path(environment["TEMP"]).resolve() == expected_temp
        assert Path(environment["TMP"]).resolve() == expected_temp
        assert Path(environment["TMPDIR"]).resolve() == expected_temp
        assert expected_temp.is_dir()
        assert expected_temp.parent == (
            working_directory / "build"
        ).resolve()
        assert not any(
            "ExternalTemp" in environment[name]
            for name in ("TEMP", "TMP", "TMPDIR")
        )
        assert "PYTHONPATH" not in environment
        assert "OPENAI_API_KEY" not in environment
        stdout_path.write_text(self.sensitive_log, encoding="utf-8")
        stderr_path.write_text(self.sensitive_log, encoding="utf-8")
        if self.artifacts:
            _write_compilation_report(working_directory)
            _write_build_artifacts(working_directory)
        if self.mutate_spec:
            (
                working_directory / "packaging/pysidedeploy.spec"
            ).write_text("changed", encoding="utf-8")
        payload = self.sensitive_log.encode("utf-8")
        return replace(
            self.result,
            stdout_sha256=hashlib.sha256(payload).hexdigest(),
            stdout_bytes=len(payload),
            stderr_sha256=hashlib.sha256(payload).hexdigest(),
            stderr_bytes=len(payload),
        )


def _run_build(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: _FakeBuildRunner,
    *,
    snapshots: Any = None,
) -> Any:
    monkeypatch.setattr(
        _BUILD,
        "validate_dependency_walker_cache",
        lambda path: _CACHE.CacheOutcome("none", True, True),
    )
    return _BUILD.run_standalone_build(
        root,
        runner=runner,
        environment={
            "PATH": "fixed",
            "SYSTEMROOT": r"C:\Windows",
            "TEMP": r"C:\ExternalTemp",
            "TMP": r"C:\ExternalTemp",
            "TMPDIR": r"C:\ExternalTemp",
            "OPENAI_API_KEY": "sk-real-never-record",
            "SERVICE_TOKEN": "sensitive-token",
        },
        disk_free_reader=lambda path: 20 * 1024**3,
        process_snapshotter=snapshots or (lambda: {}),
        monotonic=iter((10.0, 12.5)).__next__,
        environment_validator=lambda path: True,
    )


def test_standalone_helpers_default_to_inert() -> None:
    for path, expected in (
        (_BUILD_PATH, "safe_code=standalone_build_disabled\n"),
        (
            _AUDIT_PATH,
            "safe_code=standalone_artifact_audit_disabled\n",
        ),
    ):
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=_PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0
        assert completed.stdout == expected
        assert completed.stderr == ""


def test_output_occupancy_rejects_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)
    (tmp_path / "dist").mkdir()
    runner = _FakeBuildRunner()

    outcome = _run_build(tmp_path, monkeypatch, runner)

    assert outcome.safe_code == "standalone_output_occupied"
    assert runner.calls == 0


def test_disk_space_rejects_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)
    monkeypatch.setattr(
        _BUILD,
        "validate_dependency_walker_cache",
        lambda path: _CACHE.CacheOutcome("none", True, True),
    )
    runner = _FakeBuildRunner()

    outcome = _BUILD.run_standalone_build(
        tmp_path,
        runner=runner,
        environment={},
        disk_free_reader=lambda path: 11 * 1024**3,
        environment_validator=lambda path: True,
    )

    assert outcome.safe_code == "standalone_disk_space_insufficient"
    assert runner.calls == 0


def test_success_requires_job_and_all_postconditions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)
    runner = _FakeBuildRunner()

    outcome = _run_build(tmp_path, monkeypatch, runner)

    assert outcome.completed
    assert outcome.safe_code == "none"
    assert runner.calls == 1
    assert outcome.report["hard_network_isolation"] is False
    assert outcome.report["packaged_executable_executed"] is False
    assert (
        outcome.report["postconditions"]["raw_final_manifest_equal"] is True
    )
    report_text = json.dumps(outcome.report)
    assert "sk-real-never-record" not in report_text
    assert "sensitive-token" not in report_text


def test_exit_zero_without_artifacts_fails_postcondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)

    outcome = _run_build(
        tmp_path,
        monkeypatch,
        _FakeBuildRunner(artifacts=False),
    )

    assert outcome.safe_code == "standalone_postcondition_failed"


@pytest.mark.parametrize(
    "mutation",
    ["missing_report", "corrupt_report", "missing_exe", "dist_mismatch"],
)
def test_each_strong_postcondition_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _prepare_build_root(tmp_path)

    class MutatingRunner(_FakeBuildRunner):
        def run(self, *args: Any, **kwargs: Any) -> Any:
            result = super().run(*args, **kwargs)
            root = kwargs["working_directory"]
            if mutation == "missing_report":
                (
                    root
                    / _BUILD.BUILD_RELATIVE_PATH
                    / _BUILD.REPORT_NAME
                ).unlink()
            elif mutation == "corrupt_report":
                (
                    root
                    / _BUILD.BUILD_RELATIVE_PATH
                    / _BUILD.REPORT_NAME
                ).write_text("<broken", encoding="utf-8")
            elif mutation == "missing_exe":
                (
                    root
                    / _BUILD.FINAL_DIST_RELATIVE_PATH
                    / "ArkClaw.exe"
                ).unlink()
            else:
                (
                    root / _BUILD.FINAL_DIST_RELATIVE_PATH / "extra.dll"
                ).write_bytes(_minimal_pe())
            return result

    outcome = _run_build(tmp_path, monkeypatch, MutatingRunner())

    assert outcome.safe_code == "standalone_postcondition_failed"


def test_tracked_spec_modification_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)

    outcome = _run_build(
        tmp_path,
        monkeypatch,
        _FakeBuildRunner(mutate_spec=True),
    )

    assert outcome.safe_code == "standalone_postcondition_failed"


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            replace(_successful_execution(), timed_out=True),
            "standalone_build_timeout",
        ),
        (
            _BUILD._empty_execution_result("standalone_build_failed"),
            "standalone_build_failed",
        ),
        (
            replace(_successful_execution(), process_remaining=True),
            "standalone_build_failed",
        ),
    ],
)
def test_job_timeout_setup_and_residue_fail_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: Any,
    expected: str,
) -> None:
    _prepare_build_root(tmp_path)

    outcome = _run_build(
        tmp_path,
        monkeypatch,
        _FakeBuildRunner(result=result),
    )

    assert outcome.safe_code == expected


def test_new_build_process_residue_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)
    snapshots = iter(({100: "codex.exe"}, {100: "codex.exe", 200: "cl.exe"}))

    outcome = _run_build(
        tmp_path,
        monkeypatch,
        _FakeBuildRunner(),
        snapshots=lambda: next(snapshots),
    )

    assert outcome.safe_code == "standalone_build_failed"
    assert outcome.report["unexpected_build_processes"] == ["cl.exe"]


def test_sensitive_build_logs_are_hashed_not_copied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_build_root(tmp_path)
    sensitive = "opaque-secret-never-publish"

    outcome = _run_build(
        tmp_path,
        monkeypatch,
        _FakeBuildRunner(sensitive_log=sensitive),
    )

    serialized = json.dumps(outcome.report)
    assert sensitive not in serialized
    assert sensitive not in repr(outcome)
    assert outcome.report["execution"]["stdout_bytes"] == len(sensitive)


def _prepare_audit_root(root: Path, *, report_extra: str = "") -> None:
    build = root / _AUDIT.BUILD_RELATIVE_PATH
    build.mkdir(parents=True)
    _write_compilation_report(root, extra=report_extra)
    files = (
        "ArkClaw.exe",
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "Qt6Network.dll",
        "python313.dll",
        "PySide6/QtCore.pyd",
        "PySide6/qt-plugins/platforms/qwindows.dll",
        "PySide6/qt-plugins/styles/qmodernwindowsstyle.dll",
    )
    for relative in files:
        for directory in (
            root / _AUDIT.RAW_DIST_RELATIVE_PATH,
            root / _AUDIT.FINAL_DIST_RELATIVE_PATH,
        ):
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_minimal_pe())


def _fake_pe(path: Path) -> Any:
    del path
    return _AUDIT._PEInfo(
        machine=0x8664,
        subsystem=2,
        dll_characteristics=0x0160,
        dependencies=("kernel32.dll", "vcruntime140.dll"),
    )


def _fake_dumpbin(path: Path) -> dict[str, object]:
    assert path.name == "ArkClaw.exe"
    return {
        "tool_directory_valid": True,
        "/HEADERS": {"exit_code": 0, "sha256": "0" * 64, "bytes": 1},
        "/DEPENDENTS": {
            "exit_code": 0,
            "sha256": "0" * 64,
            "bytes": 1,
        },
    }


def _audit(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    monkeypatch.setattr(_AUDIT, "_parse_pe", _fake_pe)
    return _AUDIT.audit_standalone_artifacts(
        root,
        dumpbin_runner=_fake_dumpbin,
        system_dll_names=frozenset(
            {"kernel32.dll", "vcruntime140.dll"}
        ),
    )


def test_static_audit_accepts_complete_fake_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_audit_root(tmp_path)

    outcome = _audit(tmp_path, monkeypatch)

    assert outcome.completed
    assert outcome.safe_code == "packaged_runtime_authorization_required"
    assert outcome.report["file_count"] == 9
    assert outcome.report["control_flow_guard_enabled"] is False
    assert outcome.report["packaged_executable_executed"] is False
    assert outcome.report["plugin_results"]["platforms"] == [
        "PySide6/qt-plugins/platforms/qwindows.dll"
    ]
    assert outcome.report["plugin_results"]["styles"] == [
        "PySide6/qt-plugins/styles/qmodernwindowsstyle.dll"
    ]


def test_pe_parser_includes_normal_and_delay_imports(
    tmp_path: Path,
) -> None:
    path = tmp_path / "imports.dll"
    path.write_bytes(_minimal_pe_with_imports())

    info = _AUDIT._parse_pe(path)

    assert info.normal_dependencies == ("normal.dll",)
    assert info.delay_dependencies == ("delay.dll",)
    assert info.dependencies == ("delay.dll", "normal.dll")


def test_dependency_resolution_uses_explicit_loader_locations() -> None:
    bundled = {
        "adjacent.dll": ("plugins/platforms/adjacent.dll",),
        "root.dll": ("root.dll",),
        "wrong.dll": ("unrelated/wrong.dll",),
        "duplicate.dll": (
            "first/duplicate.dll",
            "second/duplicate.dll",
        ),
    }
    system = frozenset({"system-only.dll"})

    adjacent = _AUDIT._dependency_resolution(
        "plugins/platforms/qwindows.dll",
        "adjacent.dll",
        bundled_paths_by_name=bundled,
        system_names=system,
    )
    root = _AUDIT._dependency_resolution(
        "plugins/platforms/qwindows.dll",
        "root.dll",
        bundled_paths_by_name=bundled,
        system_names=system,
    )
    wrong = _AUDIT._dependency_resolution(
        "plugins/platforms/qwindows.dll",
        "wrong.dll",
        bundled_paths_by_name=bundled,
        system_names=system,
    )
    duplicate = _AUDIT._dependency_resolution(
        "plugins/platforms/qwindows.dll",
        "duplicate.dll",
        bundled_paths_by_name=bundled,
        system_names=system,
    )
    system_result = _AUDIT._dependency_resolution(
        "plugins/platforms/qwindows.dll",
        "system-only.dll",
        bundled_paths_by_name=bundled,
        system_names=system,
    )

    assert adjacent.status == "resolved"
    assert adjacent.resolution_tier == "current_pe_directory"
    assert adjacent.selected_candidate == (
        "plugins/platforms/adjacent.dll"
    )
    assert root.status == "resolved"
    assert root.resolution_tier == "distribution_root"
    assert root.selected_candidate == "root.dll"
    assert wrong.status == "bundled_wrong_directory"
    assert wrong.selected_candidate is None
    assert duplicate.status == "bundled_wrong_directory"
    assert duplicate.selected_candidate is None
    assert system_result.status == "resolved"
    assert system_result.resolution_tier == "windows_system"


def test_dependency_resolution_prefers_current_and_reports_shadowed() -> None:
    bundled = {
        "msvcp140.dll": (
            "msvcp140.dll",
            "shiboken6/msvcp140.dll",
        )
    }

    result = _AUDIT._dependency_resolution(
        "shiboken6/Shiboken.pyd",
        "msvcp140.dll",
        bundled_paths_by_name=bundled,
        system_names=frozenset(),
    )

    assert result.status == "resolved"
    assert result.selected_candidate == "shiboken6/msvcp140.dll"
    assert result.resolution_tier == "current_pe_directory"
    assert result.shadowed_candidates == ("msvcp140.dll",)


def test_dependency_resolution_prefers_root_over_other_package() -> None:
    bundled = {
        "runtime.dll": (
            "runtime.dll",
            "unrelated/runtime.dll",
        )
    }

    result = _AUDIT._dependency_resolution(
        "PySide6/qt-plugins/platforms/qwindows.dll",
        "runtime.dll",
        bundled_paths_by_name=bundled,
        system_names=frozenset(),
    )

    assert result.status == "resolved"
    assert result.selected_candidate == "runtime.dll"
    assert result.resolution_tier == "distribution_root"
    assert result.shadowed_candidates == ("unrelated/runtime.dll",)


def test_dependency_resolution_rejects_same_tier_ambiguity() -> None:
    bundled = {
        "runtime.dll": (
            "package/runtime.dll",
            "PACKAGE/RUNTIME.DLL",
        )
    }

    result = _AUDIT._dependency_resolution(
        "package/importer.pyd",
        "runtime.dll",
        bundled_paths_by_name=bundled,
        system_names=frozenset(),
    )

    assert result.status == "ambiguous"
    assert result.resolution_tier == "current_pe_directory"
    assert result.selected_candidate is None


@pytest.mark.parametrize(
    ("importer", "selected"),
    [
        ("mypy/module.pyd", "mypy/__init__.pyd"),
        ("mypyc/module.pyd", "mypyc/__init__.pyd"),
    ],
)
def test_duplicate_package_initializers_resolve_in_importer_directory(
    importer: str,
    selected: str,
) -> None:
    bundled = {
        "__init__.pyd": (
            "mypy/__init__.pyd",
            "mypyc/__init__.pyd",
        )
    }

    result = _AUDIT._dependency_resolution(
        importer,
        "__init__.pyd",
        bundled_paths_by_name=bundled,
        system_names=frozenset(),
    )

    assert result.status == "resolved"
    assert result.selected_candidate == selected
    assert result.resolution_tier == "current_pe_directory"


def test_delay_import_uses_same_dependency_resolution(tmp_path: Path) -> None:
    path = tmp_path / "importer.dll"
    path.write_bytes(_minimal_pe_with_imports())
    info = _AUDIT._parse_pe(path)

    result = _AUDIT._dependency_resolution(
        "plugins/importer.dll",
        info.delay_dependencies[0],
        bundled_paths_by_name={"delay.dll": ("plugins/delay.dll",)},
        system_names=frozenset(),
    )

    assert result.status == "resolved"
    assert result.resolution_tier == "current_pe_directory"


def test_static_audit_reports_unreferenced_duplicate_pe_basenames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_audit_root(tmp_path)
    for directory in (
        tmp_path / _AUDIT.RAW_DIST_RELATIVE_PATH,
        tmp_path / _AUDIT.FINAL_DIST_RELATIVE_PATH,
    ):
        for parent in ("first", "second"):
            path = directory / parent / "duplicate.dll"
            path.parent.mkdir()
            path.write_bytes(_minimal_pe())

    outcome = _audit(tmp_path, monkeypatch)

    assert outcome.completed
    assert outcome.report["duplicate_basenames_are_informational"] is True
    assert outcome.report["duplicate_pe_basenames"] == {
        "duplicate.dll": [
            "first/duplicate.dll",
            "second/duplicate.dll",
        ]
    }


@pytest.mark.parametrize(
    ("relative", "allowed"),
    [
        ("PySide6/qt-plugins/platforms/qwindows.dll", True),
        ("PySide6/qt-plugins/platforms/qoffscreen.dll", True),
        ("PySide6/qt-plugins/styles/qwindowsvistastyle.dll", True),
        ("PySide6/qt-plugins/imageformats/qjpeg.dll", True),
        ("PySide6/qt-plugins/iconengines/qsvgicon.dll", True),
        ("PySide6/qt-plugins/tls/qschannelbackend.dll", True),
        ("PySide6/qt-plugins/unknown/theme.dll", False),
        ("PySide6/qt-plugins/platforms/deep/qwindows.dll", False),
        ("PySide6/qt-plugins/platformthemes/theme.dll", False),
        ("Qt6Core.dll", True),
    ],
)
def test_qt_plugin_paths_are_explicit(relative: str, allowed: bool) -> None:
    assert _AUDIT._qt_plugin_path_is_allowed(relative) is allowed


def test_static_audit_accepts_all_five_qt_plugin_families(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_audit_root(tmp_path)
    extras = (
        "platforms/qoffscreen.dll",
        "imageformats/qjpeg.dll",
        "iconengines/qsvgicon.dll",
        "tls/qschannelbackend.dll",
    )
    for directory in (
        tmp_path / _AUDIT.RAW_DIST_RELATIVE_PATH,
        tmp_path / _AUDIT.FINAL_DIST_RELATIVE_PATH,
    ):
        for relative in extras:
            path = directory / "PySide6/qt-plugins" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_minimal_pe())

    outcome = _audit(tmp_path, monkeypatch)

    assert outcome.completed
    assert outcome.report["checks"]["qt_plugin_paths_valid"] is True
    assert set(outcome.report["plugin_results"]) == {
        "iconengines",
        "imageformats",
        "platforms",
        "platformthemes",
        "styles",
        "tls",
    }


@pytest.mark.parametrize(
    ("payload", "secret_count", "benign_count", "identifier"),
    [
        (b"Bearer authentication is required", 0, 1, False),
        (b"Bearer authorization failed", 0, 1, False),
        (
            b"Bearer eyJhbGciOiJIUzI1NiJ9."
            b"eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
            1,
            0,
            False,
        ),
        (
            b"Bearer A9b_7Qx-2Lm+4Nr=8Vp0Zk3Yt6Ws",
            1,
            0,
            False,
        ),
        (b"CredentialBlob", 0, 0, True),
        (b'{"CredentialBlob": null}', 0, 0, True),
        (
            b"CredentialBlob=A9b7Qx2Lm4Nr8Vp0Zk3Yt6Ws1Ce5",
            1,
            0,
            True,
        ),
        (b"sk-test-never-use-this-value", 1, 0, False),
    ],
)
def test_sensitive_scanner_classifies_without_exposing_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: bytes,
    secret_count: int,
    benign_count: int,
    identifier: bool,
) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(payload)

    scan = _AUDIT._scan_file(path)
    serialized = json.dumps(
        {
            "secret": [
                _AUDIT._finding_report(item, filename="payload.bin")
                for item in scan.secret_findings
            ],
            "benign": [
                _AUDIT._finding_report(item, filename="payload.bin")
                for item in scan.benign_bearer_findings
            ],
        }
    )

    assert len(scan.secret_findings) == secret_count
    assert len(scan.benign_bearer_findings) == benign_count
    assert scan.credential_blob_identifier_present is identifier
    assert payload.decode("ascii") not in serialized
    assert payload.decode("ascii") not in repr(scan)
    captured = capsys.readouterr()
    assert payload.decode("ascii") not in captured.out
    assert payload.decode("ascii") not in captured.err


def test_sensitive_scanner_detects_token_across_read_boundary(
    tmp_path: Path,
) -> None:
    token = b"A9b_7Qx-2Lm+4Nr=8Vp0Zk3Yt6Ws"
    prefix = b"x" * (1024 * 1024 - len(b"Bearer ") + 2)
    path = tmp_path / "boundary.bin"
    path.write_bytes(prefix + b" Bearer " + token)

    scan = _AUDIT._scan_file(path)

    assert len(scan.secret_findings) == 1
    finding = scan.secret_findings[0]
    assert finding.kind == "Bearer"
    assert finding.sha256 == hashlib.sha256(
        b"Bearer " + token
    ).hexdigest()


def test_bearer_prose_metadata_matches_complete_original_match(
    tmp_path: Path,
) -> None:
    phrase = b"bearer authentication."
    path = tmp_path / "prose.bin"
    path.write_bytes(phrase)

    scan = _AUDIT._scan_file(path)

    assert not scan.secret_findings
    assert len(scan.benign_bearer_findings) == 1
    finding = scan.benign_bearer_findings[0]
    assert finding.length == 22
    assert finding.sha256 == (
        "52477424de5444aee8b33d00bc58491877ab0f42f4c587a5149bd069ca1d3df3"
    )


def test_production_dependency_surface_has_dedicated_safe_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = (
        '<module name="pydantic.mypy"/>'
        '<module name="mypy"/>'
        '<module name="mypy.checker"/>'
        '<module name="mypyc"/>'
        '<module name="httpx._main"/>'
        '<module name="pygments"/>'
        "<distributions>"
        '<distribution name="mypy" version="1" installer="uv"/>'
        '<distribution name="mypy_extensions" version="1" installer="uv"/>'
        '<distribution name="Pygments" version="1" installer="uv"/>'
        "</distributions>"
    )
    _prepare_audit_root(tmp_path, report_extra=extra)

    outcome = _audit(tmp_path, monkeypatch)

    assert not outcome.completed
    assert outcome.safe_code == "standalone_dependency_pruning_required"
    assert (
        outcome.report["checks"]["production_dependency_surface_valid"]
        is False
    )
    assert outcome.report["forbidden_production_modules"] == [
        "httpx._main",
        "mypy",
        "mypy.checker",
        "mypyc",
        "pydantic.mypy",
        "pygments",
    ]
    assert outcome.report["forbidden_production_distributions"] == [
        "mypy",
        "mypy_extensions",
        "Pygments",
    ]


@pytest.mark.parametrize(
    ("kind", "expected_check"),
    [
        ("manual_target", "no_real_secret_material"),
        ("depends", "no_forbidden_names"),
        ("local_path", "no_local_path_leaks"),
        ("missing_qwindows", "required_qt_python_files_present"),
        ("missing_styles", "required_qt_plugins_present"),
        ("platformthemes", "qt_plugin_paths_valid"),
        ("raw_final_mismatch", "raw_final_manifest_equal"),
    ],
)
def test_static_audit_rejects_forbidden_artifact_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_check: str,
) -> None:
    _prepare_audit_root(tmp_path)
    raw = tmp_path / _AUDIT.RAW_DIST_RELATIVE_PATH
    final = tmp_path / _AUDIT.FINAL_DIST_RELATIVE_PATH
    if kind == "manual_target":
        for directory in (raw, final):
            (directory / "payload.bin").write_bytes(
                b"ArkClaw/Test/OpenAI/APIKey"
            )
    elif kind == "depends":
        for directory in (raw, final):
            (directory / "depends.exe").write_bytes(_minimal_pe())
    elif kind == "local_path":
        for directory in (raw, final):
            (directory / "payload.bin").write_bytes(b"D:\\ArkClaw\\.venv")
    elif kind == "missing_qwindows":
        for directory in (raw, final):
            (
                directory
                / "PySide6/qt-plugins/platforms/qwindows.dll"
            ).unlink()
    elif kind == "missing_styles":
        for directory in (raw, final):
            (
                directory
                / "PySide6/qt-plugins/styles/qmodernwindowsstyle.dll"
            ).unlink()
    elif kind == "platformthemes":
        for directory in (raw, final):
            path = (
                directory
                / "PySide6/qt-plugins/platformthemes/theme.dll"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(_minimal_pe())
    else:
        (final / "extra.bin").write_bytes(b"extra")

    outcome = _audit(tmp_path, monkeypatch)

    assert not outcome.completed
    assert outcome.safe_code == "standalone_artifact_audit_failed"
    assert outcome.report["checks"][expected_check] is False


def test_compilation_report_forbidden_module_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_audit_root(
        tmp_path,
        report_extra='<module name="tests.test_secret" source_path="fixed"/>',
    )

    outcome = _audit(tmp_path, monkeypatch)

    assert not outcome.completed
    compilation = outcome.report["compilation_report"]
    assert compilation["forbidden_modules"] == ["tests.test_secret"]


def test_compilation_report_requires_all_autostart_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_audit_root(tmp_path)
    report = tmp_path / _AUDIT.REPORT_RELATIVE_PATH
    missing = "arkclaw.infrastructure.autostart.windows_run_key"
    text = report.read_text(encoding="utf-8")
    text = text.replace(
        f'<module name="{missing}" source_path="repository"/>',
        "",
    )
    report.write_text(text, encoding="utf-8")

    outcome = _audit(tmp_path, monkeypatch)

    assert not outcome.completed
    compilation = outcome.report["compilation_report"]
    assert compilation["missing_required_autostart_modules"] == [missing]
    assert missing not in compilation["required_autostart_modules_present"]


def test_corrupt_compilation_report_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_audit_root(tmp_path)
    (
        tmp_path / _AUDIT.REPORT_RELATIVE_PATH
    ).write_text("<broken", encoding="utf-8")

    outcome = _audit(tmp_path, monkeypatch)

    assert not outcome.completed
    assert outcome.report["checks"]["compilation_report_valid"] is False


def test_packaging_source_uses_suspended_job_and_never_runs_output() -> None:
    build_text = _BUILD_PATH.read_text(encoding="utf-8")
    audit_text = _AUDIT_PATH.read_text(encoding="utf-8")
    combined = (build_text + audit_text).casefold()

    assert "CreateJobObjectW" in build_text
    assert "AssignProcessToJobObject" in build_text
    assert "CREATE_SUSPENDED" in build_text
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in build_text
    assert "ACTIVE_PROCESS_LIMIT = 128" in build_text
    assert "TIMEOUT_SECONDS = 90.0 * 60.0" in build_text
    assert "start-process" not in combined
    assert "popen" not in audit_text.casefold()
    assert "createprocessw" not in audit_text.casefold()
    assert "shell=true" not in combined
    assert "socket" not in combined
    assert "requests" not in combined


def test_powershell_build_boundary_has_required_fixed_controls() -> None:
    text = _POWERSHELL_PATH.read_text(encoding="utf-8")

    assert "[switch]$ConfirmBuild" in text
    assert '"standalone_output_occupied"' in text
    assert '"standalone_disk_space_insufficient"' in text
    assert "$env:PIP_NO_INDEX = \"1\"" in text
    assert "$env:UV_OFFLINE = \"1\"" in text
    assert "--confirm-build" in text
    assert "--confirm-audit" in text
    assert "--confirm-real-api" not in text
    assert "--onefile" not in text
    assert "Start-Process" not in text
