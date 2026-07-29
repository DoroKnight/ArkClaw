from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from transactional_archive import (
    ArchiveSource,
    combined_file_manifest,
    diagnostic_payload,
    manifest_sha256,
    snapshot_directory,
    transactional_archive,
)

ARCHIVE_NAME = "20260729T071602Z-pre-autostart-ui-rebuild"
ARCHIVE_PARENT_RELATIVE_PATH = Path("build/standalone-artifact-archive")
DIAGNOSTIC_RELATIVE_PATH = Path(
    "build/packaging-incidents/"
    "20260729-autostart-rebuild-archive-transaction.json"
)
EXPECTED_FILE_COUNT = 5473
EXPECTED_TOTAL_SIZE_BYTES = 893604991
EXPECTED_MANIFEST_SHA256 = (
    "05ac619a815a0354dcde84410a0faebe15e07dcf5894b21fbed1f8e8c2cb8173"
)
SOURCES = (
    ArchiveSource(
        "build_output",
        Path("build/windows-standalone"),
        Path("build/windows-standalone"),
    ),
    ArchiveSource(
        "temp_output",
        Path("build/standalone-third-build-temp"),
        Path("build/standalone-third-build-temp"),
    ),
    ArchiveSource(
        "deployment",
        Path("packaging/deployment"),
        Path("packaging/deployment"),
    ),
    ArchiveSource("dist", Path("dist"), Path("dist")),
)


def _relative_snapshot(directory: Path, child: Path) -> object:
    return snapshot_directory(directory / child)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> bool:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            return False
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
        os.rename(temporary, path)
        return True
    except OSError:
        return False


def _preflight(root: Path) -> tuple[bool, dict[str, object]]:
    try:
        snapshots = {
            source.source_relative_path.as_posix(): snapshot_directory(
                root / source.source_relative_path
            )
            for source in SOURCES
        }
        combined = combined_file_manifest(snapshots)
        raw = _relative_snapshot(
            root / "packaging/deployment",
            Path("pet_entry.dist"),
        )
        final = _relative_snapshot(
            root / "dist",
            Path("SJTUClaw.dist"),
        )
        build_files = snapshots["build/windows-standalone"].files
    except OSError:
        return False, {"safe_code": "autostart_archive_source_invalid"}
    aggregate = manifest_sha256(combined)
    valid = all(
        (
            len(combined) == EXPECTED_FILE_COUNT,
            sum(size for size, _ in combined.values())
            == EXPECTED_TOTAL_SIZE_BYTES,
            aggregate == EXPECTED_MANIFEST_SHA256,
            raw == final,
            not snapshots["build/standalone-third-build-temp"].files,
            not snapshots["build/standalone-third-build-temp"].directories,
            {
                "artifact_audit.json",
                "build_report.json",
                "compilation-report.xml",
            }.issubset(build_files),
        )
    )
    return valid, {
        "file_count": len(combined),
        "total_size_bytes": sum(size for size, _ in combined.values()),
        "manifest_sha256": aggregate,
        "raw_final_manifest_equal": raw == final,
        "safe_code": (
            "autostart_archive_preflight_ready"
            if valid
            else "autostart_archive_source_invalid"
        ),
    }


def archive_current_outputs(root: Path) -> tuple[bool, dict[str, object]]:
    valid, preflight = _preflight(root)
    if not valid:
        return False, preflight
    outcome = transactional_archive(
        root,
        archive_parent_relative_path=ARCHIVE_PARENT_RELATIVE_PATH,
        archive_name=ARCHIVE_NAME,
        sources=SOURCES,
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "archive_name": outcome.archive_name,
        "completed": outcome.completed,
        "safe_code": outcome.safe_code,
        "file_count": outcome.file_count,
        "total_size_bytes": outcome.total_size_bytes,
        "manifest_sha256": outcome.manifest_sha256,
        "preflight": preflight,
        "diagnostic": (
            diagnostic_payload(outcome.diagnostic)
            if outcome.diagnostic is not None
            else None
        ),
        "raw_exception_recorded": False,
        "absolute_paths_recorded": False,
        "environment_values_recorded": False,
    }
    if not _write_json_atomic(root / DIAGNOSTIC_RELATIVE_PATH, payload):
        return False, {
            "safe_code": "autostart_archive_diagnostic_write_failed"
        }
    return outcome.completed, payload


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.confirm_archive:
        print("safe_code=autostart_archive_disabled")
        return 0
    root = Path(__file__).resolve().parents[1]
    try:
        completed, payload = archive_current_outputs(root)
    except Exception:
        print("safe_code=autostart_archive_failed")
        return 2
    diagnostic = payload.get("diagnostic")
    if isinstance(diagnostic, dict):
        print(
            " ".join(
                (
                    f"operation_stage={diagnostic['operation_stage']}",
                    f"source_class={diagnostic['source_class']}",
                    "exception_category="
                    f"{diagnostic['exception_category']}",
                    "rollback_attempted="
                    f"{str(diagnostic['rollback_attempted']).lower()}",
                    "rollback_completed="
                    f"{str(diagnostic['rollback_completed']).lower()}",
                    "original_sources_restored="
                    f"{str(diagnostic['original_sources_restored']).lower()}",
                    "failed_part_preserved="
                    f"{str(diagnostic['failed_part_preserved']).lower()}",
                )
            )
        )
    if completed:
        print(
            " ".join(
                (
                    "autostart_rebuild_archived=true",
                    f"file_count={payload['file_count']}",
                    f"total_size_bytes={payload['total_size_bytes']}",
                    f"manifest_sha256={payload['manifest_sha256']}",
                    "same_volume_renames=true",
                )
            )
        )
    print(f"safe_code={payload['safe_code']}")
    return 0 if completed else 2


if __name__ == "__main__":
    sys.exit(main())
