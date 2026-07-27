from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import stat
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as element_tree
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

BUILD_RELATIVE_PATH = Path("build/windows-standalone")
REPORT_RELATIVE_PATH = BUILD_RELATIVE_PATH / "compilation-report.xml"
AUDIT_RELATIVE_PATH = BUILD_RELATIVE_PATH / "artifact_audit.json"
RAW_DIST_RELATIVE_PATH = Path("packaging/deployment/pet_entry.dist")
FINAL_DIST_RELATIVE_PATH = Path("dist/SJTUClaw.dist")
MAIN_EXECUTABLE = "SJTUClaw.exe"
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_DIST_BYTES = 4 * 1024**3
PE_MACHINE_AMD64 = 0x8664
PE32_PLUS_MAGIC = 0x20B
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2
IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA = 0x0020
IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE = 0x0040
IMAGE_DLLCHARACTERISTICS_NX_COMPAT = 0x0100
IMAGE_DLLCHARACTERISTICS_GUARD_CF = 0x4000
REQUIRED_MSVC_VERSION = "14.44.35207"
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_FORBIDDEN_MODULE_PREFIXES = (
    "tests",
    "scripts.manual_openai_verification",
    "scripts.manual_deepseek_verification",
    "scripts.qt_",
    "packaging.dependency_walker",
)
_FORBIDDEN_FILE_PARTS = (
    "manual_openai_verification",
    "manual_deepseek_verification",
    "qt_gui_smoke",
    "qt_pet_smoke",
    "dependency_walker",
)
_FORBIDDEN_EXACT_NAMES = frozenset(
    {
        ".env",
        "compilation-report.xml",
        "depends.chm",
        "depends.dll",
        "depends.exe",
        "depends22_x64.zip",
        "pet_settings.json",
        "provider_profiles.json",
    }
)
_FORBIDDEN_SCRIPT_SUFFIXES = frozenset(
    {".bat", ".cmd", ".ps1", ".py", ".pyw", ".sh"}
)
_FORBIDDEN_CHARACTER_SUFFIXES = frozenset(
    {".atlas", ".png", ".skel"}
)
_FORBIDDEN_BYTE_LITERALS = (
    b"SJTUClaw/Test/OpenAI/APIKey",
    b"SJTUClaw/Test/DeepSeek/APIKey",
    b"D:\\ark-model",
    b"D:/ark-model",
)
_LOCAL_PATH_LITERALS = (
    b"D:\\SJTUClaw",
    b"D:/SJTUClaw",
    b"C:\\Users\\LENOVO",
    b"C:/Users/LENOVO",
    b"\\.venv\\",
    b"/.venv/",
)
_BEARER_CANDIDATE_PATTERN = re.compile(
    rb"(?i)\bBearer[ \t]+([A-Za-z0-9._~+/=-]{12,4096})"
)
_SK_KEY_PATTERN = re.compile(rb"\bsk-[A-Za-z0-9_-]{16,4096}")
_CREDENTIAL_BLOB_VALUE_PATTERN = re.compile(
    rb"(?i)\bCredentialBlob\b[ \t\"':=]{1,16}"
    rb"([A-Za-z0-9+/=_-]{24,4096})"
)
_SYSTEM_DLL_PREFIXES = ("api-ms-win-", "ext-ms-win-")
_QT_PLUGIN_FAMILIES = frozenset(
    {"platforms", "styles", "imageformats", "iconengines", "tls"}
)
_FORBIDDEN_PRODUCTION_MODULE_PREFIXES = (
    "pydantic.mypy",
    "mypy",
    "mypyc",
    "httpx._main",
    "pygments",
)
_FORBIDDEN_PRODUCTION_DISTRIBUTIONS = frozenset(
    {"mypy", "mypy_extensions", "pygments"}
)
_KNOWN_SYSTEM_DLLS = frozenset(
    {
        "advapi32.dll",
        "bcrypt.dll",
        "bcryptprimitives.dll",
        "cabinet.dll",
        "cfgmgr32.dll",
        "combase.dll",
        "comctl32.dll",
        "comdlg32.dll",
        "crypt32.dll",
        "dwmapi.dll",
        "dxgi.dll",
        "gdi32.dll",
        "gdi32full.dll",
        "imm32.dll",
        "iphlpapi.dll",
        "kernel32.dll",
        "kernelbase.dll",
        "msvcp_win.dll",
        "msvcrt.dll",
        "ncrypt.dll",
        "netapi32.dll",
        "ntdll.dll",
        "ole32.dll",
        "oleaut32.dll",
        "powrprof.dll",
        "propsys.dll",
        "rpcrt4.dll",
        "secur32.dll",
        "setupapi.dll",
        "shell32.dll",
        "shlwapi.dll",
        "ucrtbase.dll",
        "user32.dll",
        "userenv.dll",
        "usp10.dll",
        "version.dll",
        "win32u.dll",
        "winhttp.dll",
        "winmm.dll",
        "winnsi.dll",
        "wintrust.dll",
        "wldap32.dll",
        "ws2_32.dll",
        "wtsapi32.dll",
    }
)


@dataclass(frozen=True, slots=True)
class ArtifactAuditOutcome:
    completed: bool
    safe_code: str
    report: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Section:
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int


