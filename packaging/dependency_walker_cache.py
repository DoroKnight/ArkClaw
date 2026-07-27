from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

SOURCE_RELATIVE_PATH = Path(
    "build/tool-quarantine/dependency-walker/extracted"
)
CACHE_RELATIVE_PATH = Path(
    "build/nuitka-cache/downloads/depends/x86_64"
)
EXPECTED_FILES = {
    "depends.exe": (
        566_272,
        "57c483dc985a9757501993e969c2a7043c26517f97fd49a42b33d2d6a4193d8b",
    ),
    "depends.dll": (
        12_288,
        "7a5cae7605ae5d8c8aee3e6d8e77e455537b636b395b8f00aebe17bf8b228770",
    ),
}
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
PE_MACHINE_AMD64 = 0x8664
PE32_PLUS_MAGIC = 0x20B
COPY_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class CacheOutcome:
    safe_code: str
    completed: bool
    idempotent: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        stat_result = path.lstat()
    except OSError:
        return True
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(int(attributes) & FILE_ATTRIBUTE_REPARSE_POINT)


def _is_single_regular_file(path: Path) -> bool:
    try:
        stat_result = path.stat()
    except OSError:
        return False
    return (
        path.is_file()
        and not _is_reparse_point(path)
        and stat_result.st_nlink == 1
    )


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((path, root)) == os.fspath(root)
    except ValueError:
        return False


def _validate_existing_path_chain(root: Path, target: Path) -> bool:
    try:
        resolved_root = root.resolve(strict=True)
        relative = target.relative_to(root)
    except (OSError, ValueError):
        return False
    current = resolved_root
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
        if not _path_is_within(resolved, resolved_root):
            return False
    return True


