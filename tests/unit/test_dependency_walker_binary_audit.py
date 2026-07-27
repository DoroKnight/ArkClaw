from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_SCRIPT = (
    _PROJECT_ROOT / "packaging" / "dependency_walker_binary_audit.py"
)
_POWERSHELL_SCRIPT = (
    _PROJECT_ROOT / "packaging" / "audit_dependency_walker_binaries.ps1"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_dependency_walker_binary_audit_test",
        _PYTHON_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_AUDIT: Any = _load_module()


def _minimal_pe(
    *,
    machine: int = 0x8664,
    certificate: bytes | None = None,
    certificate_offset: int | None = None,
    certificate_size: int | None = None,
    writable_executable: bool = False,
) -> bytes:
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    coff = 0x84
    struct.pack_into("<HHI", data, coff, machine, 1, 0x386D4380)
    struct.pack_into("<H", data, coff + 16, 0xF0)
    struct.pack_into("<H", data, coff + 18, 0x0022)
    optional = coff + 20
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<Q", data, optional + 24, 0x140000000)
    struct.pack_into("<H", data, optional + 68, 2)
    struct.pack_into("<H", data, optional + 70, 0x4160)
    struct.pack_into("<I", data, optional + 108, 16)
    section = optional + 0xF0
    data[section : section + 8] = b".text\x00\x00\x00"
    struct.pack_into("<IIII", data, section + 8, 0x180, 0x1000, 0x200, 0x200)
    characteristics = 0x60000020
    if writable_executable:
        characteristics |= 0x80000000
    struct.pack_into("<I", data, section + 36, characteristics)
    data[0x200:0x204] = b"\xC3\x90\x90\x90"
    if certificate is not None:
        offset = certificate_offset if certificate_offset is not None else len(data)
        size = certificate_size if certificate_size is not None else len(certificate)
        struct.pack_into("<II", data, optional + 112 + 4 * 8, offset, size)
        if offset == len(data):
            data.extend(certificate)
    elif certificate_offset is not None or certificate_size is not None:
        struct.pack_into(
            "<II",
            data,
            optional + 112 + 4 * 8,
            certificate_offset or 0,
            certificate_size or 0,
        )
    return bytes(data)


def _minimal_pe_with_ordinal_exports() -> bytes:
    data = bytearray(_minimal_pe())
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe_offset + 24
    export_rva = 0x1100
    export_offset = 0x300
    functions_rva = 0x1140
    functions_offset = 0x340
    struct.pack_into("<II", data, optional + 112, export_rva, 0x48)
    struct.pack_into(
        "<IIHHIIIIIII",
        data,
        export_offset,
        0,
        0x386D4380,
        0,
        0,
        0,
        7,
        3,
        0,
        functions_rva,
        0,
        0,
    )
    struct.pack_into(
        "<III",
        data,
        functions_offset,
        0x1010,
        0,
        0x1020,
    )
    return bytes(data)


def _archive_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _prepare_archive(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exe: bytes | None = None,
    dll: bytes | None = None,
    chm: bytes = b"offline help",
) -> dict[str, bytes]:
    entries = {
        "depends.exe": exe or _minimal_pe(),
        "depends.dll": dll or _minimal_pe(),
        "depends.chm": chm,
    }
    payload = _archive_bytes(entries)
    zip_path = root / _AUDIT.ZIP_RELATIVE_PATH
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(payload)
    monkeypatch.setattr(_AUDIT, "EXPECTED_ZIP_SIZE", len(payload))
    monkeypatch.setattr(
        _AUDIT,
        "EXPECTED_ZIP_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        _AUDIT,
        "EXPECTED_ENTRY_HASHES",
        {
            name: hashlib.sha256(value).hexdigest()
            for name, value in entries.items()
        },
    )
    return entries


def _fake_dumpbin(path: Path) -> dict[str, object]:
    del path
    return {
        "tool": "fake dumpbin",
        "host_arch": "amd64",
        "target_arch": "amd64",
        "commands": {
            option: {
                "exit_code": 0,
                "output_sha256": "0" * 64,
                "output_bytes": 0,
            }
            for option in ("/HEADERS", "/DEPENDENTS", "/IMPORTS", "/EXPORTS")
        },
    }


def _fake_version(path: Path) -> dict[str, str | None]:
    return {
        "file_description": "Dependency Walker",
        "product_name": "Dependency Walker",
        "company_name": "Dependency Walker",
        "file_version": "2.2.6000.0",
        "product_version": "2.2",
        "original_filename": path.name,
        "copyright": "placeholder",
    }


def test_default_powershell_mode_is_inert_and_extracts_nothing() -> None:
    extracted = (
        _PROJECT_ROOT
        / "build"
        / "tool-quarantine"
        / "dependency-walker"
        / "extracted"
    )
    before = (
        sorted(path.name for path in extracted.iterdir())
        if extracted.exists()
        else None
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_POWERSHELL_SCRIPT),
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "safe_code=dependency_walker_extraction_disabled\n"
    )
    assert completed.stderr == ""
    after = (
        sorted(path.name for path in extracted.iterdir())
        if extracted.exists()
        else None
    )
    assert after == before


