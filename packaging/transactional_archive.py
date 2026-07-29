from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
OPERATION_STAGES = frozenset(
    {
        "preflight",
        "create_part",
        "move_source",
        "verify_part",
        "publish",
        "rollback",
    }
)
SOURCE_CLASSES = frozenset(
    {
        "dist",
        "deployment",
        "build_output",
        "temp_output",
        "failed_part",
    }
)
EXCEPTION_CATEGORIES = frozenset(
    {
        "destination_exists",
        "source_missing",
        "access_denied",
        "sharing_violation",
        "path_not_found",
        "rename_failed",
        "manifest_mismatch",
        "rollback_failed",
        "unexpected_filesystem_error",
    }
)


@dataclass(frozen=True, slots=True)
class ArchiveSource:
    source_class: str
    source_relative_path: Path
    archive_relative_path: Path


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    directories: tuple[str, ...]
    files: Mapping[str, tuple[int, str]]


@dataclass(frozen=True, slots=True)
class ArchiveDiagnostic:
    operation_stage: str
    source_class: str | None
    exception_category: str
    winerror_or_errno: int | None
    rollback_attempted: bool
    rollback_completed: bool
    original_sources_restored: bool
    failed_part_preserved: bool


@dataclass(frozen=True, slots=True)
class TransactionalArchiveOutcome:
    completed: bool
    safe_code: str
    archive_name: str
    file_count: int = 0
    total_size_bytes: int = 0
    manifest_sha256: str | None = None
    diagnostic: ArchiveDiagnostic | None = None


Renamer = Callable[[Path, Path], None]
Snapshotter = Callable[[Path], DirectorySnapshot]
StagingNameFactory = Callable[[str], str]


