from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import uuid
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

ZIP_RELATIVE_PATH = Path(
    "build/tool-quarantine/dependency-walker/depends22_x64.zip"
)
EXTRACTED_RELATIVE_PATH = Path(
    "build/tool-quarantine/dependency-walker/extracted"
)
BINARY_AUDIT_RELATIVE_PATH = Path(
    "build/tool-quarantine/dependency-walker/binary_audit.json"
)
EXPECTED_ZIP_SIZE = 468_618
EXPECTED_ZIP_SHA256 = (
    "35db68a613874a2e8c1422eb0ea7861f825fc71717d46dabf1f249ce9634b4f1"
)
EXPECTED_ENTRY_HASHES = {
    "depends.exe": (
        "57c483dc985a9757501993e969c2a7043c26517f97fd49a42b33d2d6a4193d8b"
    ),
    "depends.dll": (
        "7a5cae7605ae5d8c8aee3e6d8e77e455537b636b395b8f00aebe17bf8b228770"
    ),
    "depends.chm": (
        "e5a4e001fbfe731b5d8b9d2046c57fa1786599364366704a800d59239d0c064d"
    ),
}
EXTRACTABLE_ENTRIES = ("depends.exe", "depends.dll")
REQUIRED_MSVC_VERSION = "14.44.35207"
STREAM_CHUNK_BYTES = 64 * 1024
MAX_BINARY_BYTES = 2 * 1024 * 1024
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
PE_MACHINE_AMD64 = 0x8664
PE32_PLUS_MAGIC = 0x20B

IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA = 0x0020
IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE = 0x0040
IMAGE_DLLCHARACTERISTICS_NX_COMPAT = 0x0100
IMAGE_DLLCHARACTERISTICS_GUARD_CF = 0x4000
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000

_SUSPICIOUS_API_PATTERNS = {
    "network": re.compile(
        r"(?i)^(?:WSA|socket$|connect$|send$|recv$|Internet|"
        r"WinHttp|URLDownload)"
    ),
    "process_injection_or_debug": re.compile(
        r"(?i)(?:OpenProcess|WriteProcessMemory|ReadProcessMemory|"
        r"CreateRemoteThread|VirtualAllocEx|VirtualProtectEx|"
        r"VirtualQueryEx|DebugActiveProcess|WaitForDebugEvent|"
        r"ContinueDebugEvent|GetThreadContext|SetThreadContext|"
        r"SetWindowsHookEx|NtMapViewOfSection)"
    ),
    "registry": re.compile(r"(?i)^Reg(?:Open|Create|Set|Delete|Query)"),
    "service_driver_or_persistence": re.compile(
        r"(?i)(?:OpenSCManager|CreateService|StartService|"
        r"DeleteService|AdjustTokenPrivileges)"
    ),
}


@dataclass(frozen=True, slots=True)
class BinaryAuditOutcome:
    safe_code: str
    completed: bool


@dataclass(frozen=True, slots=True)
class _Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int


@dataclass(frozen=True, slots=True)
class _PELayout:
    data: bytes
    sections: tuple[_Section, ...]
    is_pe32_plus: bool
    machine: int
    timestamp: int
    image_base: int
    subsystem: int
    dll_characteristics: int
    data_directories: tuple[tuple[int, int], ...]


DumpbinRunner = Callable[[Path], dict[str, object]]
VersionReader = Callable[[Path], dict[str, str | None]]