@dataclass(frozen=True, slots=True)
class _PEInfo:
    machine: int
    subsystem: int
    dll_characteristics: int
    dependencies: tuple[str, ...]
    normal_dependencies: tuple[str, ...] = ()
    delay_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _DependencyResolution:
    status: str
    selected_candidate: str | None
    resolution_tier: str | None
    shadowed_candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _SensitiveFinding:
    kind: str
    length: int
    sha256: str
    offset: int
    attribution: str


@dataclass(frozen=True, slots=True)
class _FileScan:
    forbidden_categories: tuple[str, ...]
    local_path_categories: tuple[str, ...]
    secret_findings: tuple[_SensitiveFinding, ...]
    benign_bearer_findings: tuple[_SensitiveFinding, ...]
    credential_blob_identifier_present: bool


DumpbinRunner = Callable[[Path], Mapping[str, object]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(directory: Path) -> dict[str, dict[str, object]]:
    directory_stat = directory.lstat()
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or directory.is_symlink()
        or int(getattr(directory_stat, "st_file_attributes", 0))
        & FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise OSError("standalone_manifest_root_invalid")
    result: dict[str, dict[str, object]] = {}
    pending = [directory]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                entry_stat = path.lstat()
                is_reparse = bool(
                    int(
                        getattr(
                            entry_stat,
                            "st_file_attributes",
                            0,
                        )
                    )
                    & FILE_ATTRIBUTE_REPARSE_POINT
                )
                if path.is_symlink() or is_reparse:
                    raise OSError("standalone_manifest_link_rejected")
                if stat.S_ISDIR(entry_stat.st_mode):
                    pending.append(path)
                    continue
                if (
                    not stat.S_ISREG(entry_stat.st_mode)
                    or entry_stat.st_nlink != 1
                    or not entry.is_file(follow_symlinks=False)
                ):
                    raise OSError(
                        "standalone_manifest_non_regular_rejected"
                    )
                relative = path.relative_to(directory).as_posix()
                result[relative] = {
                    "size": entry_stat.st_size,
                    "sha256": _sha256_file(path),
                }
    return dict(sorted(result.items()))


def _manifest_entry_size(entry: Mapping[str, object]) -> int:
    value = entry.get("size")
    return value if isinstance(value, int) else -1


def _atomic_write_json(path: Path, payload: object) -> bool:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                (
                    json.dumps(
                        payload,
                        ensure_ascii=True,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _read_c_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset, min(len(data), offset + 4096))
    if end < 0:
        return ""
    return data[offset:end].decode("ascii", errors="replace")


def _rva_to_offset(
    data: bytes,
    sections: Sequence[_Section],
    rva: int,
) -> int | None:
    for section in sections:
        span = max(section.virtual_size, section.raw_size)
        if section.virtual_address <= rva < section.virtual_address + span:
            offset = section.raw_offset + rva - section.virtual_address
            if 0 <= offset < len(data):
                return offset
    return None


def _parse_pe(path: Path) -> _PEInfo:
    size = path.stat().st_size
    if size <= 0 or size > MAX_FILE_BYTES:
        raise ValueError("invalid_pe_size")
    data = path.read_bytes()
    if len(data) < 0x100 or data[:2] != b"MZ":
        raise ValueError("invalid_pe")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if (
        pe_offset + 24 > len(data)
        or data[pe_offset : pe_offset + 4] != b"PE\0\0"
    ):
        raise ValueError("invalid_pe")
    coff = pe_offset + 4
    machine, section_count = struct.unpack_from("<HH", data, coff)
    optional_size = struct.unpack_from("<H", data, coff + 16)[0]
    optional = coff + 20
    if (
        optional + optional_size > len(data)
        or struct.unpack_from("<H", data, optional)[0] != PE32_PLUS_MAGIC
    ):
        raise ValueError("invalid_pe32_plus")
    subsystem = struct.unpack_from("<H", data, optional + 68)[0]
    dll_characteristics = struct.unpack_from("<H", data, optional + 70)[0]
    image_base = struct.unpack_from("<Q", data, optional + 24)[0]
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
        raise ValueError("invalid_sections")
    sections: list[_Section] = []
    for index in range(section_count):
        offset = section_table + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = (
            struct.unpack_from("<IIII", data, offset + 8)
        )
        if raw_offset + raw_size > len(data):
            raise ValueError("invalid_section")
        sections.append(
            _Section(
                virtual_address,
                virtual_size,
                raw_offset,
                raw_size,
            )
        )
    normal_dependencies: set[str] = set()
    delay_dependencies: set[str] = set()
    if len(directories) > 1:
        import_rva, import_size = directories[1]
        if import_rva and import_size:
            descriptor = _rva_to_offset(data, sections, import_rva)
            if descriptor is None:
                raise ValueError("invalid_import_directory")
            for index in range(4096):
                offset = descriptor + index * 20
                if offset + 20 > len(data):
                    raise ValueError("invalid_import_directory")
                values = struct.unpack_from("<IIIII", data, offset)
                if not any(values):
                    break
                name_offset = _rva_to_offset(data, sections, values[3])
                if name_offset is None:
                    raise ValueError("invalid_import_name")
                name = _read_c_string(data, name_offset).casefold()
                if not name:
                    raise ValueError("invalid_import_name")
                normal_dependencies.add(name)
    if len(directories) > 13:
        delay_rva, delay_size = directories[13]
        if delay_rva and delay_size:
            descriptor = _rva_to_offset(data, sections, delay_rva)
            if descriptor is None:
                raise ValueError("invalid_delay_import_directory")
            for index in range(4096):
                offset = descriptor + index * 32
                if offset + 32 > len(data):
                    raise ValueError("invalid_delay_import_directory")
                values = struct.unpack_from("<IIIIIIII", data, offset)
                if not any(values):
                    break
                attributes, name_value = values[:2]
                name_rva = (
                    name_value
                    if attributes & 1
                    else name_value - image_base
                )
                name_offset = _rva_to_offset(
                    data,
                    sections,
                    int(name_rva),
                )
                if name_offset is None:
                    raise ValueError("invalid_delay_import_name")
                name = _read_c_string(data, name_offset).casefold()
                if not name:
                    raise ValueError("invalid_delay_import_name")
                delay_dependencies.add(name)
    dependencies = normal_dependencies | delay_dependencies
    return _PEInfo(
        machine,
        subsystem,
        dll_characteristics,
        tuple(sorted(dependencies)),
        tuple(sorted(normal_dependencies)),
        tuple(sorted(delay_dependencies)),
    )


def _shannon_entropy(value: bytes) -> float:
    if not value:
        return 0.0
    counts = {byte: value.count(byte) for byte in set(value)}
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    )


def _looks_like_bearer_token(value: bytes) -> bool:
    jwt_parts = value.split(b".")
    if (
        len(jwt_parts) == 3
        and all(len(part) >= 4 for part in jwt_parts)
        and all(
            re.fullmatch(rb"[A-Za-z0-9_-]+", part) is not None
            for part in jwt_parts
        )
    ):
        return True
    if len(value) < 24 or value.isalpha():
        return False
    categories = sum(
        (
            any(65 <= byte <= 90 for byte in value),
            any(97 <= byte <= 122 for byte in value),
            any(48 <= byte <= 57 for byte in value),
            any(
                byte in b"._~+/=-"
                for byte in value
            ),
        )
    )
    return categories >= 3 and _shannon_entropy(value) >= 3.5


def _finding(
    *,
    kind: str,
    value: bytes,
    offset: int,
    attribution: str,
) -> _SensitiveFinding:
    return _SensitiveFinding(
        kind=kind,
        length=len(value),
        sha256=hashlib.sha256(value).hexdigest(),
        offset=offset,
        attribution=attribution,
    )


def _finding_report(
    finding: _SensitiveFinding,
    *,
    filename: str,
) -> dict[str, object]:
    return {
        "type": finding.kind,
        "length": finding.length,
        "sha256": finding.sha256,
        "file": filename,
        "offset": finding.offset,
        "attribution": finding.attribution,
        "attribution_complete": True,
    }


def _scan_file(path: Path) -> _FileScan:
    forbidden: set[str] = set()
    local_paths: set[str] = set()
    overlap = 512
    tail = b""
    stream_position = 0
    secret_findings: dict[
        tuple[str, int, str],
        _SensitiveFinding,
    ] = {}
    benign_bearer_findings: dict[
        tuple[str, int, str],
        _SensitiveFinding,
    ] = {}
    credential_blob_identifier_present = False
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            base_offset = stream_position - len(tail)
            folded = data.lower()
            for literal in _FORBIDDEN_BYTE_LITERALS:
                if literal.lower() in folded:
                    forbidden.add("forbidden_literal")
            for literal in _LOCAL_PATH_LITERALS:
                if literal.lower() in folded:
                    local_paths.add("local_build_path")
            if b"credentialblob" in folded:
                credential_blob_identifier_present = True
            for match in _CREDENTIAL_BLOB_VALUE_PATTERN.finditer(data):
                value = match.group(1)
                if not _looks_like_bearer_token(value):
                    continue
                offset = base_offset + match.start(1)
                item = _finding(
                    kind="CredentialBlob",
                    value=value,
                    offset=offset,
                    attribution="sensitive_value",
                )
                secret_findings[(item.kind, item.offset, item.sha256)] = item
            for match in _BEARER_CANDIDATE_PATTERN.finditer(data):
                value = match.group(1)
                reported_value = match.group(0)
                offset = base_offset + match.start(0)
                if _looks_like_bearer_token(value):
                    item = _finding(
                        kind="Bearer",
                        value=reported_value,
                        offset=offset,
                        attribution="sensitive_value",
                    )
                    secret_findings[
                        (item.kind, item.offset, item.sha256)
                    ] = item
                else:
                    item = _finding(
                        kind="Bearer",
                        value=reported_value,
                        offset=offset,
                        attribution="prose",
                    )
                    benign_bearer_findings[
                        (item.kind, item.offset, item.sha256)
                    ] = item
            for match in _SK_KEY_PATTERN.finditer(data):
                value = match.group(0)
                offset = base_offset + match.start(0)
                item = _finding(
                    kind="sk_key",
                    value=value,
                    offset=offset,
                    attribution="known_credential_format",
                )
                secret_findings[(item.kind, item.offset, item.sha256)] = item
            utf16 = data.decode("utf-16le", errors="ignore").encode(
                "utf-8",
                errors="ignore",
            )
            utf16_folded = utf16.lower()
            if any(
                literal.lower() in utf16_folded
                for literal in _FORBIDDEN_BYTE_LITERALS
            ):
                forbidden.add("forbidden_literal_utf16")
            if any(
                literal.lower() in utf16_folded
                for literal in _LOCAL_PATH_LITERALS
            ):
                local_paths.add("local_build_path_utf16")
            tail = data[-overlap:]
            stream_position += len(chunk)
    return _FileScan(
        tuple(sorted(forbidden)),
        tuple(sorted(local_paths)),
        tuple(
            sorted(
                secret_findings.values(),
                key=lambda item: (item.offset, item.kind),
            )
        ),
        tuple(
            sorted(
                benign_bearer_findings.values(),
                key=lambda item: (item.offset, item.kind),
            )
        ),
        credential_blob_identifier_present,
    )


def _audit_compilation_report(path: Path) -> tuple[bool, dict[str, object]]:
    result: dict[str, object] = {}
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_REPORT_BYTES:
            raise ValueError("report_size_invalid")
        raw = path.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("xml_declaration_rejected")
        root = element_tree.fromstring(raw)
        report_scan = _scan_file(path)
    except (OSError, ValueError, element_tree.ParseError):
        return False, {"parseable": False}
    modules = sorted(
        {
            node.attrib.get("name", "")
            for node in root.findall("module")
            if node.attrib.get("name")
        }
    )
    data_files = sorted(
        {
            node.attrib.get("name", "")
            for node in root.findall("data_file")
            if node.attrib.get("name")
        }
    )
    included_binaries = sorted(
        {
            node.attrib.get("dest_path", "")
            for node in root
            if node.tag.startswith("included_")
            and node.attrib.get("dest_path")
        }
    )
    plugins = sorted(
        {
            node.attrib.get("name", "")
            for node in root.findall("./plugins/plugin")
            if node.attrib.get("name")
        }
    )
    distributions = sorted(
        (
            {
                "name": node.attrib.get("name", ""),
                "version": node.attrib.get("version", ""),
                "installer": node.attrib.get("installer", ""),
            }
            for node in root.findall("./distributions/distribution")
        ),
        key=lambda item: str(item["name"]).casefold(),
    )
    options = tuple(
        node.attrib.get("value", "")
        for node in root.findall("./command_line/option")
    )
    python_node = root.find("./python")
    forbidden_modules = sorted(
        module
        for module in modules
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in _FORBIDDEN_MODULE_PREFIXES
        )
    )
    forbidden_production_modules = sorted(
        module
        for module in modules
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in _FORBIDDEN_PRODUCTION_MODULE_PREFIXES
        )
    )
    forbidden_production_distributions = sorted(
        (
            str(distribution["name"])
            for distribution in distributions
            if str(distribution["name"]).casefold()
            in _FORBIDDEN_PRODUCTION_DISTRIBUTIONS
        ),
        key=str.casefold,
    )
    report_text = raw.decode("utf-8", errors="replace")
    forbidden_resources = sorted(
        value
        for value in (*data_files, *included_binaries)
        if Path(value).suffix.casefold() in _FORBIDDEN_CHARACTER_SUFFIXES
        or any(
            part in value.casefold() for part in _FORBIDDEN_FILE_PARTS
        )
    )
    input_entry_valid = any(
        value.replace("\\", "/").endswith("/packaging/pet_entry.py")
        or value.replace("\\", "/") == "packaging/pet_entry.py"
        for value in options
    )
    architecture = (
        python_node.attrib.get("arch_name", "")
        if python_node is not None
        else ""
    )
    result = {
        "parseable": True,
        "root_tag": root.tag,
        "nuitka_version": root.attrib.get("nuitka_version"),
        "completion": root.attrib.get("completion"),
        "mode": root.attrib.get("mode"),
        "onefile_node_present": root.find("./onefile") is not None,
        "input_entry_valid": input_entry_valid,
        "architecture": architecture,
        "module_count": len(modules),
        "modules": modules,
        "data_file_count": len(data_files),
        "data_files": data_files,
        "included_binary_count": len(included_binaries),
        "included_binaries": included_binaries,
        "plugins": plugins,
        "distributions": distributions,
        "forbidden_modules": forbidden_modules,
        "forbidden_resources": forbidden_resources,
        "forbidden_production_modules": forbidden_production_modules,
        "forbidden_production_distributions": (
            forbidden_production_distributions
        ),
        "production_dependency_surface_valid": not (
            forbidden_production_modules
            or forbidden_production_distributions
        ),
        "manual_targets_present": (
            "SJTUClaw/Test/OpenAI/APIKey" in report_text
            or "SJTUClaw/Test/DeepSeek/APIKey" in report_text
        ),
        "external_character_path_present": (
            "D:\\ark-model" in report_text
            or "D:/ark-model" in report_text
        ),
        "credential_blob_identifier_present": (
            report_scan.credential_blob_identifier_present
        ),
        "real_secret_findings": [
            _finding_report(finding, filename=REPORT_RELATIVE_PATH.as_posix())
            for finding in report_scan.secret_findings
        ],
    }
    valid = all(
        (
            result["root_tag"] == "nuitka-compilation-report",
            result["nuitka_version"] == "4.0",
            result["completion"] == "yes",
            result["mode"] == "standalone",
            not result["onefile_node_present"],
            result["input_entry_valid"],
            str(result["architecture"]).casefold()
            in {"x86_64", "amd64"},
            not forbidden_modules,
            not forbidden_resources,
            not result["manual_targets_present"],
            not result["external_character_path_present"],
            not result["real_secret_findings"],
        )
    )
    return valid, result