def _is_amd64_pe32_plus(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(4096)
        if len(header) < 0x100 or header[:2] != b"MZ":
            return False
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        if (
            pe_offset + 26 > len(header)
            or header[pe_offset : pe_offset + 4] != b"PE\x00\x00"
        ):
            return False
        machine = int(struct.unpack_from("<H", header, pe_offset + 4)[0])
        optional_magic = int(
            struct.unpack_from("<H", header, pe_offset + 24)[0]
        )
        return (
            machine == PE_MACHINE_AMD64
            and optional_magic == PE32_PLUS_MAGIC
        )
    except (OSError, struct.error):
        return False


def _validate_fixed_file(path: Path, name: str) -> bool:
    expected_size, expected_hash = EXPECTED_FILES[name]
    try:
        return (
            _is_single_regular_file(path)
            and path.stat().st_size == expected_size
            and _sha256_file(path) == expected_hash
            and _is_amd64_pe32_plus(path)
        )
    except OSError:
        return False


def _directory_entries(path: Path) -> tuple[str, ...] | None:
    try:
        return tuple(sorted(entry.name for entry in path.iterdir()))
    except OSError:
        return None


def _validate_fixed_directory(
    repository_root: Path,
    directory: Path,
) -> bool:
    if (
        not directory.is_dir()
        or not _validate_existing_path_chain(repository_root, directory)
        or _is_reparse_point(directory)
        or _directory_entries(directory) != tuple(sorted(EXPECTED_FILES))
    ):
        return False
    return all(
        _validate_fixed_file(directory / name, name)
        for name in EXPECTED_FILES
    )


def validate_dependency_walker_cache(
    repository_root: Path,
) -> CacheOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return CacheOutcome("dependency_walker_cache_invalid", False)
    cache_directory = root / CACHE_RELATIVE_PATH
    if not _validate_fixed_directory(root, cache_directory):
        return CacheOutcome("dependency_walker_cache_invalid", False)
    return CacheOutcome("none", True, True)


def _copy_verified_file(source: Path, temporary: Path, name: str) -> None:
    expected_size, expected_hash = EXPECTED_FILES[name]
    digest = hashlib.sha256()
    actual_size = 0
    with source.open("rb") as input_stream, temporary.open("xb") as output:
        while True:
            chunk = input_stream.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            actual_size += len(chunk)
            if actual_size > expected_size:
                raise OSError("source_size_invalid")
            output.write(chunk)
            digest.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    if actual_size != expected_size or digest.hexdigest() != expected_hash:
        raise OSError("source_hash_invalid")


def _remove_owned_staging_directory(
    directory: Path,
    parent: Path,
) -> None:
    try:
        if directory.parent != parent or not directory.name.endswith(".part"):
            return
        if _is_reparse_point(directory):
            return
        for entry in directory.iterdir():
            if (
                entry.name not in EXPECTED_FILES
                and not entry.name.endswith(".part")
            ):
                return
            if entry.is_file() and not _is_reparse_point(entry):
                entry.unlink(missing_ok=True)
        directory.rmdir()
    except OSError:
        return


def stage_dependency_walker_cache(
    repository_root: Path,
) -> CacheOutcome:
    try:
        root = repository_root.resolve(strict=True)
    except OSError:
        return CacheOutcome("dependency_walker_source_invalid", False)
    source_directory = root / SOURCE_RELATIVE_PATH
    cache_directory = root / CACHE_RELATIVE_PATH
    cache_parent = cache_directory.parent

    if not _validate_fixed_directory(root, source_directory):
        return CacheOutcome("dependency_walker_source_invalid", False)
    if not _validate_existing_path_chain(root, cache_parent):
        return CacheOutcome("dependency_walker_cache_invalid", False)

    if cache_directory.exists() or cache_directory.is_symlink():
        if _validate_fixed_directory(root, cache_directory):
            return CacheOutcome("none", True, True)
        entries = _directory_entries(cache_directory)
        if entries == tuple(sorted(EXPECTED_FILES)):
            return CacheOutcome("dependency_walker_cache_occupied", False)
        return CacheOutcome("dependency_walker_cache_invalid", False)

    staging_directory = cache_parent / (
        f".x86_64.{uuid.uuid4().hex}.part"
    )
    try:
        cache_parent.mkdir(parents=True, exist_ok=True)
        if (
            not _validate_existing_path_chain(root, cache_parent)
            or _is_reparse_point(cache_parent)
        ):
            return CacheOutcome("dependency_walker_cache_invalid", False)
        staging_directory.mkdir()
        for name in EXPECTED_FILES:
            temporary = staging_directory / f".{name}.part"
            final = staging_directory / name
            _copy_verified_file(source_directory / name, temporary, name)
            os.rename(temporary, final)
        if not _validate_fixed_directory(root, staging_directory):
            return CacheOutcome("dependency_walker_staging_failed", False)
        os.rename(staging_directory, cache_directory)
        if not _validate_fixed_directory(root, cache_directory):
            return CacheOutcome("dependency_walker_staging_failed", False)
        return CacheOutcome("none", True, False)
    except OSError:
        return CacheOutcome("dependency_walker_staging_failed", False)
    finally:
        if staging_directory.exists():
            _remove_owned_staging_directory(staging_directory, cache_parent)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or stage the fixed Dependency Walker cache."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--confirm-staging", action="store_true")
    mode.add_argument("--validate-cache", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    repository_root = Path(__file__).resolve().parents[1]
    if arguments.validate_cache:
        outcome = validate_dependency_walker_cache(repository_root)
        print(
            "dependency_walker_cache_valid="
            f"{str(outcome.completed).lower()} safe_code={outcome.safe_code}"
        )
        return 0 if outcome.completed else 2
    if not arguments.confirm_staging:
        print("safe_code=dependency_walker_staging_disabled")
        return 0
    outcome = stage_dependency_walker_cache(repository_root)
    print(
        "dependency_walker_staged="
        f"{str(outcome.completed).lower()} "
        f"idempotent={str(outcome.idempotent).lower()} "
        f"safe_code={outcome.safe_code}"
    )
    return 0 if outcome.completed else 2


if __name__ == "__main__":
    sys.exit(main())
