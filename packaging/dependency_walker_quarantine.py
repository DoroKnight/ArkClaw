from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import ssl
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol, cast

DEPENDENCY_WALKER_URL = "https://dependencywalker.com/depends22_x64.zip"
QUARANTINE_RELATIVE_PATH = Path(
    "build/tool-quarantine/dependency-walker"
)
ZIP_FILENAME = "depends22_x64.zip"
DOWNLOAD_AUDIT_FILENAME = "download_audit.json"
ARCHIVE_AUDIT_FILENAME = "archive_audit.json"
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_ENTRY_COUNT = 64
MAX_TOTAL_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_SINGLE_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000.0
MAX_PE_PREFIX_BYTES = 64 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
AMD64_MACHINE = 0x8664


class ResponseLike(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def geturl(self) -> str: ...

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class Transport(Protocol):
    def open(self, url: str) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    safe_code: str
    completed: bool
    archive_safe: bool | None = None
    manual_review_required: bool | None = None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        del req, fp, code, msg, headers, newurl
        return None


class _UrlLibResponse:
    def __init__(self, response: Any) -> None:
        self._response = response

    @property
    def status(self) -> int:
        status = self._response.status
        if status is None:
            status = self._response.code
        return int(status)

    @property
    def headers(self) -> Mapping[str, str]:
        return cast(Mapping[str, str], self._response.headers)

    def geturl(self) -> str:
        return str(self._response.geturl())

    def read(self, size: int = -1) -> bytes:
        return bytes(self._response.read(size))

    def close(self) -> None:
        self._response.close()


class _UrlLibTransport:
    def __init__(self) -> None:
        context = ssl.create_default_context()
        https_handler = urllib.request.HTTPSHandler(context=context)
        self._opener = urllib.request.build_opener(
            _NoRedirectHandler(),
            https_handler,
        )

    def open(self, url: str) -> ResponseLike:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "SJTUClaw-Dependency-Audit/1.0"},
            method="GET",
        )
        try:
            return _UrlLibResponse(self._opener.open(request, timeout=60))
        except urllib.error.HTTPError as error:
            return _UrlLibResponse(error)