def _default_dumpbin_runner(path: Path) -> Mapping[str, object]:
    dumpbin = _find_dumpbin()
    results: dict[str, object] = {
        "tool": "MSVC 14.44 dumpbin.exe",
        "tool_directory_valid": (
            dumpbin.parent.name.casefold() == "x64"
            and dumpbin.parent.parent.name.casefold() == "hostx64"
            and dumpbin.parent.parent.parent.parent.name
            == REQUIRED_MSVC_VERSION
        ),
    }
    for option in ("/HEADERS", "/DEPENDENTS"):
        completed = subprocess.run(
            [os.fspath(dumpbin), option, os.fspath(path)],
            check=False,
            capture_output=True,
            timeout=60,
        )
        output = completed.stdout + completed.stderr
        results[option] = {
            "exit_code": completed.returncode,
            "sha256": hashlib.sha256(output).hexdigest(),
            "bytes": len(output),
        }
    return results


def _find_dumpbin() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft Visual Studio/Installer/vswhere.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft Visual Studio/Installer/vswhere.exe",
    )
    vswhere = next((path for path in candidates if path.is_file()), None)
    if vswhere is None:
        raise OSError("dumpbin_unavailable")
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
        raise OSError("dumpbin_unavailable")
    for line in completed.stdout.splitlines():
        path = (
            Path(line.strip())
            / "VC/Tools/MSVC"
            / REQUIRED_MSVC_VERSION
            / "bin/Hostx64/x64/dumpbin.exe"
        )
        if path.is_file():
            return path
    raise OSError("dumpbin_unavailable")