class _ArchiveStateError(OSError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


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


def _validate_existing_chain(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
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


def snapshot_directory(directory: Path) -> DirectorySnapshot:
    if (
        not directory.is_dir()
        or _is_reparse_point(directory)
        or not stat.S_ISDIR(directory.lstat().st_mode)
    ):
        raise OSError("archive_directory_invalid")
    directories: list[str] = []
    files: dict[str, tuple[int, str]] = {}
    pending = [directory]
    while pending:
        current = pending.pop()
        for entry in os.scandir(current):
            path = Path(entry.path)
            result = path.lstat()
            if _is_reparse_point(path):
                raise OSError("archive_reparse_point_rejected")
            relative = path.relative_to(directory).as_posix()
            if stat.S_ISDIR(result.st_mode):
                directories.append(relative)
                pending.append(path)
                continue
            if (
                not stat.S_ISREG(result.st_mode)
                or result.st_nlink != 1
                or not entry.is_file(follow_symlinks=False)
            ):
                raise OSError("archive_non_regular_file_rejected")
            files[relative] = (result.st_size, _sha256_file(path))
    return DirectorySnapshot(
        tuple(sorted(directories)),
        dict(sorted(files.items())),
    )


def combined_file_manifest(
    snapshots: Mapping[str, DirectorySnapshot],
) -> dict[str, tuple[int, str]]:
    return dict(
        sorted(
            (
                f"{source}/{relative}",
                details,
            )
            for source, snapshot in snapshots.items()
            for relative, details in snapshot.files.items()
        )
    )


def manifest_sha256(
    manifest: Mapping[str, tuple[int, str]],
) -> str:
    payload = "\n".join(
        f"{name}\t{size}\t{digest}"
        for name, (size, digest) in sorted(manifest.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _snapshot_payload(snapshot: DirectorySnapshot) -> dict[str, object]:
    return {
        "directory_count": len(snapshot.directories),
        "file_count": len(snapshot.files),
        "total_size_bytes": sum(
            size for size, _ in snapshot.files.values()
        ),
        "manifest_sha256": manifest_sha256(snapshot.files),
        "directories": snapshot.directories,
        "files": {
            name: {"size": size, "sha256": digest}
            for name, (size, digest) in snapshot.files.items()
        },
    }


def _write_manifest(
    path: Path,
    *,
    archive_name: str,
    snapshots: Mapping[str, DirectorySnapshot],
) -> tuple[int, int, str]:
    combined = combined_file_manifest(snapshots)
    file_count = len(combined)
    total_size = sum(size for size, _ in combined.values())
    digest = manifest_sha256(combined)
    payload = {
        "schema_version": 1,
        "archive_name": archive_name,
        "file_count": file_count,
        "total_size_bytes": total_size,
        "manifest_sha256": digest,
        "sources": {
            source: _snapshot_payload(snapshot)
            for source, snapshot in sorted(snapshots.items())
        },
        "same_volume_renames": True,
        "absolute_paths_recorded": False,
        "environment_values_recorded": False,
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
    return file_count, total_size, digest


def diagnostic_payload(
    diagnostic: ArchiveDiagnostic,
) -> dict[str, object]:
    payload = asdict(diagnostic)
    if (
        payload["operation_stage"] not in OPERATION_STAGES
        or payload["exception_category"] not in EXCEPTION_CATEGORIES
        or (
            payload["source_class"] is not None
            and payload["source_class"] not in SOURCE_CLASSES
        )
    ):
        raise ValueError("invalid_archive_diagnostic")
    return payload


def _exception_category(
    error: OSError,
    *,
    stage: str,
) -> str:
    if isinstance(error, _ArchiveStateError):
        return error.category
    code = getattr(error, "winerror", None)
    if code in {32, 33}:
        return "sharing_violation"
    if isinstance(error, PermissionError):
        return "access_denied"
    if isinstance(error, FileExistsError):
        return "destination_exists"
    if isinstance(error, FileNotFoundError):
        return "source_missing" if stage == "preflight" else "path_not_found"
    if stage in {"move_source", "publish"}:
        return "rename_failed"
    return "unexpected_filesystem_error"


def _same_volume(paths: Sequence[Path]) -> bool:
    try:
        devices = {
            (
                path
                if path.exists()
                else next(
                    parent
                    for parent in path.parents
                    if parent.exists()
                )
            ).stat().st_dev
            for path in paths
        }
    except (OSError, StopIteration):
        return False
    return len(devices) == 1


def _default_staging_name(archive_name: str) -> str:
    archive_digest = hashlib.sha256(archive_name.encode("utf-8")).hexdigest()[:12]
    return f".txn-{archive_digest}-{uuid.uuid4().hex[:12]}.part"


def transactional_archive(
    repository_root: Path,
    *,
    archive_parent_relative_path: Path,
    archive_name: str,
    sources: Sequence[ArchiveSource],
    renamer: Renamer = os.rename,
    snapshotter: Snapshotter = snapshot_directory,
    staging_name_factory: StagingNameFactory = _default_staging_name,
) -> TransactionalArchiveOutcome:
    stage = "preflight"
    current_source_class: str | None = None
    moved: list[ArchiveSource] = []
    rollback_attempted = False
    rollback_completed = False
    original_sources_restored = False
    failed_part_preserved = False
    stale_part_detected = False
    staging: Path | None = None
    archive_target: Path | None = None
    snapshots: dict[str, DirectorySnapshot] = {}
    file_count = 0
    total_size = 0
    aggregate: str | None = None
    try:
        root = repository_root.resolve(strict=True)
        archive_parent = root / archive_parent_relative_path
        archive_target = archive_parent / archive_name
        if (
            not archive_name
            or Path(archive_name).name != archive_name
            or Path(archive_name).is_absolute()
            or len(sources) == 0
        ):
            raise _ArchiveStateError("unexpected_filesystem_error")
        source_paths: set[Path] = set()
        destination_paths: set[Path] = set()
        for source in sources:
            current_source_class = source.source_class
            source_path = root / source.source_relative_path
            destination_path = source.archive_relative_path
            if (
                source.source_class not in SOURCE_CLASSES
                or source.source_relative_path.is_absolute()
                or destination_path.is_absolute()
                or source_path in source_paths
                or destination_path in destination_paths
                or not _validate_existing_chain(root, source_path)
                or not source_path.is_dir()
            ):
                raise _ArchiveStateError("source_missing")
            source_paths.add(source_path)
            destination_paths.add(destination_path)
        if archive_target.exists() or archive_target.is_symlink():
            raise _ArchiveStateError("destination_exists")
        if archive_parent.exists():
            stale_part_detected = any(
                entry.name.startswith(".") and entry.name.endswith(".part")
                for entry in os.scandir(archive_parent)
            )
            if stale_part_detected:
                raise _ArchiveStateError("destination_exists")
        if not _same_volume(
            (
                root,
                *(root / source.source_relative_path for source in sources),
                archive_target,
            )
        ):
            raise _ArchiveStateError("rename_failed")
        snapshots = {
            source.source_relative_path.as_posix(): snapshotter(
                root / source.source_relative_path
            )
            for source in sources
        }
        stage = "create_part"
        current_source_class = None
        archive_parent.mkdir(parents=True, exist_ok=True)
        if (
            not _validate_existing_chain(root, archive_parent)
            or _is_reparse_point(archive_parent)
        ):
            raise _ArchiveStateError("access_denied")
        staging = archive_parent / staging_name_factory(archive_name)
        if staging.exists() or staging.is_symlink():
            raise _ArchiveStateError("destination_exists")
        staging.mkdir()
        for source in sources:
            (staging / source.archive_relative_path).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        file_count, total_size, aggregate = _write_manifest(
            staging / "archive_manifest.json",
            archive_name=archive_name,
            snapshots=snapshots,
        )
        stage = "move_source"
        for source in sources:
            current_source_class = source.source_class
            renamer(
                root / source.source_relative_path,
                staging / source.archive_relative_path,
            )
            moved.append(source)
        stage = "verify_part"
        for source in sources:
            current_source_class = source.source_class
            if (
                snapshotter(staging / source.archive_relative_path)
                != snapshots[source.source_relative_path.as_posix()]
            ):
                raise _ArchiveStateError("manifest_mismatch")
        stage = "publish"
        current_source_class = None
        renamer(staging, archive_target)
        staging = None
        for source in sources:
            current_source_class = source.source_class
            if (
                snapshotter(archive_target / source.archive_relative_path)
                != snapshots[source.source_relative_path.as_posix()]
            ):
                raise _ArchiveStateError("manifest_mismatch")
        if any(
            (root / source.source_relative_path).exists()
            for source in sources
        ):
            raise _ArchiveStateError("manifest_mismatch")
        return TransactionalArchiveOutcome(
            True,
            "transactional_archive_complete",
            archive_name,
            file_count,
            total_size,
            aggregate,
        )
    except OSError as error:
        original_stage = stage
        original_source_class = current_source_class
        category = _exception_category(error, stage=stage)
        rollback_root = (
            archive_target
            if archive_target is not None and archive_target.exists()
            else staging
        )
        if moved:
            rollback_attempted = True
            stage = "rollback"
            try:
                if rollback_root is None:
                    raise _ArchiveStateError("rollback_failed")
                root = repository_root.resolve(strict=True)
                for source in reversed(moved):
                    archived = rollback_root / source.archive_relative_path
                    original = root / source.source_relative_path
                    if archived.exists() and not original.exists():
                        original.parent.mkdir(parents=True, exist_ok=True)
                        renamer(archived, original)
                original_sources_restored = all(
                    (root / source.source_relative_path).is_dir()
                    and snapshotter(root / source.source_relative_path)
                    == snapshots[source.source_relative_path.as_posix()]
                    for source in sources
                )
                rollback_completed = original_sources_restored
            except OSError as rollback_error:
                error = rollback_error
                category = "rollback_failed"
                original_stage = "rollback"
                current_source_class = (
                    moved[-1].source_class if moved else current_source_class
                )
        else:
            original_sources_restored = all(
                (repository_root / source.source_relative_path).is_dir()
                for source in sources
            )
        failed_part_preserved = bool(
            stale_part_detected
            or (staging is not None and staging.exists())
            or (
                archive_target is not None
                and archive_target.exists()
                and not rollback_completed
            )
        )
        numeric_code = getattr(error, "winerror", None) or error.errno
        diagnostic = ArchiveDiagnostic(
            operation_stage=original_stage,
            source_class=(
                current_source_class
                if original_stage == "rollback"
                else original_source_class
            ),
            exception_category=category,
            winerror_or_errno=(
                int(numeric_code) if numeric_code is not None else None
            ),
            rollback_attempted=rollback_attempted,
            rollback_completed=rollback_completed,
            original_sources_restored=original_sources_restored,
            failed_part_preserved=failed_part_preserved,
        )
        return TransactionalArchiveOutcome(
            False,
            "transactional_archive_failed",
            archive_name,
            file_count,
            total_size,
            aggregate,
            diagnostic,
        )
