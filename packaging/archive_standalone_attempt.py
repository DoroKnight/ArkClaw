from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

SOURCE_BUILD_RELATIVE_PATH = Path("build/windows-standalone")
SOURCE_DEPLOYMENT_RELATIVE_PATH = Path("packaging/deployment")
DIST_RELATIVE_PATH = Path("dist")
ARCHIVE_PARENT_RELATIVE_PATH = Path("build/failed-standalone-attempts")
ARCHIVE_NAME = "20260727T060057Z-platformthemes"
ARCHIVED_BUILD_NAME = "windows-standalone"
ARCHIVED_DEPLOYMENT_NAME = "deployment"
MANIFEST_NAME = "archive_manifest.json"
UNPRUNED_ARCHIVE_PARENT_RELATIVE_PATH = Path(
    "build/standalone-artifact-archive"
)
UNPRUNED_ARCHIVE_NAME = "20260727T063632Z-unpruned"
UNPRUNED_MANIFEST_NAME = "unpruned_archive_manifest.json"
INCIDENT_RELATIVE_PATH = Path(
    "build/packaging-incidents/20260727-dry-run-cleanup"
)
INCIDENT_REPORT_NAME = "incident.json"
INCIDENT_FINAL_MANIFEST_NAME = "final_dist_manifest.json"
INCIDENT_BUILD_MANIFEST_NAME = "build_evidence_manifest.json"
DEGRADED_ARCHIVE_PARENT_RELATIVE_PATH = Path(
    "build/standalone-artifact-archive"
)
DEGRADED_ARCHIVE_NAME = "20260727T063632Z-unpruned-degraded"
DEGRADED_ARCHIVE_MANIFEST_NAME = "degraded_archive_manifest.json"
EXPECTED_FINAL_EXE_SHA256 = (
    "10fe39ab457ecf017dc752ce92c90699735f832dbdf44e54d28f6236a5066dae"
)
EXPECTED_FINAL_FILE_COUNT = 136
EXPECTED_FINAL_TOTAL_SIZE = 187599080
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

EXPECTED_BUILD_FILES: Mapping[str, tuple[int, str]] = {
    "build_attempt_started.marker": (
        38,
        "74a2990dfe2822ac181a077c22151a6377f6460586a9695952ef6cea704d5d04",
    ),
    "build_report.json": (
        2317,
        "fac48ab924ee508c1ca9644f655afcd738bb49c361924446c2d05278e6e9f9b1",
    ),
    "compilation-report.xml": (
        3730,
        "4757e97c76cd566f51719026301f6651325419a040a413618f70ecd3d9c5e288",
    ),
    "pyside6-deploy.stderr.log": (
        722,
        "b7eaac64edae59dbba79ecbc8dac24aa6d51e000322a0e9c7480d730c130c7b9",
    ),
    "pyside6-deploy.stdout.log": (
        4068,
        "a642d1a37f0e433e4b45d5fe14cdcf54f1f042bdc6902d26bc4126f52d2970c7",
    ),
    "pysidedeploy.spec": (
        906,
        "4550735d438d60f91d1bccf2d4a64f51c2a591bf7f24f612f1477ccd8a7d9b61",
    ),
}


@dataclass(frozen=True, slots=True)
class ArchiveOutcome:
    completed: bool
    safe_code: str
    file_count: int = 0
    total_size: int = 0
    manifest_sha256: str | None = None