def _dependency_resolution(
    importer: str,
    name: str,
    *,
    bundled_paths_by_name: Mapping[str, tuple[str, ...]],
    system_names: frozenset[str],
) -> _DependencyResolution:
    lowered = name.casefold()
    bundled = bundled_paths_by_name.get(lowered, ())
    importer_parent = Path(importer).parent
    importer_parent_name = (
        ""
        if importer_parent == Path(".")
        else importer_parent.as_posix().casefold()
    )
    explicit_directories: tuple[str, ...] = ()
    importer_parts = tuple(part.casefold() for part in Path(importer).parts)
    if importer_parts and importer_parts[0] == "pyside6":
        explicit_directories = ("pyside6",)
    elif importer_parts and importer_parts[0] == "shiboken6":
        explicit_directories = ("shiboken6",)
    tier_definitions = (
        ("current_pe_directory", (importer_parent_name,)),
        ("distribution_root", ("",)),
        ("explicit_runtime_directory", explicit_directories),
    )
    examined: set[str] = set()
    for tier, directories in tier_definitions:
        normalized_directories = {
            directory.casefold() for directory in directories
        }
        candidates = tuple(
            candidate
            for candidate in bundled
            if (
                ""
                if Path(candidate).parent == Path(".")
                else Path(candidate).parent.as_posix().casefold()
            )
            in normalized_directories
            and candidate.casefold() not in examined
        )
        examined.update(candidate.casefold() for candidate in candidates)
        if len(candidates) > 1:
            return _DependencyResolution(
                "ambiguous",
                None,
                tier,
                tuple(
                    candidate
                    for candidate in bundled
                    if candidate not in candidates
                ),
            )
        if len(candidates) == 1:
            selected = candidates[0]
            return _DependencyResolution(
                "resolved",
                selected,
                tier,
                tuple(
                    candidate
                    for candidate in bundled
                    if candidate != selected
                ),
            )
    if (
        lowered in system_names
        or lowered in _KNOWN_SYSTEM_DLLS
        or lowered.startswith(_SYSTEM_DLL_PREFIXES)
    ):
        return _DependencyResolution(
            "resolved",
            name,
            "windows_system",
            bundled,
        )
    if bundled:
        return _DependencyResolution(
            "bundled_wrong_directory",
            None,
            None,
            bundled,
        )
    return _DependencyResolution("unresolved", None, None)