def _sha256_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(STREAM_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        stat_result = path.lstat()
    except OSError:
        return True
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((path, root)) == os.fspath(root)
    except ValueError:
        return False


def _validate_existing_path_chain(root: Path, target: Path) -> bool:
    resolved_root = root.resolve(strict=True)
    current = resolved_root
    relative = target.relative_to(root)
    for part in relative.parts:
        current = current / part
        if not current.exists():
            continue
        if _is_reparse_point(current):
            return False
        if not _path_is_within(current.resolve(strict=True), resolved_root):
            return False
    return True


def _atomic_write_json(path: Path, payload: object) -> bool:
    if path.exists():
        return False
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    created = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            json.dump(
                payload,
                stream,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, path)
        created = False
        return True
    except OSError:
        return False
    finally:
        if created:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def _verify_zip_and_entries(zip_path: Path) -> str | None:
    try:
        if zip_path.stat().st_size != EXPECTED_ZIP_SIZE:
            return "dependency_walker_zip_size_mismatch"
        if _sha256_file(zip_path) != EXPECTED_ZIP_SHA256:
            return "dependency_walker_zip_hash_mismatch"
        with zipfile.ZipFile(zip_path, mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if sorted(names) != sorted(EXPECTED_ENTRY_HASHES):
                return "dependency_walker_archive_entries_mismatch"
            for info in infos:
                if info.is_dir() or info.filename not in EXPECTED_ENTRY_HASHES:
                    return "dependency_walker_archive_entries_mismatch"
                if info.flag_bits & 0x1:
                    return "dependency_walker_archive_encrypted"
                with archive.open(info, mode="r") as entry_stream:
                    actual_hash = _sha256_stream(entry_stream)
                if actual_hash != EXPECTED_ENTRY_HASHES[info.filename]:
                    return "dependency_walker_entry_hash_mismatch"
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return "dependency_walker_archive_invalid"
    return None


def _extract_allowed_entries(
    repository_root: Path,
    zip_path: Path,
    extracted_dir: Path,
) -> str | None:
    if not _validate_existing_path_chain(repository_root, zip_path):
        return "dependency_walker_reparse_point_rejected"
    if not _validate_existing_path_chain(repository_root, extracted_dir.parent):
        return "dependency_walker_reparse_point_rejected"
    try:
        extracted_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return "dependency_walker_extraction_directory_unavailable"
    if (
        _is_reparse_point(extracted_dir)
        or not _path_is_within(
            extracted_dir.resolve(strict=True),
            repository_root.resolve(strict=True),
        )
    ):
        return "dependency_walker_reparse_point_rejected"

    targets = {
        name: extracted_dir / name for name in EXTRACTABLE_ENTRIES
    }
    if any(path.exists() or path.is_symlink() for path in targets.values()):
        return "dependency_walker_extraction_target_occupied"

    lock_path = extracted_dir / f".audit-lock.{uuid.uuid4().hex}.part"
    temporary_paths: dict[str, Path] = {}
    lock_stream: IO[bytes] | None = None
    try:
        lock_stream = lock_path.open("xb")
        with zipfile.ZipFile(zip_path, mode="r") as archive:
            for name in EXTRACTABLE_ENTRIES:
                info = archive.getinfo(name)
                temporary = extracted_dir / (
                    f".{name}.{uuid.uuid4().hex}.part"
                )
                temporary_paths[name] = temporary
                digest = hashlib.sha256()
                actual_size = 0
                with (
                    archive.open(info, mode="r") as source,
                    temporary.open("xb") as destination,
                ):
                    while True:
                        chunk = source.read(STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        actual_size += len(chunk)
                        if actual_size > MAX_BINARY_BYTES:
                            return "dependency_walker_entry_too_large"
                        destination.write(chunk)
                        digest.update(chunk)
                    destination.flush()
                    os.fsync(destination.fileno())
                if digest.hexdigest() != EXPECTED_ENTRY_HASHES[name]:
                    return "dependency_walker_entry_hash_mismatch"

        if (
            _is_reparse_point(extracted_dir)
            or not _path_is_within(
                extracted_dir.resolve(strict=True),
                repository_root.resolve(strict=True),
            )
        ):
            return "dependency_walker_path_replaced"
        for name in EXTRACTABLE_ENTRIES:
            target = targets[name]
            if target.exists() or target.is_symlink():
                return "dependency_walker_extraction_target_occupied"
            os.rename(temporary_paths[name], target)
            temporary_paths.pop(name)
        return None
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
        return "dependency_walker_extraction_failed"
    finally:
        if lock_stream is not None:
            lock_stream.close()
        with contextlib.suppress(OSError):
            lock_path.unlink(missing_ok=True)
        for temporary in temporary_paths.values():
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def _validate_existing_extraction(
    repository_root: Path,
    extracted_dir: Path,
) -> str | None:
    if not extracted_dir.is_dir():
        return "dependency_walker_extraction_target_occupied"
    if not _validate_existing_path_chain(repository_root, extracted_dir):
        return "dependency_walker_reparse_point_rejected"
    try:
        entries = sorted(path.name for path in extracted_dir.iterdir())
    except OSError:
        return "dependency_walker_extraction_directory_unavailable"
    if entries != sorted(EXTRACTABLE_ENTRIES):
        return "dependency_walker_extraction_target_occupied"
    try:
        for name in EXTRACTABLE_ENTRIES:
            path = extracted_dir / name
            if (
                not path.is_file()
                or _is_reparse_point(path)
                or _sha256_file(path) != EXPECTED_ENTRY_HASHES[name]
            ):
                return "dependency_walker_extraction_target_occupied"
    except OSError:
        return "dependency_walker_extraction_target_occupied"
    return None


def _read_c_string(data: bytes, offset: int, *, limit: int = 4096) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\x00", offset, min(len(data), offset + limit))
    if end < 0:
        return ""
    return data[offset:end].decode("ascii", errors="replace")


def _rva_to_offset(layout: _PELayout, rva: int) -> int | None:
    for section in layout.sections:
        span = max(section.virtual_size, section.raw_size)
        if section.virtual_address <= rva < section.virtual_address + span:
            offset = section.raw_offset + (rva - section.virtual_address)
            if 0 <= offset < len(layout.data):
                return offset
    return None


def _parse_pe_layout(data: bytes) -> _PELayout:
    if len(data) < 0x100 or data[:2] != b"MZ":
        raise ValueError("invalid_pe")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("invalid_pe")
    coff = pe_offset + 4
    machine, section_count, timestamp = struct.unpack_from("<HHI", data, coff)
    optional_size = struct.unpack_from("<H", data, coff + 16)[0]
    optional = coff + 20
    if optional + optional_size > len(data):
        raise ValueError("invalid_pe")
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic != PE32_PLUS_MAGIC:
        raise ValueError("not_pe32_plus")
    image_base = struct.unpack_from("<Q", data, optional + 24)[0]
    subsystem = struct.unpack_from("<H", data, optional + 68)[0]
    dll_characteristics = struct.unpack_from("<H", data, optional + 70)[0]
    directory_count = min(
        struct.unpack_from("<I", data, optional + 108)[0],
        16,
    )
    directories = tuple(
        struct.unpack_from("<II", data, optional + 112 + index * 8)
        for index in range(directory_count)
    )
    section_table = optional + optional_size
    if section_table + section_count * 40 > len(data):
        raise ValueError("invalid_pe")
    sections: list[_Section] = []
    for index in range(section_count):
        offset = section_table + index * 40
        name = data[offset : offset + 8].split(b"\x00", 1)[0].decode(
            "ascii",
            errors="replace",
        )
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII",
            data,
            offset + 8,
        )
        characteristics = struct.unpack_from("<I", data, offset + 36)[0]
        if raw_offset + raw_size > len(data):
            raise ValueError("invalid_pe")
        sections.append(
            _Section(
                name,
                virtual_address,
                virtual_size,
                raw_offset,
                raw_size,
                characteristics,
            )
        )
    return _PELayout(
        data,
        tuple(sections),
        True,
        machine,
        timestamp,
        image_base,
        subsystem,
        dll_characteristics,
        directories,
    )


def _parse_imports(layout: _PELayout) -> dict[str, list[str]]:
    if len(layout.data_directories) <= 1:
        return {}
    import_rva, import_size = layout.data_directories[1]
    if import_rva == 0 or import_size == 0:
        return {}
    descriptor_offset = _rva_to_offset(layout, import_rva)
    if descriptor_offset is None:
        raise ValueError("invalid_import_directory")
    imports: dict[str, list[str]] = {}
    for descriptor_index in range(1024):
        offset = descriptor_offset + descriptor_index * 20
        if offset + 20 > len(layout.data):
            raise ValueError("invalid_import_directory")
        original_thunk, _, _, name_rva, first_thunk = struct.unpack_from(
            "<IIIII",
            layout.data,
            offset,
        )
        if not any((original_thunk, name_rva, first_thunk)):
            break
        name_offset = _rva_to_offset(layout, name_rva)
        if name_offset is None:
            raise ValueError("invalid_import_name")
        dll_name = _read_c_string(layout.data, name_offset).casefold()
        if not dll_name:
            raise ValueError("invalid_import_name")
        thunk_rva = original_thunk or first_thunk
        thunk_offset = _rva_to_offset(layout, thunk_rva)
        if thunk_offset is None:
            raise ValueError("invalid_import_thunk")
        functions: list[str] = []
        for thunk_index in range(65536):
            value_offset = thunk_offset + thunk_index * 8
            if value_offset + 8 > len(layout.data):
                raise ValueError("invalid_import_thunk")
            thunk_value = struct.unpack_from("<Q", layout.data, value_offset)[0]
            if thunk_value == 0:
                break
            if thunk_value & (1 << 63):
                functions.append(f"ordinal:{thunk_value & 0xFFFF}")
                continue
            hint_name_offset = _rva_to_offset(layout, int(thunk_value))
            if hint_name_offset is None or hint_name_offset + 2 >= len(layout.data):
                raise ValueError("invalid_import_function")
            function_name = _read_c_string(layout.data, hint_name_offset + 2)
            if not function_name:
                raise ValueError("invalid_import_function")
            functions.append(function_name)
        imports[dll_name] = sorted(set(functions), key=str.casefold)
    return dict(sorted(imports.items()))


def _parse_exports(layout: _PELayout) -> list[str]:
    if not layout.data_directories:
        return []
    export_rva, export_size = layout.data_directories[0]
    if export_rva == 0 or export_size == 0:
        return []
    export_offset = _rva_to_offset(layout, export_rva)
    if export_offset is None or export_offset + 40 > len(layout.data):
        raise ValueError("invalid_export_directory")
    ordinal_base, function_count, name_count = struct.unpack_from(
        "<III",
        layout.data,
        export_offset + 16,
    )
    functions_rva = struct.unpack_from(
        "<I",
        layout.data,
        export_offset + 28,
    )[0]
    names_rva = struct.unpack_from("<I", layout.data, export_offset + 32)[0]
    ordinals_rva = struct.unpack_from("<I", layout.data, export_offset + 36)[0]
    functions_offset = _rva_to_offset(layout, functions_rva)
    if function_count and functions_offset is None:
        raise ValueError("invalid_export_functions")
    exported_ordinals: set[int] = set()
    if functions_offset is not None:
        for index in range(min(function_count, 65536)):
            item_offset = functions_offset + index * 4
            if item_offset + 4 > len(layout.data):
                raise ValueError("invalid_export_functions")
            if struct.unpack_from("<I", layout.data, item_offset)[0] != 0:
                exported_ordinals.add(ordinal_base + index)
    if name_count == 0:
        return [f"ordinal:{ordinal}" for ordinal in sorted(exported_ordinals)]
    names_offset = _rva_to_offset(layout, names_rva)
    ordinals_offset = _rva_to_offset(layout, ordinals_rva)
    if names_offset is None or ordinals_offset is None:
        raise ValueError("invalid_export_names")
    exports: list[str] = []
    named_ordinals: set[int] = set()
    for index in range(min(name_count, 65536)):
        item_offset = names_offset + index * 4
        ordinal_offset = ordinals_offset + index * 2
        if (
            item_offset + 4 > len(layout.data)
            or ordinal_offset + 2 > len(layout.data)
        ):
            raise ValueError("invalid_export_names")
        name_rva = struct.unpack_from("<I", layout.data, item_offset)[0]
        function_index = struct.unpack_from(
            "<H",
            layout.data,
            ordinal_offset,
        )[0]
        if function_index >= function_count:
            raise ValueError("invalid_export_ordinal")
        named_ordinals.add(ordinal_base + function_index)
        name_offset = _rva_to_offset(layout, name_rva)
        if name_offset is None:
            raise ValueError("invalid_export_name")
        name = _read_c_string(layout.data, name_offset)
        if name:
            exports.append(name)
    exports.extend(
        f"ordinal:{ordinal}"
        for ordinal in sorted(exported_ordinals - named_ordinals)
    )
    return sorted(set(exports), key=str.casefold)


def _inspect_authenticode(layout: _PELayout) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "unsigned",
        "signature_validation": "not_applicable",
        "certificate_table_present": False,
        "certificate_table_offset": 0,
        "certificate_table_size": 0,
        "pkcs7_signed_data_present": False,
        "signer_count": None,
        "subject": None,
        "issuer": None,
        "serial_number": None,
        "certificate_sha256_thumbprint": None,
        "valid_from": None,
        "valid_to": None,
        "timestamp_attribute_present": None,
        "digest_algorithm": None,
        "file_digest_matches": None,
    }
    if len(layout.data_directories) <= 4:
        return result
    table_offset, table_size = layout.data_directories[4]
    result["certificate_table_offset"] = table_offset
    result["certificate_table_size"] = table_size
    if table_offset == 0 and table_size == 0:
        return result
    result["certificate_table_present"] = True
    if (
        table_offset % 8 != 0
        or table_size < 8
        or table_offset > len(layout.data)
        or table_size > len(layout.data) - table_offset
    ):
        result["status"] = "embedded_signature_invalid"
        result["signature_validation"] = "invalid"
        return result
    certificate_length, revision, certificate_type = struct.unpack_from(
        "<IHH",
        layout.data,
        table_offset,
    )
    result["win_certificate_length"] = certificate_length
    result["win_certificate_revision"] = f"0x{revision:04X}"
    result["win_certificate_type"] = f"0x{certificate_type:04X}"
    if (
        certificate_length < 8
        or certificate_length > table_size
        or certificate_type != 0x0002
    ):
        result["status"] = "embedded_signature_invalid"
        result["signature_validation"] = "invalid"
        return result
    certificate_blob = layout.data[
        table_offset + 8 : table_offset + certificate_length
    ]
    result["pkcs7_sha256"] = hashlib.sha256(certificate_blob).hexdigest()
    result["pkcs7_signed_data_present"] = (
        certificate_blob.startswith(b"\x30") and len(certificate_blob) > 16
    )
    if not result["pkcs7_signed_data_present"]:
        result["status"] = "embedded_signature_invalid"
        result["signature_validation"] = "invalid"
        return result
    result["status"] = "embedded_signature_present"
    result["signature_validation"] = "unavailable"
    return result


def _timestamp_text(timestamp: int) -> str | None:
    try:
        return datetime.fromtimestamp(timestamp, UTC).isoformat().replace(
            "+00:00",
            "Z",
        )
    except (OSError, OverflowError, ValueError):
        return None


def _extract_strings(data: bytes) -> list[str]:
    ascii_strings = {
        match.group().decode("ascii", errors="replace")
        for match in re.finditer(rb"[\x20-\x7E]{4,}", data)
    }
    utf16_strings = {
        match.group().decode("utf-16le", errors="replace")
        for match in re.finditer(rb"(?:[\x20-\x7E]\x00){4,}", data)
    }
    return sorted(ascii_strings | utf16_strings, key=str.casefold)


def _redact_embedded_path(value: str) -> str:
    value = re.sub(
        r"(?i)(?:[A-Z]:\\)?Users\\[^\\\s]+",
        r"<user-profile>",
        value,
    )
    return re.sub(
        r"(?i)(?:[A-Z]:\\)?Documents and Settings\\[^\\\s]+",
        r"<user-profile>",
        value,
    )


def _string_observations(strings: Sequence[str]) -> dict[str, list[str]]:
    categories: dict[str, set[str]] = {
        "urls": set(),
        "domains": set(),
        "file_paths": set(),
        "registry_paths": set(),
        "command_line_tools": set(),
        "debug_injection_or_profiling": set(),
        "persistence": set(),
    }
    for value in strings:
        safe_value = _redact_embedded_path(value)
        for url in re.findall(r"(?i)https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", safe_value):
            categories["urls"].add(url[:512])
        for domain in re.findall(
            r"(?i)\b(?:[A-Za-z0-9-]+\.)+(?:com|net|org|gov|edu|io)\b",
            safe_value,
        ):
            categories["domains"].add(domain)
        if re.search(r"(?i)(?:[A-Z]:\\|\\\\)[^\x00\r\n]{2,}", safe_value):
            categories["file_paths"].add(safe_value[:512])
        if re.search(r"(?i)(?:HKEY_|HKLM\\|HKCU\\|\\Software\\)", safe_value):
            categories["registry_paths"].add(safe_value[:512])
        if re.search(
            r"(?i)\b(?:cmd|powershell|rundll32|regsvr32|schtasks|sc)\.exe\b",
            safe_value,
        ):
            categories["command_line_tools"].add(safe_value[:512])
        if re.search(
            r"(?i)(?:debug|inject|profil|CreateRemoteThread|"
            r"WriteProcessMemory|ReadProcessMemory|SetWindowsHookEx)",
            safe_value,
        ):
            categories["debug_injection_or_profiling"].add(safe_value[:512])
        if re.search(
            r"(?i)(?:\\CurrentVersion\\Run(?:Once)?\b|"
            r"CreateService|Startup\\|schtasks)",
            safe_value,
        ):
            categories["persistence"].add(safe_value[:512])
    return {
        category: sorted(values, key=str.casefold)[:128]
        for category, values in categories.items()
    }


def _suspicious_imports(
    imports: dict[str, list[str]],
) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {
        category: set() for category in _SUSPICIOUS_API_PATTERNS
    }
    for dll_name, functions in imports.items():
        for function in functions:
            for category, pattern in _SUSPICIOUS_API_PATTERNS.items():
                if pattern.search(function):
                    result[category].add(f"{dll_name}!{function}")
    return {
        category: sorted(values, key=str.casefold)
        for category, values in result.items()
    }


def _inspect_binary(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) > MAX_BINARY_BYTES:
        raise ValueError("binary_too_large")
    layout = _parse_pe_layout(data)
    imports = _parse_imports(layout)
    exports = _parse_exports(layout)
    sections = [
        {
            "name": section.name,
            "virtual_address": f"0x{section.virtual_address:X}",
            "virtual_size": section.virtual_size,
            "raw_size": section.raw_size,
            "readable": bool(section.characteristics & IMAGE_SCN_MEM_READ),
            "writable": bool(section.characteristics & IMAGE_SCN_MEM_WRITE),
            "executable": bool(section.characteristics & IMAGE_SCN_MEM_EXECUTE),
            "writable_and_executable": bool(
                section.characteristics & IMAGE_SCN_MEM_WRITE
                and section.characteristics & IMAGE_SCN_MEM_EXECUTE
            ),
            "characteristics": f"0x{section.characteristics:08X}",
        }
        for section in layout.sections
    ]
    strings = _extract_strings(data)
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "machine": layout.machine,
        "machine_hex": f"0x{layout.machine:04X}",
        "is_amd64": layout.machine == PE_MACHINE_AMD64,
        "pe_format": "PE32+" if layout.is_pe32_plus else "PE32",
        "subsystem": layout.subsystem,
        "image_base": f"0x{layout.image_base:X}",
        "pe_timestamp": layout.timestamp,
        "pe_timestamp_utc": _timestamp_text(layout.timestamp),
        "dll_characteristics": f"0x{layout.dll_characteristics:04X}",
        "security_features": {
            "aslr_dynamic_base": bool(
                layout.dll_characteristics
                & IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE
            ),
            "dep_nx_compat": bool(
                layout.dll_characteristics
                & IMAGE_DLLCHARACTERISTICS_NX_COMPAT
            ),
            "control_flow_guard": bool(
                layout.dll_characteristics
                & IMAGE_DLLCHARACTERISTICS_GUARD_CF
            ),
            "high_entropy_va": bool(
                layout.dll_characteristics
                & IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA
            ),
        },
        "sections": sections,
        "has_writable_executable_section": any(
            bool(section["writable_and_executable"]) for section in sections
        ),
        "dependent_dlls": sorted(imports, key=str.casefold),
        "imports": imports,
        "exports": exports,
        "suspicious_imports": _suspicious_imports(imports),
        "string_observations": _string_observations(strings),
        "authenticode": _inspect_authenticode(layout),
    }