def test_zip_hash_mismatch_prevents_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_archive(tmp_path, monkeypatch)
    monkeypatch.setattr(_AUDIT, "EXPECTED_ZIP_SHA256", "0" * 64)

    outcome = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert outcome.safe_code == "dependency_walker_zip_hash_mismatch"
    assert not (tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH).exists()


def test_entry_hash_mismatch_prevents_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_archive(tmp_path, monkeypatch)
    hashes = dict(_AUDIT.EXPECTED_ENTRY_HASHES)
    hashes["depends.dll"] = "0" * 64
    monkeypatch.setattr(_AUDIT, "EXPECTED_ENTRY_HASHES", hashes)

    outcome = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert outcome.safe_code == "dependency_walker_entry_hash_mismatch"
    assert not (tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH).exists()


def test_target_occupied_is_not_overwritten_or_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_archive(tmp_path, monkeypatch)
    extracted = tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH
    extracted.mkdir(parents=True)
    target = extracted / "depends.exe"
    target.write_bytes(b"user-owned")

    outcome = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert outcome.safe_code == "dependency_walker_extraction_target_occupied"
    assert target.read_bytes() == b"user-owned"
    assert not (extracted / "depends.dll").exists()


def test_owned_part_files_are_cleaned_after_atomic_rename_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_archive(tmp_path, monkeypatch)

    def fail_rename(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("simulated rename failure")

    monkeypatch.setattr(_AUDIT.os, "rename", fail_rename)
    outcome = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert outcome.safe_code == "dependency_walker_extraction_failed"
    extracted = tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH
    assert list(extracted.glob("*.part")) == []
    assert list(extracted.glob(".*.part")) == []


def test_only_exe_and_dll_are_atomically_extracted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _prepare_archive(tmp_path, monkeypatch)

    outcome = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert outcome.completed
    extracted = tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH
    assert sorted(path.name for path in extracted.iterdir()) == [
        "depends.dll",
        "depends.exe",
    ]
    assert (extracted / "depends.exe").read_bytes() == entries["depends.exe"]
    assert (extracted / "depends.dll").read_bytes() == entries["depends.dll"]
    assert not (extracted / "depends.chm").exists()
    assert list(extracted.glob("*.part")) == []
    report = json.loads(
        (tmp_path / _AUDIT.BINARY_AUDIT_RELATIVE_PATH).read_text(
            encoding="utf-8"
        )
    )
    assert report["target_pe_executed"] is False
    assert report["target_dll_loaded"] is False
    assert report["network_accessed"] is False
    relationship = report["relationship_analysis"]
    assert relationship["depends_dll_only_used_for_profiling_proven"] is False
    assert relationship["depends_dll_runtime_profile_helper_evidence"] == (
        "strong"
    )
    assert relationship["cache_only_exe_runtime_failure_risk"] is True
    assert relationship["chm_needed_for_nuitka_scan"] is False
    assert str(tmp_path) not in json.dumps(report)


def test_exact_owned_extraction_can_resume_static_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _prepare_archive(tmp_path, monkeypatch)

    failed = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=lambda path: (_ for _ in ()).throw(
            OSError(path.name)
        ),
        version_reader=_fake_version,
    )
    completed = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert failed.safe_code == "dependency_walker_static_audit_failed"
    assert completed.completed
    extracted = tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH
    assert (extracted / "depends.exe").read_bytes() == entries["depends.exe"]
    assert (extracted / "depends.dll").read_bytes() == entries["depends.dll"]
    assert sorted(path.name for path in extracted.iterdir()) == [
        "depends.dll",
        "depends.exe",
    ]