def _qt_plugin_path_is_allowed(name: str) -> bool:
    components = tuple(part.casefold() for part in Path(name).parts)
    if len(components) < 2 or components[:2] != (
        "pyside6",
        "qt-plugins",
    ):
        return True
    if len(components) != 4:
        return False
    family = components[2]
    filename = components[3]
    return family in _QT_PLUGIN_FAMILIES and filename.endswith(".dll")


def _system_dll_names() -> frozenset[str]:
    system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    system32 = system_root / "System32"
    try:
        return frozenset(
            path.name.casefold()
            for path in system32.iterdir()
            if path.is_file() and path.suffix.casefold() == ".dll"
        )
    except OSError:
        return frozenset()


def audit_standalone_artifacts(
    repository_root: Path,
    *,
    dumpbin_runner: DumpbinRunner = _default_dumpbin_runner,
    system_dll_names: frozenset[str] | None = None,
) -> ArtifactAuditOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return ArtifactAuditOutcome(
            False,
            "standalone_artifact_audit_failed",
            {},
        )
    raw_dist = root / RAW_DIST_RELATIVE_PATH
    final_dist = root / FINAL_DIST_RELATIVE_PATH
    compilation_report = root / REPORT_RELATIVE_PATH
    if not raw_dist.is_dir() or not final_dist.is_dir():
        return ArtifactAuditOutcome(
            False,
            "standalone_artifact_audit_failed",
            {},
        )
    try:
        raw_manifest = _manifest(raw_dist)
        final_manifest = _manifest(final_dist)
    except OSError:
        return ArtifactAuditOutcome(
            False,
            "standalone_artifact_audit_failed",
            {},
        )
    total_size = sum(
        _manifest_entry_size(entry) for entry in final_manifest.values()
    )
    manifest_equal = bool(final_manifest) and raw_manifest == final_manifest
    filenames = tuple(final_manifest)
    executable_names = tuple(
        name for name in filenames if Path(name).suffix.casefold() == ".exe"
    )
    forbidden_names = sorted(
        name
        for name in filenames
        if Path(name).name.casefold() in _FORBIDDEN_EXACT_NAMES
        or Path(name).suffix.casefold() in _FORBIDDEN_SCRIPT_SUFFIXES
        or Path(name).suffix.casefold() in _FORBIDDEN_CHARACTER_SUFFIXES
        or any(
            part in name.casefold() for part in _FORBIDDEN_FILE_PARTS
        )
        or any(
            component.casefold() in {"tests", "scripts"}
            for component in Path(name).parts
        )
    )
    abnormal_files = sorted(
        name
        for name, entry in final_manifest.items()
        if _manifest_entry_size(entry) <= 0
        or _manifest_entry_size(entry) > MAX_FILE_BYTES
    )
    pe_paths: list[tuple[str, Path]] = []
    unknown_pe_files: list[str] = []
    forbidden_content: dict[str, list[str]] = {}
    local_path_hits: dict[str, list[str]] = {}
    secret_findings: list[dict[str, object]] = []
    benign_bearer_findings: list[dict[str, object]] = []
    credential_blob_identifier_files: list[str] = []
    for name in filenames:
        path = final_dist / Path(name)
        try:
            with path.open("rb") as stream:
                magic = stream.read(2)
            if magic == b"MZ":
                pe_paths.append((name, path))
                if Path(name).suffix.casefold() not in {
                    ".dll",
                    ".exe",
                    ".pyd",
                }:
                    unknown_pe_files.append(name)
            scan = _scan_file(path)
            if scan.forbidden_categories:
                forbidden_content[name] = list(
                    scan.forbidden_categories
                )
            if scan.local_path_categories:
                local_path_hits[name] = list(
                    scan.local_path_categories
                )
            secret_findings.extend(
                _finding_report(finding, filename=name)
                for finding in scan.secret_findings
            )
            benign_bearer_findings.extend(
                _finding_report(finding, filename=name)
                for finding in scan.benign_bearer_findings
            )
            if scan.credential_blob_identifier_present:
                credential_blob_identifier_files.append(name)
        except OSError:
            abnormal_files.append(name)
    pe_reports: dict[str, dict[str, object]] = {}
    bundled_path_lists: dict[str, list[str]] = {}
    for name, _path in pe_paths:
        bundled_path_lists.setdefault(
            Path(name).name.casefold(),
            [],
        ).append(name)
    bundled_paths_by_name = {
        basename: tuple(sorted(paths))
        for basename, paths in sorted(bundled_path_lists.items())
    }
    duplicate_pe_basenames = {
        basename: list(paths)
        for basename, paths in bundled_paths_by_name.items()
        if len(paths) > 1
    }
    system_names = (
        _system_dll_names()
        if system_dll_names is None
        else system_dll_names
    )
    unresolved: dict[str, list[str]] = {}
    ambiguous: dict[str, list[str]] = {}
    pe_parse_failed: list[str] = []
    for name, path in pe_paths:
        try:
            info = _parse_pe(path)
        except (OSError, ValueError, struct.error):
            pe_parse_failed.append(name)
            continue
        resolutions = {
            dependency: _dependency_resolution(
                name,
                dependency,
                bundled_paths_by_name=bundled_paths_by_name,
                system_names=system_names,
            )
            for dependency in info.dependencies
        }
        missing = sorted(
            dependency
            for dependency, resolution in resolutions.items()
            if resolution.status
            in {"bundled_wrong_directory", "unresolved"}
        )
        ambiguous_dependencies = sorted(
            dependency
            for dependency, resolution in resolutions.items()
            if resolution.status == "ambiguous"
        )
        if missing:
            unresolved[name] = missing
        if ambiguous_dependencies:
            ambiguous[name] = ambiguous_dependencies
        pe_reports[name] = {
            "machine": f"0x{info.machine:04X}",
            "is_amd64": info.machine == PE_MACHINE_AMD64,
            "subsystem": info.subsystem,
            "dependencies": list(info.dependencies),
            "normal_dependencies": list(info.normal_dependencies),
            "delay_dependencies": list(info.delay_dependencies),
            "dependency_resolutions": {
                dependency: {
                    "status": resolution.status,
                    "selected_candidate": (
                        resolution.selected_candidate
                    ),
                    "resolution_tier": resolution.resolution_tier,
                    "shadowed_lower_priority_candidates": list(
                        resolution.shadowed_candidates
                    ),
                }
                for dependency, resolution in sorted(
                    resolutions.items()
                )
            },
            "security_features": {
                "aslr_dynamic_base": bool(
                    info.dll_characteristics
                    & IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE
                ),
                "dep_nx_compat": bool(
                    info.dll_characteristics
                    & IMAGE_DLLCHARACTERISTICS_NX_COMPAT
                ),
                "control_flow_guard": bool(
                    info.dll_characteristics
                    & IMAGE_DLLCHARACTERISTICS_GUARD_CF
                ),
                "high_entropy_va": bool(
                    info.dll_characteristics
                    & IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA
                ),
            },
        }
    main_report = pe_reports.get(MAIN_EXECUTABLE, {})
    main_security = main_report.get("security_features", {})
    if not isinstance(main_security, Mapping):
        main_security = {}
    required_files = {
        "qt6core": any(
            Path(name).name.casefold() == "qt6core.dll"
            for name in filenames
        ),
        "qt6gui": any(
            Path(name).name.casefold() == "qt6gui.dll"
            for name in filenames
        ),
        "qt6widgets": any(
            Path(name).name.casefold() == "qt6widgets.dll"
            for name in filenames
        ),
        "qt6network": any(
            Path(name).name.casefold() == "qt6network.dll"
            for name in filenames
        ),
        "qwindows": any(
            name.casefold().endswith("platforms/qwindows.dll")
            for name in filenames
        ),
        "python_runtime": any(
            re.fullmatch(r"python3\d\d(?:t)?\.dll", Path(name).name.casefold())
            for name in filenames
        ),
    }
    qt_plugin_paths = tuple(
        name
        for name in filenames
        if tuple(
            part.casefold() for part in Path(name).parts[:2]
        )
        == ("pyside6", "qt-plugins")
    )
    plugin_results = {
        family: sorted(
            name
            for name in qt_plugin_paths
            if len(Path(name).parts) >= 3
            and Path(name).parts[2].casefold() == family
        )
        for family in sorted(
            _QT_PLUGIN_FAMILIES | {"platformthemes"}
        )
    }
    required_qt_plugins_present = bool(
        any(
            name.casefold()
            == "pyside6/qt-plugins/platforms/qwindows.dll"
            for name in plugin_results["platforms"]
        )
        and any(
            name.casefold()
            == "pyside6/qt-plugins/styles/qmodernwindowsstyle.dll"
            for name in plugin_results["styles"]
        )
        and not plugin_results["platformthemes"]
    )
    runtime_dependencies_present = False
    for pe_report in pe_reports.values():
        dependencies = pe_report.get("dependencies")
        if not isinstance(dependencies, list):
            continue
        if any(
            isinstance(dependency, str)
            and (
                dependency.startswith("vcruntime")
                or dependency == "ucrtbase.dll"
                or dependency.startswith("api-ms-win-crt-")
            )
            for dependency in dependencies
        ):
            runtime_dependencies_present = True
            break
    report_valid, compilation = _audit_compilation_report(
        compilation_report
    )
    try:
        dumpbin = dict(dumpbin_runner(final_dist / MAIN_EXECUTABLE))
        dumpbin_checks: list[bool] = []
        for option in ("/HEADERS", "/DEPENDENTS"):
            option_result = dumpbin.get(option)
            dumpbin_checks.append(
                isinstance(option_result, Mapping)
                and option_result.get("exit_code") == 0
            )
        dumpbin_valid = bool(
            dumpbin.get("tool_directory_valid")
            and all(dumpbin_checks)
        )
    except Exception:
        dumpbin = {"available": False}
        dumpbin_valid = False
    pe_all_amd64 = bool(pe_reports) and all(
        report["is_amd64"] for report in pe_reports.values()
    )
    main_valid = all(
        (
            main_report.get("is_amd64") is True,
            main_report.get("subsystem") == IMAGE_SUBSYSTEM_WINDOWS_GUI,
            main_security.get("aslr_dynamic_base") is True,
            main_security.get("dep_nx_compat") is True,
        )
    )
    compilation_secret_findings = compilation.get(
        "real_secret_findings",
        [],
    )
    production_dependency_surface_valid = (
        compilation.get("production_dependency_surface_valid") is True
    )
    no_real_secret_material = not (
        forbidden_content
        or secret_findings
        or compilation_secret_findings
    )
    checks = {
        "raw_final_manifest_equal": manifest_equal,
        "file_count_nonzero": bool(final_manifest),
        "total_size_within_limit": 0 < total_size <= MAX_DIST_BYTES,
        "only_one_main_executable": executable_names
        == (MAIN_EXECUTABLE,),
        "no_forbidden_names": not forbidden_names,
        "no_abnormal_files": not abnormal_files,
        "no_unknown_pe_files": not unknown_pe_files,
        "no_real_secret_material": no_real_secret_material,
        "no_local_path_leaks": not local_path_hits,
        "all_pe_parseable": not pe_parse_failed,
        "all_pe_amd64": pe_all_amd64,
        "dll_dependencies_resolved_deterministically": (
            not unresolved and not ambiguous
        ),
        "qt_plugin_paths_valid": all(
            _qt_plugin_path_is_allowed(name)
            for name in qt_plugin_paths
        ),
        "required_qt_plugins_present": required_qt_plugins_present,
        "required_qt_python_files_present": all(required_files.values()),
        "msvc_ucrt_dependency_observed": runtime_dependencies_present,
        "main_executable_security_valid": main_valid,
        "compilation_report_valid": report_valid,
        "dumpbin_validation_passed": dumpbin_valid,
        "production_dependency_surface_valid": (
            production_dependency_surface_valid
        ),
    }
    structural_checks = {
        name: value
        for name, value in checks.items()
        if name != "production_dependency_surface_valid"
    }
    structural_valid = all(structural_checks.values())
    completed = structural_valid and production_dependency_surface_valid
    safe_code = (
        "standalone_artifact_audit_failed"
        if not structural_valid
        else (
            "standalone_dependency_pruning_required"
            if not production_dependency_surface_valid
            else "packaged_runtime_authorization_required"
        )
    )
    report: dict[str, object] = {
        "schema_version": 2,
        "standalone_artifact_audit": completed,
        "safe_code": safe_code,
        "checks": checks,
        "file_count": len(final_manifest),
        "total_size_bytes": total_size,
        "manifest": final_manifest,
        "executable_names": list(executable_names),
        "forbidden_names": forbidden_names,
        "abnormal_files": sorted(set(abnormal_files)),
        "unknown_pe_files": unknown_pe_files,
        "forbidden_content_categories": forbidden_content,
        "real_secret_findings": secret_findings,
        "benign_bearer_findings": benign_bearer_findings,
        "bearer_prose_false_positive_removed": bool(
            benign_bearer_findings
        ),
        "credential_blob_identifier_present": bool(
            credential_blob_identifier_files
            or compilation.get(
                "credential_blob_identifier_present",
                False,
            )
        ),
        "credential_blob_identifier_files": sorted(
            credential_blob_identifier_files
        ),
        "local_path_hit_categories": local_path_hits,
        "pe_file_count": len(pe_paths),
        "pe_parse_failed": pe_parse_failed,
        "pe_files": pe_reports,
        "unresolved_dependencies": unresolved,
        "ambiguous_dependencies": ambiguous,
        "duplicate_pe_basenames": duplicate_pe_basenames,
        "duplicate_basenames_are_informational": True,
        "required_files": required_files,
        "plugin_results": plugin_results,
        "main_executable": main_report,
        "control_flow_guard_enabled": (
            main_security.get("control_flow_guard") is True
        ),
        "dumpbin": dumpbin,
        "compilation_report": compilation,
        "forbidden_production_modules": compilation.get(
            "forbidden_production_modules",
            [],
        ),
        "forbidden_production_distributions": compilation.get(
            "forbidden_production_distributions",
            [],
        ),
        "preliminary_third_party_components": compilation.get(
            "distributions",
            [],
        ),
        "license_review_complete_for_public_distribution": False,
        "authenticode_required_at_this_stage": False,
        "hard_network_isolation": False,
        "network_accessed_by_auditor": False,
        "credential_manager_accessed": False,
        "packaged_executable_executed": False,
    }
    if not _atomic_write_json(root / AUDIT_RELATIVE_PATH, report):
        return ArtifactAuditOutcome(
            False,
            "standalone_artifact_audit_failed",
            report,
        )
    return ArtifactAuditOutcome(
        completed,
        str(report["safe_code"]),
        report,
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Statically audit the standalone artifact."
    )
    parser.add_argument("--confirm-audit", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.confirm_audit:
        print("safe_code=standalone_artifact_audit_disabled")
        return 0
    root = Path(__file__).resolve().parents[1]
    try:
        outcome = audit_standalone_artifacts(root)
    except Exception:
        print("safe_code=standalone_artifact_audit_failed")
        return 2
    report = outcome.report
    print(
        " ".join(
            (
                "standalone_artifact_audit="
                f"{str(outcome.completed).lower()}",
                f"file_count={report.get('file_count', 0)}",
                f"total_size_bytes={report.get('total_size_bytes', 0)}",
                f"pe_file_count={report.get('pe_file_count', 0)}",
                "packaged_executable_executed=false",
            )
        )
    )
    print(f"safe_code={outcome.safe_code}")
    return 0 if outcome.completed else 2


if __name__ == "__main__":
    sys.exit(main())