def _find_dumpbin() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft Visual Studio/Installer/vswhere.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft Visual Studio/Installer/vswhere.exe",
    )
    vswhere = next(
        (path for path in candidates if path.is_file()),
        None,
    )
    if vswhere is None:
        raise OSError("vswhere_unavailable")
    completed = subprocess.run(
        [
            os.fspath(vswhere),
            "-all",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise OSError("vswhere_failed")
    for line in completed.stdout.splitlines():
        installation = Path(line.strip())
        tool_root = (
            installation
            / "VC"
            / "Tools"
            / "MSVC"
            / REQUIRED_MSVC_VERSION
            / "bin"
            / "Hostx64"
            / "x64"
        )
        required = tuple(
            tool_root / name
            for name in ("cl.exe", "link.exe", "dumpbin.exe")
        )
        if all(path.is_file() for path in required):
            return required[2]
    raise OSError("dumpbin_unavailable")


def _default_dumpbin_runner(path: Path) -> dict[str, object]:
    dumpbin = _find_dumpbin()
    commands: dict[str, object] = {}
    for option in ("/HEADERS", "/DEPENDENTS", "/IMPORTS", "/EXPORTS"):
        completed = subprocess.run(
            [os.fspath(dumpbin), option, os.fspath(path)],
            check=False,
            capture_output=True,
            timeout=60,
        )
        output = completed.stdout + completed.stderr
        commands[option] = {
            "exit_code": completed.returncode,
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "output_bytes": len(output),
        }
        if completed.returncode != 0:
            raise OSError("dumpbin_failed")
    return {
        "tool": "MSVC 14.44 dumpbin.exe",
        "host_arch": "amd64",
        "target_arch": "amd64",
        "commands": commands,
    }


def _default_version_reader(path: Path) -> dict[str, str | None]:
    command = (
        "$i=[System.Diagnostics.FileVersionInfo]::GetVersionInfo("
        "$env:SJTUCLAW_AUDIT_FILE);"
        "[pscustomobject]@{"
        "file_description=$i.FileDescription;"
        "product_name=$i.ProductName;"
        "company_name=$i.CompanyName;"
        "file_version=$i.FileVersion;"
        "product_version=$i.ProductVersion;"
        "original_filename=$i.OriginalFilename;"
        "copyright=$i.LegalCopyright"
        "}|ConvertTo-Json -Compress"
    )
    environment = dict(os.environ)
    environment["SJTUCLAW_AUDIT_FILE"] = os.fspath(path)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    if completed.returncode != 0:
        raise OSError("version_resource_unavailable")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("invalid_version_resource")
    allowed = {
        "file_description",
        "product_name",
        "company_name",
        "file_version",
        "product_version",
        "original_filename",
        "copyright",
    }
    return {
        key: str(value) if value is not None else None
        for key, value in payload.items()
        if key in allowed
    }


def audit_dependency_walker_binaries(
    repository_root: Path,
    *,
    dumpbin_runner: DumpbinRunner = _default_dumpbin_runner,
    version_reader: VersionReader = _default_version_reader,
) -> BinaryAuditOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return BinaryAuditOutcome("repository_root_unavailable", False)
    zip_path = root / ZIP_RELATIVE_PATH
    extracted_dir = root / EXTRACTED_RELATIVE_PATH
    report_path = root / BINARY_AUDIT_RELATIVE_PATH
    if report_path.exists():
        return BinaryAuditOutcome("binary_audit_target_occupied", False)
    if not zip_path.is_file() or _is_reparse_point(zip_path):
        return BinaryAuditOutcome("dependency_walker_zip_unavailable", False)

    verification_error = _verify_zip_and_entries(zip_path)
    if verification_error is not None:
        return BinaryAuditOutcome(verification_error, False)
    if extracted_dir.exists():
        extraction_error = _validate_existing_extraction(root, extracted_dir)
    else:
        extraction_error = _extract_allowed_entries(
            root,
            zip_path,
            extracted_dir,
        )
    if extraction_error is not None:
        return BinaryAuditOutcome(extraction_error, False)

    binaries: dict[str, object] = {}
    try:
        for name in EXTRACTABLE_ENTRIES:
            path = extracted_dir / name
            if _is_reparse_point(path):
                return BinaryAuditOutcome(
                    "dependency_walker_reparse_point_rejected",
                    False,
                )
            binary_report = _inspect_binary(path)
            binary_report["version_resource"] = version_reader(path)
            binary_report["dumpbin"] = dumpbin_runner(path)
            binaries[name] = binary_report
    except Exception:
        return BinaryAuditOutcome("dependency_walker_static_audit_failed", False)

    exe = binaries["depends.exe"]
    dll = binaries["depends.dll"]
    if not isinstance(exe, dict) or not isinstance(dll, dict):
        return BinaryAuditOutcome("dependency_walker_static_audit_failed", False)
    exe_dependencies = {
        str(item).casefold()
        for item in exe.get("dependent_dlls", [])
    }
    exe_depends_on_dll = "depends.dll" in exe_dependencies
    dll_exports = [str(item) for item in dll.get("exports", [])]
    report = {
        "schema_version": 1,
        "zip_sha256": EXPECTED_ZIP_SHA256,
        "extracted_directory": (
            "build/tool-quarantine/dependency-walker/extracted"
        ),
        "binaries": binaries,
        "relationship_analysis": {
            "depends_exe_statically_imports_depends_dll": exe_depends_on_dll,
            "depends_dll_exports": dll_exports,
            "depends_dll_only_used_for_profiling_proven": False,
            "depends_dll_runtime_profile_helper_evidence": "strong",
            "nuitka_invokes_depends_exe_with_profiling": True,
            "nuitka_cache_source_extracts_archive_with_flatten": True,
            "cache_only_exe_runtime_failure_risk": True,
            "chm_needed_for_nuitka_scan": False,
        },
        "static_risk_observations": [
            (
                "Dependency Walker is a diagnostic and profiling tool; "
                "debugging or process-inspection APIs are contextually expected "
                "but still require review."
            ),
            (
                "Hash agreement identifies the reviewed sample but does not "
                "prove publisher authenticity or safety."
            ),
            (
                "No target PE was executed or dynamically loaded during this "
                "audit."
            ),
        ],
        "suitable_for_next_execution_authorization_review": (
            all(
                bool(binary.get("is_amd64"))
                and binary.get("pe_format") == "PE32+"
                and not bool(binary.get("has_writable_executable_section"))
                for binary in (exe, dll)
            )
        ),
        "target_pe_executed": False,
        "target_dll_loaded": False,
        "network_accessed": False,
    }
    if not _atomic_write_json(report_path, report):
        return BinaryAuditOutcome("binary_audit_write_failed", False)
    return BinaryAuditOutcome(
        "dependency_walker_execution_authorization_required",
        True,
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and statically audit fixed Dependency Walker binaries."
    )
    parser.add_argument(
        "--confirm-extraction",
        action="store_true",
        help="Allow extraction of the two fixed entries into quarantine.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.confirm_extraction:
        print("safe_code=dependency_walker_extraction_disabled")
        return 0
    repository_root = Path(__file__).resolve().parents[1]
    try:
        outcome = audit_dependency_walker_binaries(repository_root)
    except Exception:
        print("safe_code=dependency_walker_binary_audit_failed")
        return 2
    print(
        "dependency_walker_binary_audit="
        f"{str(outcome.completed).lower()} "
        f"safe_code={outcome.safe_code}"
    )
    return 0 if outcome.completed else 2


if __name__ == "__main__":
    sys.exit(main())
