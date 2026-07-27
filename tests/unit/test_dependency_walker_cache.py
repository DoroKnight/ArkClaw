from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _PROJECT_ROOT / "packaging" / "dependency_walker_cache.py"
_POWERSHELL_PATH = (
    _PROJECT_ROOT / "packaging" / "stage_dependency_walker_cache.ps1"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_dependency_walker_cache_test",
        _MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CACHE: Any = _load_module()


def _minimal_pe(marker: bytes) -> bytes:
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, 0x8664)
    struct.pack_into("<H", data, 0x84 + 16, 0xF0)
    struct.pack_into("<H", data, 0x84 + 20, 0x20B)
    data[0x200 : 0x200 + len(marker)] = marker
    return bytes(data)


def _prepare_source(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, bytes]:
    payloads = {
        "depends.exe": _minimal_pe(b"exe"),
        "depends.dll": _minimal_pe(b"dll"),
    }
    expected = {
        name: (len(payload), hashlib.sha256(payload).hexdigest())
        for name, payload in payloads.items()
    }
    monkeypatch.setattr(_CACHE, "EXPECTED_FILES", expected)
    source = root / _CACHE.SOURCE_RELATIVE_PATH
    source.mkdir(parents=True)
    for name, payload in payloads.items():
        (source / name).write_bytes(payload)
    return payloads


def test_default_entry_is_inert() -> None:
    cache = _PROJECT_ROOT / _CACHE.CACHE_RELATIVE_PATH
    before = cache.exists()

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_POWERSHELL_PATH),
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "safe_code=dependency_walker_staging_disabled\n"
    )
    assert cache.exists() is before


def test_stage_copies_exact_files_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _prepare_source(tmp_path, monkeypatch)

    first = _CACHE.stage_dependency_walker_cache(tmp_path)
    second = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert first.completed and not first.idempotent
    assert second.completed and second.idempotent
    cache = tmp_path / _CACHE.CACHE_RELATIVE_PATH
    assert sorted(path.name for path in cache.iterdir()) == [
        "depends.dll",
        "depends.exe",
    ]
    assert (cache / "depends.exe").read_bytes() == payloads["depends.exe"]
    assert (cache / "depends.dll").read_bytes() == payloads["depends.dll"]
    assert list(cache.parent.glob("*.part")) == []
    assert list(cache.parent.glob(".*.part")) == []


def test_missing_dll_fails_before_cache_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_source(tmp_path, monkeypatch)
    (tmp_path / _CACHE.SOURCE_RELATIVE_PATH / "depends.dll").unlink()

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_source_invalid"
    assert not (tmp_path / _CACHE.CACHE_RELATIVE_PATH).exists()


@pytest.mark.parametrize("name", ["depends.chm", "depends22_x64.zip"])
def test_source_rejects_chm_or_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    _prepare_source(tmp_path, monkeypatch)
    (tmp_path / _CACHE.SOURCE_RELATIVE_PATH / name).write_bytes(b"forbidden")

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_source_invalid"
    assert not (tmp_path / _CACHE.CACHE_RELATIVE_PATH).exists()


def test_cache_rejects_unknown_file_and_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _prepare_source(tmp_path, monkeypatch)
    cache = tmp_path / _CACHE.CACHE_RELATIVE_PATH
    cache.mkdir(parents=True)
    for name, payload in payloads.items():
        (cache / name).write_bytes(payload)
    (cache / "unknown").mkdir()

    validation = _CACHE.validate_dependency_walker_cache(tmp_path)
    staging = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert validation.safe_code == "dependency_walker_cache_invalid"
    assert staging.safe_code == "dependency_walker_cache_invalid"
    assert (cache / "unknown").is_dir()


@pytest.mark.parametrize("name", ["depends.chm", "depends22_x64.zip"])
def test_cache_rejects_chm_or_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    payloads = _prepare_source(tmp_path, monkeypatch)
    cache = tmp_path / _CACHE.CACHE_RELATIVE_PATH
    cache.mkdir(parents=True)
    for filename, payload in payloads.items():
        (cache / filename).write_bytes(payload)
    (cache / name).write_bytes(b"forbidden")

    validation = _CACHE.validate_dependency_walker_cache(tmp_path)

    assert validation.safe_code == "dependency_walker_cache_invalid"
    assert (cache / name).read_bytes() == b"forbidden"


def test_different_existing_hash_is_not_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _prepare_source(tmp_path, monkeypatch)
    cache = tmp_path / _CACHE.CACHE_RELATIVE_PATH
    cache.mkdir(parents=True)
    (cache / "depends.exe").write_bytes(b"user-owned")
    (cache / "depends.dll").write_bytes(payloads["depends.dll"])

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_cache_occupied"
    assert (cache / "depends.exe").read_bytes() == b"user-owned"
    assert (cache / "depends.dll").read_bytes() == payloads["depends.dll"]


def test_hard_link_source_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_source(tmp_path, monkeypatch)
    source = tmp_path / _CACHE.SOURCE_RELATIVE_PATH / "depends.exe"
    linked = source.with_name("owned-link")
    os.link(source, linked)
    linked.unlink()
    assert source.stat().st_nlink == 1
    os.link(source, tmp_path / "outside-link")

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_source_invalid"
    assert not (tmp_path / _CACHE.CACHE_RELATIVE_PATH).exists()


def test_size_and_architecture_are_revalidated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_source(tmp_path, monkeypatch)
    source = tmp_path / _CACHE.SOURCE_RELATIVE_PATH / "depends.exe"
    payload = bytearray(source.read_bytes())
    struct.pack_into("<H", payload, 0x84, 0x014C)
    source.write_bytes(payload)

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_source_invalid"


def test_reparse_point_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_source(tmp_path, monkeypatch)
    source = tmp_path / _CACHE.SOURCE_RELATIVE_PATH
    original = _CACHE._is_reparse_point

    def fake_reparse(path: Path) -> bool:
        return path == source or bool(original(path))

    monkeypatch.setattr(_CACHE, "_is_reparse_point", fake_reparse)

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_source_invalid"
    assert not (tmp_path / _CACHE.CACHE_RELATIVE_PATH).exists()


def test_atomic_rename_failure_cleans_only_owned_part(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_source(tmp_path, monkeypatch)
    original = _CACHE.os.rename

    def fail_directory_rename(source: Path, target: Path) -> None:
        if Path(target).name == "x86_64":
            raise OSError("simulated")
        original(source, target)

    monkeypatch.setattr(_CACHE.os, "rename", fail_directory_rename)

    outcome = _CACHE.stage_dependency_walker_cache(tmp_path)

    assert outcome.safe_code == "dependency_walker_staging_failed"
    cache_parent = (tmp_path / _CACHE.CACHE_RELATIVE_PATH).parent
    assert not (cache_parent / "x86_64").exists()
    assert list(cache_parent.glob("*.part")) == []
    assert list(cache_parent.glob(".*.part")) == []


def test_cli_rejects_user_paths() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            "--confirm-staging",
            "--source",
            "attacker",
            "--cache",
            "outside",
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0
    assert "unrecognized arguments" in completed.stderr


def test_source_has_no_network_or_binary_execution_path() -> None:
    text = _MODULE_PATH.read_text(encoding="utf-8").casefold()
    powershell = _POWERSHELL_PATH.read_text(encoding="utf-8").casefold()

    assert "import urllib" not in text
    assert "import socket" not in text
    assert "import requests" not in text
    assert "subprocess" not in text
    assert "start-process" not in powershell
    assert "expand-archive" not in powershell
