from __future__ import annotations

import importlib.util
import io
import json
import struct
import subprocess
import sys
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_SCRIPT = (
    _PROJECT_ROOT / "packaging" / "dependency_walker_quarantine.py"
)
_POWERSHELL_SCRIPT = (
    _PROJECT_ROOT / "packaging" / "acquire_dependency_walker.ps1"
)


def _load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_dependency_walker_quarantine_test",
        _AUDIT_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_AUDIT = _load_audit_module()


class _FakeResponse:
    def __init__(
        self,
        data: bytes,
        *,
        status: int = 200,
        final_url: str | None = None,
        headers: Mapping[str, str] | None = None,
        fail_after_reads: int | None = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._stream = io.BytesIO(data)
        self._final_url = final_url or _AUDIT.DEPENDENCY_WALKER_URL
        self._fail_after_reads = fail_after_reads
        self._read_count = 0
        self.read_sizes: list[int] = []
        self.closed = False

    def geturl(self) -> str:
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        self._read_count += 1
        self.read_sizes.append(size)
        if (
            self._fail_after_reads is not None
            and self._read_count > self._fail_after_reads
        ):
            raise OSError("sensitive-proxy-value")
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True


class _FakeTransport:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.open_count = 0
        self.requested_urls: list[str] = []

    def open(self, url: str) -> _FakeResponse:
        self.open_count += 1
        self.requested_urls.append(url)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _fake_pe(machine: int = 0x8664) -> bytes:
    payload = bytearray(512)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", payload, 0x84, machine)
    return bytes(payload)


def _zip_bytes(
    entries: Sequence[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return output.getvalue()


def _write_zip(
    path: Path,
    entries: Sequence[tuple[str | zipfile.ZipInfo, bytes]],
) -> None:
    path.write_bytes(_zip_bytes(entries))


def _patch_encrypted_flag(payload: bytes) -> bytes:
    patched = bytearray(payload)
    cursor = 0
    while True:
        cursor = patched.find(b"PK\x03\x04", cursor)
        if cursor < 0:
            break
        flags = struct.unpack_from("<H", patched, cursor + 6)[0]
        struct.pack_into("<H", patched, cursor + 6, flags | 0x1)
        cursor += 4
    cursor = 0
    while True:
        cursor = patched.find(b"PK\x01\x02", cursor)
        if cursor < 0:
            break
        flags = struct.unpack_from("<H", patched, cursor + 8)[0]
        struct.pack_into("<H", patched, cursor + 8, flags | 0x1)
        cursor += 4
    return bytes(patched)


def _patch_declared_size(payload: bytes, size: int) -> bytes:
    patched = bytearray(payload)
    local = patched.find(b"PK\x03\x04")
    central = patched.find(b"PK\x01\x02")
    assert local >= 0
    assert central >= 0
    struct.pack_into("<I", patched, local + 22, size)
    struct.pack_into("<I", patched, central + 24, size)
    return bytes(patched)


def _patch_all_declared_sizes(payload: bytes, size: int) -> bytes:
    patched = bytearray(payload)
    for signature, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        cursor = 0
        while True:
            cursor = patched.find(signature, cursor)
            if cursor < 0:
                break
            struct.pack_into("<I", patched, cursor + offset, size)
            cursor += 4
    return bytes(patched)


def _fixed_now() -> datetime:
    return datetime(2026, 7, 27, 1, 2, 3, tzinfo=UTC)


def _successful_transport(
    *,
    headers: Mapping[str, str] | None = None,
) -> tuple[_FakeTransport, bytes]:
    payload = _zip_bytes([("depends.exe", _fake_pe())])
    response = _FakeResponse(
        payload,
        headers=headers
        or {
            "Content-Length": str(len(payload)),
            "Content-Type": "application/zip",
        },
    )
    return _FakeTransport(response), payload


def test_powershell_default_mode_is_inert_and_requires_confirmation() -> None:
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
        "safe_code=dependency_walker_download_disabled\n"
    )
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "url",
    [
        "http://dependencywalker.com/depends22_x64.zip",
        "https://www.dependencywalker.com/depends22_x64.zip",
        "https://dependencywalker.com/other.zip",
        "https://user@dependencywalker.com/depends22_x64.zip",
        "https://dependencywalker.com:443/depends22_x64.zip",
        "https://dependencywalker.com/depends22_x64.zip?download=1",
        "https://dependencywalker.com/depends22_x64.zip#fragment",
    ],
)
def test_url_allowlist_rejects_every_variant(url: str) -> None:
    assert not _AUDIT.validate_dependency_walker_url(url)


def test_url_allowlist_accepts_only_fixed_https_url() -> None:
    assert _AUDIT.validate_dependency_walker_url(
        "https://dependencywalker.com/depends22_x64.zip"
    )
    powershell = _POWERSHELL_SCRIPT.read_text(encoding="utf-8")
    assert (
        '$DependencyWalkerUrl = '
        '"https://dependencywalker.com/depends22_x64.zip"'
    ) in powershell
    assert "$Uri.Authority -ne $ExpectedHost" in powershell


def test_redirect_is_rejected_without_second_request(tmp_path: Path) -> None:
    response = _FakeResponse(
        b"",
        status=302,
        final_url="https://other.example/depends22_x64.zip",
        headers={"Location": "https://other.example/depends22_x64.zip"},
    )
    transport = _FakeTransport(response)

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=transport,
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_redirect_rejected"
    assert transport.open_count == 1
    assert transport.requested_urls == [_AUDIT.DEPENDENCY_WALKER_URL]


def test_content_length_over_limit_fails_before_body_read(
    tmp_path: Path,
) -> None:
    response = _FakeResponse(
        b"ignored",
        headers={"Content-Length": str(_AUDIT.MAX_DOWNLOAD_BYTES + 1)},
    )
    transport = _FakeTransport(response)

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=transport,
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_download_too_large"
    assert response._read_count == 0


def test_content_length_lie_cannot_bypass_stream_limit(
    tmp_path: Path,
) -> None:
    payload = b"x" * (_AUDIT.MAX_DOWNLOAD_BYTES + 1)
    response = _FakeResponse(payload, headers={"Content-Length": "1"})

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=_FakeTransport(response),
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_download_too_large"
    assert list(tmp_path.rglob("*.part")) == []


def test_interrupted_stream_is_safely_mapped_and_part_is_removed(
    tmp_path: Path,
) -> None:
    response = _FakeResponse(
        b"x" * (_AUDIT.STREAM_CHUNK_BYTES * 2),
        fail_after_reads=1,
    )

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=_FakeTransport(response),
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_stream_interrupted"
    assert list(tmp_path.rglob("*.part")) == []
    assert "sensitive-proxy-value" not in repr(outcome)


def test_tls_or_network_exception_is_safely_mapped(tmp_path: Path) -> None:
    transport = _FakeTransport(error=OSError("sensitive-proxy-credential"))

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=transport,
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_network_error"
    assert "sensitive-proxy-credential" not in repr(outcome)
    assert list(tmp_path.rglob("*.part")) == []


def test_occupied_target_is_not_read_overwritten_or_deleted(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / _AUDIT.QUARANTINE_RELATIVE_PATH
        / _AUDIT.ZIP_FILENAME
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user-owned")
    transport, _ = _successful_transport()

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=transport,
        now=_fixed_now,
    )

    assert outcome.safe_code == "quarantine_target_occupied"
    assert target.read_bytes() == b"user-owned"
    assert transport.open_count == 0


def test_preexisting_unrelated_part_file_is_never_deleted(
    tmp_path: Path,
) -> None:
    quarantine = tmp_path / _AUDIT.QUARANTINE_RELATIVE_PATH
    quarantine.mkdir(parents=True)
    user_part = quarantine / "user-owned.part"
    user_part.write_bytes(b"preserve")
    response = _FakeResponse(b"x", fail_after_reads=0)

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=_FakeTransport(response),
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_stream_interrupted"
    assert user_part.read_bytes() == b"preserve"


def test_success_writes_hashes_relative_paths_and_no_sensitive_headers(
    tmp_path: Path,
) -> None:
    transport, payload = _successful_transport(
        headers={
            "Content-Length": "1",
            "Content-Type": "application/zip",
            "Cookie": "sensitive-cookie",
            "Authorization": "Bearer sensitive-token",
        }
    )

    outcome = _AUDIT.acquire_dependency_walker(
        tmp_path,
        transport=transport,
        now=_fixed_now,
    )

    assert outcome.safe_code == "dependency_walker_review_required"
    quarantine = tmp_path / _AUDIT.QUARANTINE_RELATIVE_PATH
    report_text = (quarantine / _AUDIT.DOWNLOAD_AUDIT_FILENAME).read_text(
        encoding="utf-8"
    )
    report = json.loads(report_text)
    assert report["actual_bytes"] == len(payload)
    assert report["zip_sha256"] == __import__("hashlib").sha256(payload).hexdigest()
    assert report["zip_sha512"] == __import__("hashlib").sha512(payload).hexdigest()
    assert report["redirected"] is False
    assert report["tls_succeeded"] is True
    assert report["local_path"].startswith("build/tool-quarantine/")
    assert str(tmp_path) not in report_text
    assert "sensitive-cookie" not in report_text
    assert "sensitive-token" not in report_text
    assert transport.response is not None
    assert all(size == _AUDIT.STREAM_CHUNK_BYTES for size in transport.response.read_sizes)


@pytest.mark.parametrize(
    "name",
    [
        "../depends.exe",
        "/depends.exe",
        "\\depends.exe",
        "\\\\server\\share\\depends.exe",
        "C:\\depends.exe",
        "depends.exe:stream",
        "folder/\x01depends.exe",
    ],
)
def test_unsafe_zip_paths_are_rejected(tmp_path: Path, name: str) -> None:
    path = tmp_path / "unsafe.zip"
    _write_zip(path, [(name, _fake_pe())])

    report = _AUDIT.audit_zip_archive(path)

    assert report["archive_safe"] is False
    assert report["checks"]["no_unsafe_paths_or_types"] is False


def test_nul_and_control_characters_are_detected_without_path_resolution() -> None:
    assert _AUDIT._has_control_character("folder/\x00depends.exe")
    assert _AUDIT._has_control_character("folder/\x1fdepends.exe")


def test_duplicate_and_case_duplicate_names_are_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicates.zip"
    _write_zip(
        path,
        [
            ("depends.exe", _fake_pe()),
            ("DEPENDS.EXE", _fake_pe()),
        ],
    )

    report = _AUDIT.audit_zip_archive(path)

    assert report["duplicate_names_case_insensitive"] == ["depends.exe"]
    assert report["depends_exe_count"] == 2
    assert report["archive_safe"] is False


def test_encrypted_entry_flag_is_rejected_without_opening_entry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "encrypted.zip"
    payload = _zip_bytes([("depends.exe", _fake_pe())])
    path.write_bytes(_patch_encrypted_flag(payload))

    report = _AUDIT.audit_zip_archive(path)

    assert report["entries"][0]["encrypted"] is True
    assert report["entries"][0]["sha256"] is None
    assert report["checks"]["no_encrypted_entries"] is False
    assert report["archive_safe"] is False


def test_symlink_entry_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("depends.exe")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    _write_zip(path, [(link, b"target")])

    report = _AUDIT.audit_zip_archive(path)

    assert report["entries"][0]["symlink"] is True
    assert report["archive_safe"] is False


def test_declared_single_file_size_over_limit_is_rejected_before_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "oversize.zip"
    payload = _zip_bytes([("depends.exe", _fake_pe())])
    path.write_bytes(
        _patch_declared_size(
            payload,
            _AUDIT.MAX_SINGLE_UNCOMPRESSED_BYTES + 1,
        )
    )

    report = _AUDIT.audit_zip_archive(path)

    assert report["checks"]["single_file_size_within_limit"] is False
    assert report["entries"][0]["sha256"] is None
    assert report["archive_safe"] is False


def test_declared_total_size_over_limit_is_rejected_before_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "total-oversize.zip"
    payload = _zip_bytes(
        [
            ("depends.exe", _fake_pe()),
            ("one.bin", b"1"),
            ("two.bin", b"2"),
        ]
    )
    per_entry_size = 11 * 1024 * 1024
    path.write_bytes(_patch_all_declared_sizes(payload, per_entry_size))

    report = _AUDIT.audit_zip_archive(path)

    assert report["checks"]["total_uncompressed_size_within_limit"] is False
    assert all(entry["sha256"] is None for entry in report["entries"])
    assert report["archive_safe"] is False


def test_abnormal_compression_ratio_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ratio.zip"
    _write_zip(path, [("depends.exe", b"\x00" * 2_000_000)])

    report = _AUDIT.audit_zip_archive(path)

    assert report["checks"]["compression_ratio_within_limit"] is False
    assert report["entries"][0]["sha256"] is None
    assert report["archive_safe"] is False


def test_more_than_64_entries_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "many.zip"
    entries = [(f"file-{index}.txt", b"x") for index in range(64)]
    entries.append(("depends.exe", _fake_pe()))
    _write_zip(path, entries)

    report = _AUDIT.audit_zip_archive(path)

    assert report["entry_count"] == 65
    assert report["checks"]["entry_count_within_limit"] is False
    assert report["archive_safe"] is False


def test_missing_and_multiple_depends_exe_are_rejected(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.zip"
    multiple = tmp_path / "multiple.zip"
    _write_zip(missing, [("readme.txt", b"text")])
    _write_zip(
        multiple,
        [
            ("a/depends.exe", _fake_pe()),
            ("b/depends.exe", _fake_pe()),
        ],
    )

    missing_report = _AUDIT.audit_zip_archive(missing)
    multiple_report = _AUDIT.audit_zip_archive(multiple)

    assert missing_report["depends_exe_count"] == 0
    assert multiple_report["depends_exe_count"] == 2
    assert missing_report["archive_safe"] is False
    assert multiple_report["archive_safe"] is False


@pytest.mark.parametrize("machine", [0x014C, 0x0200])
def test_x86_and_ia64_pe_are_rejected(
    tmp_path: Path,
    machine: int,
) -> None:
    path = tmp_path / f"machine-{machine}.zip"
    _write_zip(path, [("depends.exe", _fake_pe(machine))])

    report = _AUDIT.audit_zip_archive(path)

    assert report["depends_exe_pe"]["machine"] == machine
    assert report["depends_exe_pe"]["is_amd64"] is False
    assert report["archive_safe"] is False


def test_non_pe_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "not-pe.zip"
    _write_zip(path, [("depends.exe", b"not a PE")])

    report = _AUDIT.audit_zip_archive(path)

    assert report["depends_exe_pe"]["has_mz_header"] is False
    assert report["archive_safe"] is False


def test_amd64_pe_is_recognized_and_stream_hashed(tmp_path: Path) -> None:
    path = tmp_path / "amd64.zip"
    payload = _fake_pe()
    _write_zip(path, [("depends.exe", payload)])

    report = _AUDIT.audit_zip_archive(path)

    assert report["depends_exe_pe"] == {
        "has_mz_header": True,
        "has_pe_signature": True,
        "machine": 0x8664,
        "machine_hex": "0x8664",
        "is_amd64": True,
    }
    assert report["entries"][0]["sha256"] is not None
    assert report["archive_safe"] is True


def test_other_archive_files_require_manual_review(tmp_path: Path) -> None:
    path = tmp_path / "extra.zip"
    _write_zip(
        path,
        [
            ("depends.exe", _fake_pe()),
            ("depends.chm", b"help"),
        ],
    )

    report = _AUDIT.audit_zip_archive(path)

    assert report["archive_safe"] is True
    assert report["manual_review_required"] is True
    assert report["other_non_directory_entries"] == ["depends.chm"]


def test_source_contains_no_extraction_or_execution_path() -> None:
    python_text = _AUDIT_SCRIPT.read_text(encoding="utf-8").casefold()
    powershell_text = _POWERSHELL_SCRIPT.read_text(encoding="utf-8").casefold()

    forbidden_python = (
        "extract(",
        "extractall",
        "subprocess",
        "ctypes",
        "loadlibrary",
        "os.system",
    )
    forbidden_powershell = (
        "expand-archive",
        "extracttodirectory",
        "extracttofile",
        "start-process",
        "build_standalone.ps1",
        "assume-yes-for-downloads",
    )
    assert all(term not in python_text for term in forbidden_python)
    assert all(term not in powershell_text for term in forbidden_powershell)


def test_build_quarantine_is_git_ignored() -> None:
    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "build/tool-quarantine/dependency-walker/depends22_x64.zip",
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert ignored.returncode == 0
    assert ignored.stdout.strip() == (
        "build/tool-quarantine/dependency-walker/depends22_x64.zip"
    )


def test_module_import_is_network_and_filesystem_inert(
    tmp_path: Path,
) -> None:
    code = f"""
import importlib.util
import pathlib
import socket
import urllib.request

def forbidden(*args, **kwargs):
    raise AssertionError("import crossed I/O boundary")

socket.socket = forbidden
urllib.request.urlopen = forbidden
pathlib.Path.mkdir = forbidden
pathlib.Path.write_bytes = forbidden
spec = importlib.util.spec_from_file_location(
    "_dependency_walker_import_probe",
    {str(_AUDIT_SCRIPT)!r},
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print("dependency_walker_import_inert=True")
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
    assert completed.stdout == "dependency_walker_import_inert=True\n"
    assert completed.stderr == ""