def validate_dependency_walker_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "dependencywalker.com"
        and parsed.hostname == "dependencywalker.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and parsed.path == "/depends22_x64.zip"
        and not parsed.query
        and not parsed.fragment
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_utc(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        parsed = int(value, 10)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _atomic_write_json(path: Path, payload: object) -> bool:
    if path.exists():
        return False
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    created = False
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as stream:
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
        os.rename(temporary_path, path)
        created = False
        return True
    except OSError:
        return False
    finally:
        if created:
            with contextlib.suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _normalize_entry_name(name: str) -> str:
    segments = [
        segment
        for segment in name.replace("\\", "/").split("/")
        if segment not in ("", ".")
    ]
    return "/".join(segments)


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _entry_unix_type(external_attributes: int) -> int:
    mode = (external_attributes >> 16) & 0xFFFF
    return mode & 0xF000


def _hash_entry_and_read_prefix(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> tuple[str, bytes]:
    digest = hashlib.sha256()
    prefix = bytearray()
    with archive.open(info, mode="r") as stream:
        while True:
            chunk = stream.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            if len(prefix) < MAX_PE_PREFIX_BYTES:
                remaining = MAX_PE_PREFIX_BYTES - len(prefix)
                prefix.extend(chunk[:remaining])
    return digest.hexdigest(), bytes(prefix)


def _inspect_pe_prefix(prefix: bytes) -> dict[str, object]:
    result: dict[str, object] = {
        "has_mz_header": False,
        "has_pe_signature": False,
        "machine": None,
        "machine_hex": None,
        "is_amd64": False,
    }
    if len(prefix) < 64 or prefix[:2] != b"MZ":
        return result
    result["has_mz_header"] = True
    pe_offset = struct.unpack_from("<I", prefix, 0x3C)[0]
    if pe_offset > MAX_PE_PREFIX_BYTES - 6 or pe_offset + 6 > len(prefix):
        return result
    if prefix[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        return result
    result["has_pe_signature"] = True
    machine = struct.unpack_from("<H", prefix, pe_offset + 4)[0]
    result["machine"] = machine
    result["machine_hex"] = f"0x{machine:04X}"
    result["is_amd64"] = machine == AMD64_MACHINE
    return result


def audit_zip_archive(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path, mode="r") as archive:
        infos = archive.infolist()
        normalized_counts: dict[str, int] = {}
        entries: list[dict[str, object]] = []
        total_compressed = 0
        total_uncompressed = 0

        for info in infos:
            normalized = _normalize_entry_name(info.filename)
            folded_name = normalized.casefold()
            normalized_counts[folded_name] = normalized_counts.get(folded_name, 0) + 1
            total_compressed += info.compress_size
            total_uncompressed += info.file_size

            segments = info.filename.replace("\\", "/").split("/")
            is_unc = info.filename.startswith(("\\\\", "//"))
            is_absolute = info.filename.startswith(("\\", "/"))
            has_drive = re.match(r"^[A-Za-z]:", info.filename) is not None
            has_ads_colon = ":" in info.filename
            has_traversal = any(segment == ".." for segment in segments)
            encrypted = bool(info.flag_bits & 0x1)
            unix_type = _entry_unix_type(info.external_attr)
            is_symlink = unix_type == 0xA000
            is_special_file = unix_type not in (0, 0x4000, 0x8000, 0xA000)
            ratio = (
                float("inf")
                if info.file_size > 0 and info.compress_size == 0
                else (
                    info.file_size / info.compress_size
                    if info.compress_size > 0
                    else 0.0
                )
            )
            entry: dict[str, object] = {
                "original_name": info.filename,
                "normalized_name": normalized,
                "is_directory": info.is_dir(),
                "compressed_size": info.compress_size,
                "uncompressed_size": info.file_size,
                "compression_ratio": (
                    "infinite" if ratio == float("inf") else round(ratio, 6)
                ),
                "encrypted": encrypted,
                "absolute_path": is_absolute,
                "unc_path": is_unc,
                "drive_path": has_drive,
                "path_traversal": has_traversal,
                "ads_colon": has_ads_colon,
                "nul_or_control_character": _has_control_character(info.filename),
                "external_attributes": info.external_attr,
                "unix_file_type": f"0x{unix_type:04X}",
                "symlink": is_symlink,
                "special_file": is_special_file,
                "sha256": None,
            }
            entries.append(entry)

        duplicate_names = sorted(
            name for name, count in normalized_counts.items() if count > 1
        )
        entry_count_exceeded = len(infos) > MAX_ENTRY_COUNT
        total_size_exceeded = total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES
        single_size_exceeded = any(
            info.file_size > MAX_SINGLE_UNCOMPRESSED_BYTES for info in infos
        )
        compression_ratio_exceeded = any(
            (
                info.file_size > 0
                and (
                    info.compress_size == 0
                    or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
                )
            )
            for info in infos
        )

        depends_indexes = [
            index
            for index, entry in enumerate(entries)
            if (
                not bool(entry["is_directory"])
                and str(entry["normalized_name"]).split("/")[-1].casefold()
                == "depends.exe"
            )
        ]
        unsafe_declared_size = (
            entry_count_exceeded
            or total_size_exceeded
            or single_size_exceeded
            or compression_ratio_exceeded
        )
        pe_inspection: dict[str, object] | None = None
        if not unsafe_declared_size:
            for index, info in enumerate(infos):
                entry = entries[index]
                if info.is_dir() or bool(entry["encrypted"]):
                    continue
                digest, prefix = _hash_entry_and_read_prefix(archive, info)
                entry["sha256"] = digest
                if index in depends_indexes:
                    pe_inspection = _inspect_pe_prefix(prefix)

        path_or_type_issue = any(
            any(
                bool(entry[key])
                for key in (
                    "absolute_path",
                    "unc_path",
                    "drive_path",
                    "path_traversal",
                    "ads_colon",
                    "nul_or_control_character",
                    "encrypted",
                    "symlink",
                    "special_file",
                )
            )
            for entry in entries
        )
        depends_count_valid = len(depends_indexes) == 1
        pe_valid = bool(
            pe_inspection
            and pe_inspection["has_mz_header"]
            and pe_inspection["has_pe_signature"]
            and pe_inspection["is_amd64"]
        )
        archive_safe = (
            not path_or_type_issue
            and not duplicate_names
            and not unsafe_declared_size
            and depends_count_valid
            and pe_valid
        )
        other_entries = [
            str(entry["original_name"])
            for index, entry in enumerate(entries)
            if not bool(entry["is_directory"]) and index not in depends_indexes
        ]

        return {
            "schema_version": 1,
            "archive_path": (
                "build/tool-quarantine/dependency-walker/depends22_x64.zip"
            ),
            "entry_count": len(infos),
            "total_compressed_size": total_compressed,
            "total_uncompressed_size": total_uncompressed,
            "entries": entries,
            "duplicate_names_case_insensitive": duplicate_names,
            "depends_exe_count": len(depends_indexes),
            "depends_exe_pe": pe_inspection,
            "other_non_directory_entries": other_entries,
            "manual_review_required": bool(other_entries),
            "checks": {
                "entry_count_within_limit": not entry_count_exceeded,
                "total_uncompressed_size_within_limit": not total_size_exceeded,
                "single_file_size_within_limit": not single_size_exceeded,
                "compression_ratio_within_limit": not compression_ratio_exceeded,
                "no_encrypted_entries": not any(
                    bool(entry["encrypted"]) for entry in entries
                ),
                "no_duplicate_names_case_insensitive": not duplicate_names,
                "no_unsafe_paths_or_types": not path_or_type_issue,
                "exactly_one_depends_exe": depends_count_valid,
                "depends_exe_is_amd64_pe": pe_valid,
            },
            "archive_safe": archive_safe,
        }


def _download_to_part(
    response: ResponseLike,
    part_path: Path,
) -> tuple[int, str, str]:
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    actual_bytes = 0
    with part_path.open("xb") as output:
        while True:
            chunk = response.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            actual_bytes += len(chunk)
            if actual_bytes > MAX_DOWNLOAD_BYTES:
                raise ValueError("download_size_limit")
            output.write(chunk)
            sha256.update(chunk)
            sha512.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    return actual_bytes, sha256.hexdigest(), sha512.hexdigest()


def acquire_dependency_walker(
    repository_root: Path,
    *,
    transport: Transport | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> AcquisitionOutcome:
    if not validate_dependency_walker_url(DEPENDENCY_WALKER_URL):
        return AcquisitionOutcome("dependency_walker_url_rejected", False)

    quarantine = repository_root / QUARANTINE_RELATIVE_PATH
    zip_path = quarantine / ZIP_FILENAME
    download_audit_path = quarantine / DOWNLOAD_AUDIT_FILENAME
    archive_audit_path = quarantine / ARCHIVE_AUDIT_FILENAME
    if zip_path.exists():
        return AcquisitionOutcome("quarantine_target_occupied", False)
    if download_audit_path.exists() or archive_audit_path.exists():
        return AcquisitionOutcome("quarantine_audit_target_occupied", False)

    try:
        quarantine.mkdir(parents=True, exist_ok=True)
    except OSError:
        return AcquisitionOutcome("quarantine_directory_unavailable", False)

    part_path = quarantine / f".{ZIP_FILENAME}.{uuid.uuid4().hex}.part"
    response: ResponseLike | None = None
    part_created = False
    final_created = False
    started = now()
    try:
        selected_transport = transport or _UrlLibTransport()
        try:
            response = selected_transport.open(DEPENDENCY_WALKER_URL)
        except Exception:
            return AcquisitionOutcome("dependency_walker_network_error", False)

        status = int(response.status)
        final_url = response.geturl()
        if 300 <= status <= 399 or final_url != DEPENDENCY_WALKER_URL:
            return AcquisitionOutcome("dependency_walker_redirect_rejected", False)
        if status != 200:
            return AcquisitionOutcome("dependency_walker_http_error", False)

        content_length = _safe_content_length(response.headers)
        if content_length is not None and content_length > MAX_DOWNLOAD_BYTES:
            return AcquisitionOutcome("dependency_walker_download_too_large", False)

        try:
            part_created = True
            actual_bytes, zip_sha256, zip_sha512 = _download_to_part(
                response,
                part_path,
            )
        except ValueError:
            return AcquisitionOutcome("dependency_walker_download_too_large", False)
        except Exception:
            return AcquisitionOutcome("dependency_walker_stream_interrupted", False)

        try:
            archive_audit = audit_zip_archive(part_path)
        except Exception:
            return AcquisitionOutcome("dependency_walker_archive_invalid", False)

        try:
            os.rename(part_path, zip_path)
            part_created = False
            final_created = True
        except OSError:
            return AcquisitionOutcome("quarantine_target_occupied", False)

        completed = now()
        download_audit = {
            "schema_version": 1,
            "request_url": DEPENDENCY_WALKER_URL,
            "final_url": final_url,
            "http_status": status,
            "content_type": response.headers.get("Content-Type"),
            "content_length": content_length,
            "actual_bytes": actual_bytes,
            "download_started_utc": _format_utc(started),
            "download_completed_utc": _format_utc(completed),
            "tls_succeeded": True,
            "redirected": False,
            "zip_sha256": zip_sha256,
            "zip_sha512": zip_sha512,
            "local_path": (
                "build/tool-quarantine/dependency-walker/depends22_x64.zip"
            ),
        }
        if not _atomic_write_json(download_audit_path, download_audit):
            return AcquisitionOutcome("download_audit_write_failed", False)
        if not _atomic_write_json(archive_audit_path, archive_audit):
            return AcquisitionOutcome("archive_audit_write_failed", False)

        archive_safe = bool(archive_audit["archive_safe"])
        manual_review = bool(archive_audit["manual_review_required"])
        return AcquisitionOutcome(
            (
                "dependency_walker_review_required"
                if archive_safe
                else "dependency_walker_archive_rejected"
            ),
            True,
            archive_safe=archive_safe,
            manual_review_required=manual_review,
        )
    finally:
        if response is not None:
            with contextlib.suppress(Exception):
                response.close()
        if part_created:
            with contextlib.suppress(OSError):
                part_path.unlink(missing_ok=True)
        if (
            final_created
            and not download_audit_path.exists()
            and not archive_audit_path.exists()
        ):
            # Preserve the complete quarantined ZIP for manual investigation.
            # Never delete or overwrite a completed target in an error path.
            pass


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Acquire and statically audit Dependency Walker in quarantine."
    )
    parser.add_argument(
        "--confirm-download",
        action="store_true",
        help="Allow the single fixed HTTPS download.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.confirm_download:
        print("safe_code=dependency_walker_download_disabled")
        return 0
    repository_root = Path(__file__).resolve().parents[1]
    try:
        outcome = acquire_dependency_walker(repository_root)
    except Exception:
        print("safe_code=dependency_walker_audit_failed")
        return 2
    print(
        "dependency_walker_quarantine="
        f"{str(outcome.completed).lower()} "
        f"archive_safe={str(outcome.archive_safe).lower()} "
        "manual_review_required="
        f"{str(outcome.manual_review_required).lower()} "
        f"safe_code={outcome.safe_code}"
    )
    return 0 if outcome.safe_code == "dependency_walker_review_required" else 2


if __name__ == "__main__":
    sys.exit(main())