Renamer = Callable[[Path, Path], None]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        result = path.lstat()
    except OSError:
        return True
    return path.is_symlink() or bool(
        int(getattr(result, "st_file_attributes", 0))
        & FILE_ATTRIBUTE_REPARSE_POINT
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((path, root)) == os.fspath(root)
    except ValueError:
        return False


def _validate_existing_chain(repository_root: Path, path: Path) -> bool:
    try:
        root = repository_root.resolve(strict=True)
        relative = path.relative_to(repository_root)
    except (OSError, ValueError):
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if not current.exists():
            continue
        if _is_reparse_point(current):
            return False
        try:
            resolved = current.resolve(strict=True)
        except OSError:
            return False
        if not _is_within(resolved, root):
            return False
    return True


def _directory_manifest(directory: Path) -> dict[str, tuple[int, str]]:
    if (
        not directory.is_dir()
        or _is_reparse_point(directory)
        or not stat.S_ISDIR(directory.lstat().st_mode)
    ):
        raise OSError("archive_directory_invalid")
    manifest: dict[str, tuple[int, str]] = {}
    pending = [directory]
    while pending:
        current = pending.pop()
        for entry in os.scandir(current):
            path = Path(entry.path)
            result = path.lstat()
            if _is_reparse_point(path):
                raise OSError("archive_reparse_point_rejected")
            if stat.S_ISDIR(result.st_mode):
                pending.append(path)
                continue
            if (
                not stat.S_ISREG(result.st_mode)
                or result.st_nlink != 1
                or not entry.is_file(follow_symlinks=False)
            ):
                raise OSError("archive_non_regular_file_rejected")
            relative = path.relative_to(directory).as_posix()
            manifest[relative] = (result.st_size, _sha256_file(path))
    return dict(sorted(manifest.items()))


def _manifest_digest(manifest: Mapping[str, tuple[int, str]]) -> str:
    content = "\n".join(
        f"{name}\t{size}\t{digest}"
        for name, (size, digest) in sorted(manifest.items())
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write_manifest(
    path: Path,
    *,
    build_manifest: Mapping[str, tuple[int, str]],
) -> str:
    aggregate = _manifest_digest(build_manifest)
    payload = {
        "schema_version": 1,
        "attempt": ARCHIVE_NAME,
        "source_build": SOURCE_BUILD_RELATIVE_PATH.as_posix(),
        "source_deployment": SOURCE_DEPLOYMENT_RELATIVE_PATH.as_posix(),
        "file_count": len(build_manifest),
        "total_size": sum(size for size, _ in build_manifest.values()),
        "manifest_sha256": aggregate,
        "files": {
            name: {"size": size, "sha256": digest}
            for name, (size, digest) in sorted(build_manifest.items())
        },
        "deployment_empty": True,
        "same_volume_renames": True,
    }
    with path.open("xb") as stream:
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
    return aggregate


def _write_json(path: Path, payload: object) -> None:
    with path.open("xb") as stream:
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


def _manifest_payload(
    manifest: Mapping[str, tuple[int, str]],
) -> dict[str, object]:
    return {
        "file_count": len(manifest),
        "total_size": sum(size for size, _ in manifest.values()),
        "manifest_sha256": _manifest_digest(manifest),
        "files": {
            name: {"size": size, "sha256": digest}
            for name, (size, digest) in sorted(manifest.items())
        },
    }


def _read_audit_manifest(
    build_directory: Path,
) -> dict[str, tuple[int, str]]:
    audit_path = build_directory / "artifact_audit.json"
    if audit_path.stat().st_size > 4 * 1024 * 1024:
        raise OSError("artifact_audit_too_large")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    raw_manifest = payload.get("manifest")
    if not isinstance(raw_manifest, dict):
        raise OSError("artifact_audit_manifest_invalid")
    manifest: dict[str, tuple[int, str]] = {}
    for name, raw_details in raw_manifest.items():
        if (
            not isinstance(name, str)
            or not isinstance(raw_details, dict)
            or not isinstance(raw_details.get("size"), int)
            or not isinstance(raw_details.get("sha256"), str)
        ):
            raise OSError("artifact_audit_manifest_invalid")
        manifest[name] = (
            raw_details["size"],
            raw_details["sha256"],
        )
    return dict(sorted(manifest.items()))


def record_dry_run_incident(
    repository_root: Path,
    *,
    renamer: Renamer = os.rename,
) -> ArchiveOutcome:
    try:
        root = repository_root.resolve(strict=True)
        final_directory = root / "dist/SJTUClaw.dist"
        build_directory = root / SOURCE_BUILD_RELATIVE_PATH
        raw_directory = root / "packaging/deployment/pet_entry.dist"
        target = root / INCIDENT_RELATIVE_PATH
        if (
            os.path.lexists(target)
            or os.path.lexists(raw_directory)
            or not final_directory.is_dir()
            or not build_directory.is_dir()
        ):
            raise OSError("incident_source_invalid")
        final_manifest = _directory_manifest(final_directory)
        build_manifest = _directory_manifest(build_directory)
        if (
            final_manifest != _read_audit_manifest(build_directory)
            or len(final_manifest) != EXPECTED_FINAL_FILE_COUNT
            or sum(size for size, _ in final_manifest.values())
            != EXPECTED_FINAL_TOTAL_SIZE
            or final_manifest.get("SJTUClaw.exe", (0, ""))[1]
            != EXPECTED_FINAL_EXE_SHA256
            or len(build_manifest) != 7
        ):
            raise OSError("incident_evidence_mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.part"
        staging.mkdir()
        _write_json(
            staging / INCIDENT_FINAL_MANIFEST_NAME,
            _manifest_payload(final_manifest),
        )
        _write_json(
            staging / INCIDENT_BUILD_MANIFEST_NAME,
            _manifest_payload(build_manifest),
        )
        incident = {
            "schema_version": 1,
            "dry_run_cleanup_side_effect_confirmed": True,
            "raw_dist_present": False,
            "raw_dist_reconstructed": False,
            "third_build_attempts": 0,
            "final_dist": _manifest_payload(final_manifest),
            "build_evidence": _manifest_payload(build_manifest),
            "final_executable_sha256": EXPECTED_FINAL_EXE_SHA256,
            "environment_values_recorded": False,
        }
        _write_json(staging / INCIDENT_REPORT_NAME, incident)
        renamer(staging, target)
        return ArchiveOutcome(
            True,
            "standalone_dry_run_incident_recorded",
            len(final_manifest) + len(build_manifest),
            sum(size for size, _ in final_manifest.values())
            + sum(size for size, _ in build_manifest.values()),
            _manifest_digest(
                {
                    **{
                        f"final/{name}": details
                        for name, details in final_manifest.items()
                    },
                    **{
                        f"build/{name}": details
                        for name, details in build_manifest.items()
                    },
                }
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return ArchiveOutcome(
            False,
            "standalone_dry_run_incident_failed",
        )


def _same_volume(paths: tuple[Path, ...]) -> bool:
    drives = {
        os.path.splitdrive(os.fspath(path.resolve(strict=False)))[0].casefold()
        for path in paths
    }
    return len(drives) == 1 and "" not in drives


def _write_unpruned_manifest(
    path: Path,
    *,
    manifests: Mapping[str, Mapping[str, tuple[int, str]]],
) -> tuple[int, int, str]:
    flattened = {
        f"{source}/{name}": details
        for source, manifest in manifests.items()
        for name, details in manifest.items()
    }
    file_count = len(flattened)
    total_size = sum(size for size, _ in flattened.values())
    aggregate = _manifest_digest(flattened)
    payload = {
        "schema_version": 1,
        "archive": UNPRUNED_ARCHIVE_NAME,
        "same_volume_renames": True,
        "file_count": file_count,
        "total_size": total_size,
        "manifest_sha256": aggregate,
        "sources": {
            source: {
                "file_count": len(manifest),
                "total_size": sum(size for size, _ in manifest.values()),
                "manifest_sha256": _manifest_digest(manifest),
                "files": {
                    name: {"size": size, "sha256": digest}
                    for name, (size, digest) in manifest.items()
                },
            }
            for source, manifest in manifests.items()
        },
    }
    with path.open("xb") as stream:
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
    return file_count, total_size, aggregate


def archive_unpruned_standalone(
    repository_root: Path,
    *,
    renamer: Renamer = os.rename,
) -> ArchiveOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return ArchiveOutcome(
            False,
            "standalone_unpruned_archive_source_invalid",
        )
    sources = {
        SOURCE_BUILD_RELATIVE_PATH.as_posix(): (
            root / SOURCE_BUILD_RELATIVE_PATH
        ),
        SOURCE_DEPLOYMENT_RELATIVE_PATH.as_posix(): (
            root / SOURCE_DEPLOYMENT_RELATIVE_PATH
        ),
        DIST_RELATIVE_PATH.as_posix(): root / DIST_RELATIVE_PATH,
    }
    archive_parent = root / UNPRUNED_ARCHIVE_PARENT_RELATIVE_PATH
    archive_target = archive_parent / UNPRUNED_ARCHIVE_NAME
    if archive_target.exists() or archive_target.is_symlink():
        return ArchiveOutcome(
            False,
            "standalone_unpruned_archive_failed",
        )
    if any(
        not _validate_existing_chain(root, source)
        or not source.is_dir()
        for source in sources.values()
    ):
        return ArchiveOutcome(
            False,
            "standalone_unpruned_archive_source_invalid",
        )
    try:
        manifests = {
            relative: _directory_manifest(source)
            for relative, source in sources.items()
        }
    except OSError:
        return ArchiveOutcome(
            False,
            "standalone_unpruned_archive_source_invalid",
        )
    build_manifest = manifests[SOURCE_BUILD_RELATIVE_PATH.as_posix()]
    raw_manifest = manifests[SOURCE_DEPLOYMENT_RELATIVE_PATH.as_posix()]
    final_manifest = manifests[DIST_RELATIVE_PATH.as_posix()]
    required_build_evidence = {
        "artifact_audit.json",
        "build_report.json",
        "compilation-report.xml",
    }
    if (
        not required_build_evidence.issubset(build_manifest)
        or not raw_manifest
        or raw_manifest != final_manifest
        or not _same_volume(
            (root, *sources.values(), archive_target)
        )
    ):
        return ArchiveOutcome(
            False,
            "standalone_unpruned_archive_source_invalid",
        )
    try:
        archive_parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ArchiveOutcome(False, "standalone_unpruned_archive_failed")
    if (
        not _validate_existing_chain(root, archive_parent)
        or _is_reparse_point(archive_parent)
    ):
        return ArchiveOutcome(False, "standalone_unpruned_archive_failed")
    staging = (
        archive_parent
        / f".{UNPRUNED_ARCHIVE_NAME}.{uuid.uuid4().hex}.part"
    )
    destinations = {
        relative: staging / relative
        for relative in sources
    }
    moved: list[str] = []
    file_count = 0
    total_size = 0
    aggregate: str | None = None
    try:
        staging.mkdir()
        (staging / "build").mkdir()
        (staging / "packaging").mkdir()
        file_count, total_size, aggregate = _write_unpruned_manifest(
            staging / UNPRUNED_MANIFEST_NAME,
            manifests=manifests,
        )
        for relative, source in sources.items():
            renamer(source, destinations[relative])
            moved.append(relative)
        if any(source.exists() for source in sources.values()):
            raise OSError("unpruned_archive_source_remained")
        if any(
            _directory_manifest(destinations[relative])
            != manifests[relative]
            for relative in sources
        ):
            raise OSError("unpruned_archive_manifest_mismatch")
        renamer(staging, archive_target)
        if any(source.exists() for source in sources.values()):
            raise OSError("unpruned_archive_publish_source_remained")
        if any(
            _directory_manifest(archive_target / relative)
            != manifests[relative]
            for relative in sources
        ):
            raise OSError("unpruned_archive_publish_manifest_mismatch")
        if not (
            archive_target / UNPRUNED_MANIFEST_NAME
        ).is_file():
            raise OSError("unpruned_archive_manifest_missing")
        return ArchiveOutcome(
            True,
            "standalone_unpruned_archive_complete",
            file_count,
            total_size,
            aggregate,
        )
    except OSError:
        rollback_root = archive_target if archive_target.exists() else staging
        for relative in reversed(moved):
            archived = rollback_root / relative
            source = sources[relative]
            if archived.exists() and not source.exists():
                with contextlib.suppress(OSError):
                    source.parent.mkdir(parents=True, exist_ok=True)
                    renamer(archived, source)
        return ArchiveOutcome(False, "standalone_unpruned_archive_failed")


def archive_degraded_surviving_evidence(
    repository_root: Path,
    *,
    renamer: Renamer = os.rename,
) -> ArchiveOutcome:
    try:
        root = repository_root.resolve(strict=True)
        source_dist = root / DIST_RELATIVE_PATH
        source_final = source_dist / "SJTUClaw.dist"
        source_build = root / SOURCE_BUILD_RELATIVE_PATH
        source_raw = root / SOURCE_DEPLOYMENT_RELATIVE_PATH
        incident_directory = root / INCIDENT_RELATIVE_PATH
        archive_parent = (
            root / DEGRADED_ARCHIVE_PARENT_RELATIVE_PATH
        )
        archive_target = archive_parent / DEGRADED_ARCHIVE_NAME
        if (
            os.path.lexists(archive_target)
            or os.path.lexists(source_raw)
            or not source_final.is_dir()
            or not source_build.is_dir()
            or not incident_directory.is_dir()
            or sorted(path.name for path in source_dist.iterdir())
            != ["SJTUClaw.dist"]
        ):
            raise OSError("degraded_archive_source_invalid")
        final_manifest = _directory_manifest(source_final)
        build_manifest = _directory_manifest(source_build)
        audit_manifest = _read_audit_manifest(source_build)
        incident = json.loads(
            (
                incident_directory / INCIDENT_REPORT_NAME
            ).read_text(encoding="utf-8")
        )
        if (
            final_manifest != audit_manifest
            or final_manifest.get("SJTUClaw.exe", (0, ""))[1]
            != EXPECTED_FINAL_EXE_SHA256
            or len(final_manifest) != EXPECTED_FINAL_FILE_COUNT
            or sum(size for size, _ in final_manifest.values())
            != EXPECTED_FINAL_TOTAL_SIZE
            or len(build_manifest) != 7
            or incident.get("raw_dist_present") is not False
            or incident.get("raw_dist_reconstructed") is not False
            or incident.get("dry_run_cleanup_side_effect_confirmed")
            is not True
            or incident.get("final_dist")
            != _manifest_payload(final_manifest)
            or incident.get("build_evidence")
            != _manifest_payload(build_manifest)
            or not _same_volume(
                (
                    root,
                    source_dist,
                    source_build,
                    archive_target,
                )
            )
        ):
            raise OSError("degraded_archive_evidence_mismatch")
        archive_parent.mkdir(parents=True, exist_ok=True)
        if (
            not _validate_existing_chain(root, archive_parent)
            or _is_reparse_point(archive_parent)
        ):
            raise OSError("degraded_archive_parent_invalid")
    except (OSError, ValueError, json.JSONDecodeError):
        return ArchiveOutcome(
            False,
            "standalone_degraded_archive_source_invalid",
        )

    staging = (
        archive_parent
        / f".{DEGRADED_ARCHIVE_NAME}.{uuid.uuid4().hex}.part"
    )
    archived_dist = staging / DIST_RELATIVE_PATH
    archived_build = staging / SOURCE_BUILD_RELATIVE_PATH
    moved: list[tuple[Path, Path]] = []
    combined = {
        **{
            f"dist/SJTUClaw.dist/{name}": details
            for name, details in final_manifest.items()
        },
        **{
            f"build/windows-standalone/{name}": details
            for name, details in build_manifest.items()
        },
    }
    try:
        staging.mkdir()
        archived_build.parent.mkdir()
        report = {
            "schema_version": 1,
            "archive_mode": "degraded_surviving_evidence",
            "raw_dist_present": False,
            "raw_dist_reconstructed": False,
            "prior_raw_final_equality_reported": True,
            "current_raw_final_equality_reverified": False,
            "final_dist_manifest_verified": True,
            "compilation_report_preserved": True,
            "build_report_preserved": True,
            "artifact_audit_preserved": True,
            "dry_run_incident_recorded": True,
            "same_volume_renames": True,
            **_manifest_payload(combined),
        }
        _write_json(
            staging / DEGRADED_ARCHIVE_MANIFEST_NAME,
            report,
        )
        renamer(source_dist, archived_dist)
        moved.append((archived_dist, source_dist))
        renamer(source_build, archived_build)
        moved.append((archived_build, source_build))
        if (
            os.path.lexists(source_dist)
            or os.path.lexists(source_build)
            or os.path.lexists(source_raw)
            or _directory_manifest(
                archived_dist / "SJTUClaw.dist"
            )
            != final_manifest
            or _directory_manifest(archived_build)
            != build_manifest
        ):
            raise OSError("degraded_archive_postcondition_failed")
        renamer(staging, archive_target)
        if (
            os.path.lexists(source_dist)
            or os.path.lexists(source_build)
            or os.path.lexists(source_raw)
            or _directory_manifest(
                archive_target / "dist/SJTUClaw.dist"
            )
            != final_manifest
            or _directory_manifest(
                archive_target / SOURCE_BUILD_RELATIVE_PATH
            )
            != build_manifest
            or not (
                archive_target / DEGRADED_ARCHIVE_MANIFEST_NAME
            ).is_file()
            or any(
                path.name.endswith(".part")
                for path in archive_parent.iterdir()
            )
        ):
            raise OSError("degraded_archive_publish_failed")
        return ArchiveOutcome(
            True,
            "standalone_degraded_archive_complete",
            len(combined),
            sum(size for size, _ in combined.values()),
            _manifest_digest(combined),
        )
    except OSError:
        rollback_root = archive_target if archive_target.exists() else staging
        for archived, source in reversed(moved):
            candidate = (
                rollback_root / archived.relative_to(staging)
                if rollback_root == archive_target
                else archived
            )
            if candidate.exists() and not source.exists():
                with contextlib.suppress(OSError):
                    source.parent.mkdir(parents=True, exist_ok=True)
                    renamer(candidate, source)
        return ArchiveOutcome(
            False,
            "standalone_degraded_archive_failed",
        )


def _rollback(
    *,
    renamer: Renamer,
    archived_build: Path,
    source_build: Path,
    archived_deployment: Path,
    source_deployment: Path,
) -> None:
    if archived_deployment.exists() and not source_deployment.exists():
        with contextlib.suppress(OSError):
            renamer(archived_deployment, source_deployment)
    if archived_build.exists() and not source_build.exists():
        with contextlib.suppress(OSError):
            renamer(archived_build, source_build)


def archive_failed_standalone_attempt(
    repository_root: Path,
    *,
    renamer: Renamer = os.rename,
) -> ArchiveOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return ArchiveOutcome(
            False,
            "standalone_attempt_archive_source_invalid",
        )
    source_build = root / SOURCE_BUILD_RELATIVE_PATH
    source_deployment = root / SOURCE_DEPLOYMENT_RELATIVE_PATH
    dist = root / DIST_RELATIVE_PATH
    archive_parent = root / ARCHIVE_PARENT_RELATIVE_PATH
    archive_target = archive_parent / ARCHIVE_NAME
    if archive_target.exists() or archive_target.is_symlink():
        return ArchiveOutcome(
            False,
            "standalone_attempt_archive_occupied",
        )
    if (
        dist.exists()
        or dist.is_symlink()
        or not _validate_existing_chain(root, source_build)
        or not _validate_existing_chain(root, source_deployment)
        or not source_build.is_dir()
        or not source_deployment.is_dir()
    ):
        return ArchiveOutcome(
            False,
            "standalone_attempt_archive_source_invalid",
        )
    try:
        build_manifest = _directory_manifest(source_build)
        deployment_manifest = _directory_manifest(source_deployment)
    except OSError:
        return ArchiveOutcome(
            False,
            "standalone_attempt_archive_source_invalid",
        )
    if (
        build_manifest != EXPECTED_BUILD_FILES
        or deployment_manifest
        or not _same_volume(
            (root, source_build, source_deployment, archive_target)
        )
    ):
        return ArchiveOutcome(
            False,
            "standalone_attempt_archive_source_invalid",
        )
    try:
        archive_parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ArchiveOutcome(False, "standalone_attempt_archive_failed")
    if (
        not _validate_existing_chain(root, archive_parent)
        or _is_reparse_point(archive_parent)
    ):
        return ArchiveOutcome(False, "standalone_attempt_archive_failed")
    staging = archive_parent / f".{ARCHIVE_NAME}.{uuid.uuid4().hex}.part"
    archived_build = staging / ARCHIVED_BUILD_NAME
    archived_deployment = staging / ARCHIVED_DEPLOYMENT_NAME
    manifest_path = staging / MANIFEST_NAME
    aggregate: str | None = None
    try:
        staging.mkdir()
        aggregate = _write_manifest(
            manifest_path,
            build_manifest=build_manifest,
        )
        renamer(source_build, archived_build)
        renamer(source_deployment, archived_deployment)
        if (
            _directory_manifest(archived_build) != build_manifest
            or _directory_manifest(archived_deployment)
            or source_build.exists()
            or source_deployment.exists()
            or dist.exists()
        ):
            raise OSError("archive_postcondition_failed")
        renamer(staging, archive_target)
        if (
            _directory_manifest(
                archive_target / ARCHIVED_BUILD_NAME
            )
            != build_manifest
            or _directory_manifest(
                archive_target / ARCHIVED_DEPLOYMENT_NAME
            )
            or source_build.exists()
            or source_deployment.exists()
            or dist.exists()
            or not (archive_target / MANIFEST_NAME).is_file()
        ):
            raise OSError("archive_publish_failed")
        return ArchiveOutcome(
            True,
            "standalone_attempt_archive_complete",
            len(build_manifest),
            sum(size for size, _ in build_manifest.values()),
            aggregate,
        )
    except OSError:
        if staging.exists():
            _rollback(
                renamer=renamer,
                archived_build=archived_build,
                source_build=source_build,
                archived_deployment=archived_deployment,
                source_deployment=source_deployment,
            )
        elif archive_target.exists():
            _rollback(
                renamer=renamer,
                archived_build=(
                    archive_target / ARCHIVED_BUILD_NAME
                ),
                source_build=source_build,
                archived_deployment=(
                    archive_target / ARCHIVED_DEPLOYMENT_NAME
                ),
                source_deployment=source_deployment,
            )
        return ArchiveOutcome(False, "standalone_attempt_archive_failed")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive the fixed failed standalone attempt."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--confirm-archive", action="store_true")
    mode.add_argument(
        "--confirm-degraded-archive",
        action="store_true",
    )
    mode.add_argument(
        "--record-dry-run-incident",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.record_dry_run_incident:
        root = Path(__file__).resolve().parents[1]
        try:
            outcome = record_dry_run_incident(root)
        except Exception:
            print("safe_code=standalone_dry_run_incident_failed")
            return 2
        print(f"safe_code={outcome.safe_code}")
        return 0 if outcome.completed else 2
    if arguments.confirm_degraded_archive:
        root = Path(__file__).resolve().parents[1]
        try:
            outcome = archive_degraded_surviving_evidence(root)
        except Exception:
            print("safe_code=standalone_degraded_archive_failed")
            return 2
        if outcome.completed:
            print(
                " ".join(
                    (
                        "standalone_degraded_archived=true",
                        f"file_count={outcome.file_count}",
                        f"total_size={outcome.total_size}",
                        f"manifest_sha256={outcome.manifest_sha256}",
                    )
                )
            )
        print(f"safe_code={outcome.safe_code}")
        return 0 if outcome.completed else 2
    if not arguments.confirm_archive:
        print("safe_code=standalone_attempt_archive_disabled")
        return 0
    root = Path(__file__).resolve().parents[1]
    try:
        outcome = archive_failed_standalone_attempt(root)
    except Exception:
        print("safe_code=standalone_attempt_archive_failed")
        return 2
    if outcome.completed:
        print(
            " ".join(
                (
                    "standalone_attempt_archived=true",
                    f"file_count={outcome.file_count}",
                    f"total_size={outcome.total_size}",
                    f"manifest_sha256={outcome.manifest_sha256}",
                )
            )
        )
    print(f"safe_code={outcome.safe_code}")
    return 0 if outcome.completed else 2


if __name__ == "__main__":
    sys.exit(main())