def test_reparse_point_check_fails_closed_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_archive(tmp_path, monkeypatch)
    zip_path = tmp_path / _AUDIT.ZIP_RELATIVE_PATH
    original = _AUDIT._is_reparse_point

    def fake_reparse(path: Path) -> bool:
        return path == zip_path or bool(original(path))

    monkeypatch.setattr(_AUDIT, "_is_reparse_point", fake_reparse)
    outcome = _AUDIT.audit_dependency_walker_binaries(
        tmp_path,
        dumpbin_runner=_fake_dumpbin,
        version_reader=_fake_version,
    )

    assert outcome.safe_code == "dependency_walker_zip_unavailable"
    assert not (tmp_path / _AUDIT.EXTRACTED_RELATIVE_PATH).exists()


def test_cli_accepts_no_zip_entry_or_output_path_injection() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(_PYTHON_SCRIPT),
            "--zip",
            "attacker.zip",
            "--output",
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


def test_amd64_pe32_plus_layout_and_wx_detection(
    tmp_path: Path,
) -> None:
    safe_path = tmp_path / "safe.exe"
    wx_path = tmp_path / "wx.exe"
    safe_path.write_bytes(_minimal_pe())
    wx_path.write_bytes(_minimal_pe(writable_executable=True))

    safe = _AUDIT._inspect_binary(safe_path)
    writable_executable = _AUDIT._inspect_binary(wx_path)

    assert safe["machine_hex"] == "0x8664"
    assert safe["is_amd64"] is True
    assert safe["pe_format"] == "PE32+"
    assert safe["security_features"] == {
        "aslr_dynamic_base": True,
        "dep_nx_compat": True,
        "control_flow_guard": True,
        "high_entropy_va": True,
    }
    assert safe["has_writable_executable_section"] is False
    assert writable_executable["has_writable_executable_section"] is True


def test_ordinal_only_exports_do_not_require_a_name_table() -> None:
    layout = _AUDIT._parse_pe_layout(_minimal_pe_with_ordinal_exports())

    assert _AUDIT._parse_exports(layout) == ["ordinal:7", "ordinal:9"]


def test_non_amd64_machine_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "x86.exe"
    path.write_bytes(_minimal_pe(machine=0x014C))

    report = _AUDIT._inspect_binary(path)

    assert report["machine_hex"] == "0x014C"
    assert report["is_amd64"] is False


def test_unsigned_pe_reports_no_certificate_table(tmp_path: Path) -> None:
    path = tmp_path / "unsigned.exe"
    path.write_bytes(_minimal_pe())

    report = _AUDIT._inspect_binary(path)["authenticode"]

    assert report["status"] == "unsigned"
    assert report["signature_validation"] == "not_applicable"
    assert report["certificate_table_present"] is False


def test_certificate_table_out_of_bounds_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "bad-boundary.exe"
    path.write_bytes(
        _minimal_pe(
            certificate_offset=0x400,
            certificate_size=0x100,
        )
    )

    report = _AUDIT._inspect_binary(path)["authenticode"]

    assert report["status"] == "embedded_signature_invalid"
    assert report["signature_validation"] == "invalid"


def test_malformed_pkcs7_is_invalid(tmp_path: Path) -> None:
    certificate = struct.pack("<IHH", 16, 0x0200, 0x0002) + b"not-pkcs"
    path = tmp_path / "malformed.exe"
    path.write_bytes(_minimal_pe(certificate=certificate))

    report = _AUDIT._inspect_binary(path)["authenticode"]

    assert report["certificate_table_present"] is True
    assert report["pkcs7_signed_data_present"] is False
    assert report["status"] == "embedded_signature_invalid"


def test_structural_pkcs7_reports_offline_validation_unavailable(
    tmp_path: Path,
) -> None:
    blob = b"\x30" + b"\x82" * 23
    certificate = struct.pack("<IHH", 32, 0x0200, 0x0002) + blob
    path = tmp_path / "signed-shape.exe"
    path.write_bytes(_minimal_pe(certificate=certificate))

    report = _AUDIT._inspect_binary(path)["authenticode"]

    assert report["status"] == "embedded_signature_present"
    assert report["signature_validation"] == "unavailable"
    assert report["signer_count"] is None
    assert report["file_digest_matches"] is None


def test_dumpbin_runner_uses_only_four_fixed_read_only_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dumpbin = tmp_path / "dumpbin.exe"
    target = tmp_path / "depends.exe"
    dumpbin.write_bytes(b"trusted test tool placeholder")
    target.write_bytes(_minimal_pe())
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **kwargs: object) -> Any:
        del kwargs
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"output", b"")

    monkeypatch.setattr(_AUDIT, "_find_dumpbin", lambda: dumpbin)
    monkeypatch.setattr(_AUDIT.subprocess, "run", fake_run)

    result = _AUDIT._default_dumpbin_runner(target)

    assert [arguments[1] for arguments in calls] == [
        "/HEADERS",
        "/DEPENDENTS",
        "/IMPORTS",
        "/EXPORTS",
    ]
    assert all(arguments[0] == os.fspath(dumpbin) for arguments in calls)
    assert all(arguments[2] == os.fspath(target) for arguments in calls)
    assert set(result["commands"]) == {
        "/HEADERS",
        "/DEPENDENTS",
        "/IMPORTS",
        "/EXPORTS",
    }


def test_string_report_redacts_embedded_user_paths() -> None:
    observations = _AUDIT._string_observations(
        [
            r"C:\Users\SensitiveName\source\depends.pdb",
            r"HKEY_LOCAL_MACHINE\Software\DependencyWalker",
            "https://example.com/path",
            "CreateRemoteThread profiling debug",
        ]
    )
    serialized = json.dumps(observations)

    assert "SensitiveName" not in serialized
    assert "<user-profile>" in serialized
    assert "https://example.com/path" in observations["urls"]
    assert observations["registry_paths"]
    assert observations["debug_injection_or_profiling"]


def test_suspicious_imports_distinguish_messages_from_network_calls() -> None:
    observations = _AUDIT._suspicious_imports(
        {
            "user32.dll": ["SendMessageA"],
            "ws2_32.dll": ["send"],
            "kernel32.dll": [
                "ContinueDebugEvent",
                "VirtualProtectEx",
                "WaitForDebugEvent",
            ],
        }
    )

    assert observations["network"] == ["ws2_32.dll!send"]
    assert observations["process_injection_or_debug"] == [
        "kernel32.dll!ContinueDebugEvent",
        "kernel32.dll!VirtualProtectEx",
        "kernel32.dll!WaitForDebugEvent",
    ]


def test_source_has_no_network_target_execution_or_cloud_scan_path() -> None:
    python_text = _PYTHON_SCRIPT.read_text(encoding="utf-8").casefold()
    powershell_text = _POWERSHELL_SCRIPT.read_text(encoding="utf-8").casefold()

    assert "import urllib" not in python_text
    assert "import socket" not in python_text
    assert "import requests" not in python_text
    assert "import httpx" not in python_text
    assert "ctypes" not in python_text
    assert "loadlibrary(" not in python_text
    assert "mpcmdrun" not in python_text
    assert "start-mpscan" not in powershell_text
    assert "start-process" not in powershell_text
    assert "rundll32" not in powershell_text
    assert "expand-archive" not in powershell_text
    assert "extracttodirectory" not in powershell_text
    assert "build_standalone.ps1" not in powershell_text


def test_module_import_is_filesystem_and_process_inert(tmp_path: Path) -> None:
    code = f"""
import importlib.util
import pathlib
import subprocess
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("import crossed external boundary")

pathlib.Path.mkdir = forbidden
pathlib.Path.write_bytes = forbidden
subprocess.run = forbidden
spec = importlib.util.spec_from_file_location(
    "_dependency_walker_binary_import_probe",
    {str(_PYTHON_SCRIPT)!r},
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print("dependency_walker_binary_import_inert=True")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert completed.stdout == "dependency_walker_binary_import_inert=True\n"
    assert completed.stderr == ""
