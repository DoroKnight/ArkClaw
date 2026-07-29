from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "packaging" / "transactional_archive.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_ARCHIVE: Any = _load("transactional_archive", _MODULE_PATH)


def _source(
    root: Path,
    source_class: str,
    relative: str,
    content: bytes,
) -> Any:
    directory = root / relative
    directory.mkdir(parents=True)
    (directory / "payload.bin").write_bytes(content)
    return _ARCHIVE.ArchiveSource(
        source_class,
        Path(relative),
        Path(relative),
    )


def _run(
    root: Path,
    sources: tuple[Any, ...],
    **kwargs: object,
) -> Any:
    return _ARCHIVE.transactional_archive(
        root,
        archive_parent_relative_path=Path("build/archive"),
        archive_name="fixture",
        sources=sources,
        staging_name_factory=lambda _name: ".fixture.fixed.part",
        **kwargs,
    )


def test_transactional_archive_success_preserves_exact_payload(
    tmp_path: Path,
) -> None:
    sources = (
        _source(tmp_path, "dist", "dist", b"dist"),
        _source(
            tmp_path,
            "deployment",
            "packaging/deployment",
            b"deployment",
        ),
    )
    expected = {
        source.source_relative_path.as_posix(): (
            _ARCHIVE.snapshot_directory(
                tmp_path / source.source_relative_path
            )
        )
        for source in sources
    }

    outcome = _run(tmp_path, sources)

    target = tmp_path / "build/archive/fixture"
    assert outcome.completed
    assert outcome.safe_code == "transactional_archive_complete"
    assert outcome.diagnostic is None
    assert not (tmp_path / "dist").exists()
    assert not (tmp_path / "packaging/deployment").exists()
    assert (target / "archive_manifest.json").is_file()
    for source in sources:
        assert (
            _ARCHIVE.snapshot_directory(
                target / source.archive_relative_path
            )
            == expected[source.source_relative_path.as_posix()]
        )
    manifest = json.loads(
        (target / "archive_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["absolute_paths_recorded"] is False
    assert manifest["environment_values_recorded"] is False


def test_transactional_archive_rejects_destination_collision(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, "dist", "dist", b"payload")
    (tmp_path / "build/archive/fixture").mkdir(parents=True)

    outcome = _run(tmp_path, (source,))

    assert not outcome.completed
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.operation_stage == "preflight"
    assert outcome.diagnostic.exception_category == "destination_exists"
    assert (tmp_path / "dist").is_dir()


def test_transactional_archive_rejects_stale_part(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, "dist", "dist", b"payload")
    (tmp_path / "build/archive/.fixture.stale.part").mkdir(parents=True)

    outcome = _run(tmp_path, (source,))

    assert not outcome.completed
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.exception_category == "destination_exists"
    assert outcome.diagnostic.failed_part_preserved


def test_default_staging_name_is_short_and_transaction_scoped() -> None:
    name = _ARCHIVE._default_staging_name(
        "20260729T071602Z-pre-autostart-ui-rebuild"
    )

    assert name.startswith(".txn-")
    assert name.endswith(".part")
    assert len(name) <= 40
    assert "20260729T071602Z-pre-autostart-ui-rebuild" not in name


def test_transactional_archive_rejects_missing_source(
    tmp_path: Path,
) -> None:
    source = _ARCHIVE.ArchiveSource(
        "dist",
        Path("dist"),
        Path("dist"),
    )

    outcome = _run(tmp_path, (source,))

    assert not outcome.completed
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.exception_category == "source_missing"
    assert outcome.diagnostic.source_class == "dist"


@pytest.mark.parametrize(
    ("error", "category"),
    (
        (PermissionError(13, "sensitive-value"), "access_denied"),
        (OSError(5, "sensitive-value"), "rename_failed"),
    ),
)
def test_transactional_archive_classifies_move_failures_safely(
    tmp_path: Path,
    error: OSError,
    category: str,
) -> None:
    source = _source(tmp_path, "dist", "dist", b"payload")

    def fail_move(_source: Path, _destination: Path) -> None:
        raise error

    outcome = _run(tmp_path, (source,), renamer=fail_move)

    assert not outcome.completed
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.operation_stage == "move_source"
    assert outcome.diagnostic.exception_category == category
    assert not outcome.diagnostic.rollback_attempted
    assert outcome.diagnostic.original_sources_restored
    serialized = json.dumps(
        _ARCHIVE.diagnostic_payload(outcome.diagnostic),
        sort_keys=True,
    )
    assert "sensitive-value" not in serialized
    assert str(tmp_path) not in serialized


def test_transactional_archive_classifies_sharing_violation(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, "dist", "dist", b"payload")
    error = OSError(13, "sensitive-value")
    error.winerror = 32

    outcome = _run(
        tmp_path,
        (source,),
        renamer=lambda _source, _destination: (_ for _ in ()).throw(error),
    )

    assert outcome.diagnostic is not None
    assert outcome.diagnostic.exception_category == "sharing_violation"
    assert outcome.diagnostic.winerror_or_errno == 32


def test_transactional_archive_publish_failure_rolls_back(
    tmp_path: Path,
) -> None:
    sources = (
        _source(tmp_path, "dist", "dist", b"dist"),
        _source(
            tmp_path,
            "deployment",
            "packaging/deployment",
            b"deployment",
        ),
    )

    def fail_publish(source: Path, destination: Path) -> None:
        if source.name == ".fixture.fixed.part":
            raise OSError(5, "publish-sensitive")
        os.rename(source, destination)

    outcome = _run(tmp_path, sources, renamer=fail_publish)

    assert not outcome.completed
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.operation_stage == "publish"
    assert outcome.diagnostic.exception_category == "rename_failed"
    assert outcome.diagnostic.rollback_attempted
    assert outcome.diagnostic.rollback_completed
    assert outcome.diagnostic.original_sources_restored
    assert outcome.diagnostic.failed_part_preserved


def test_transactional_archive_partial_move_rolls_back_all_sources(
    tmp_path: Path,
) -> None:
    sources = (
        _source(tmp_path, "dist", "dist", b"dist"),
        _source(
            tmp_path,
            "deployment",
            "packaging/deployment",
            b"deployment",
        ),
    )
    calls = 0

    def fail_second_move(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(5, "move-sensitive")
        os.rename(source, destination)

    outcome = _run(tmp_path, sources, renamer=fail_second_move)

    assert outcome.diagnostic is not None
    assert outcome.diagnostic.operation_stage == "move_source"
    assert outcome.diagnostic.source_class == "deployment"
    assert outcome.diagnostic.rollback_completed
    assert (tmp_path / "dist/payload.bin").read_bytes() == b"dist"
    assert (
        tmp_path / "packaging/deployment/payload.bin"
    ).read_bytes() == b"deployment"


def test_transactional_archive_reports_rollback_failure(
    tmp_path: Path,
) -> None:
    sources = (
        _source(tmp_path, "dist", "dist", b"dist"),
        _source(
            tmp_path,
            "deployment",
            "packaging/deployment",
            b"deployment",
        ),
    )
    calls = 0

    def fail_move_and_rollback(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise PermissionError(13, "rollback-sensitive")
        os.rename(source, destination)

    outcome = _run(
        tmp_path,
        sources,
        renamer=fail_move_and_rollback,
    )

    assert not outcome.completed
    assert outcome.diagnostic is not None
    assert outcome.diagnostic.operation_stage == "rollback"
    assert outcome.diagnostic.exception_category == "rollback_failed"
    assert outcome.diagnostic.rollback_attempted
    assert not outcome.diagnostic.rollback_completed
    assert not outcome.diagnostic.original_sources_restored
    assert outcome.diagnostic.failed_part_preserved


def test_transactional_archive_manifest_mismatch_rolls_back(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, "dist", "dist", b"payload")

    def mismatching_snapshot(path: Path) -> Any:
        snapshot = _ARCHIVE.snapshot_directory(path)
        if ".fixture.fixed.part" in path.parts:
            files = dict(snapshot.files)
            files["unexpected.bin"] = (1, "0" * 64)
            return _ARCHIVE.DirectorySnapshot(
                snapshot.directories,
                files,
            )
        return snapshot

    outcome = _run(
        tmp_path,
        (source,),
        snapshotter=mismatching_snapshot,
    )

    assert outcome.diagnostic is not None
    assert outcome.diagnostic.operation_stage == "verify_part"
    assert outcome.diagnostic.exception_category == "manifest_mismatch"
    assert outcome.diagnostic.rollback_completed
    assert (tmp_path / "dist/payload.bin").is_file()


def test_transactional_archive_preserves_empty_directories(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, "temp_output", "build/temp", b"payload")
    (tmp_path / "build/temp/empty/nested").mkdir(parents=True)

    outcome = _run(tmp_path, (source,))

    assert outcome.completed
    target = tmp_path / "build/archive/fixture/build/temp"
    assert (target / "empty/nested").is_dir()


def test_transactional_archive_diagnostic_has_strict_safe_fields(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, "dist", "dist", b"payload")
    secret = "api-key-never-log-this-value"

    outcome = _run(
        tmp_path,
        (source,),
        renamer=lambda _source, _destination: (
            (_ for _ in ()).throw(PermissionError(13, secret))
        ),
    )

    assert outcome.diagnostic is not None
    payload = _ARCHIVE.diagnostic_payload(outcome.diagnostic)
    assert set(payload) == {
        "operation_stage",
        "source_class",
        "exception_category",
        "winerror_or_errno",
        "rollback_attempted",
        "rollback_completed",
        "original_sources_restored",
        "failed_part_preserved",
    }
    visible = repr(payload)
    assert secret not in visible
    assert str(tmp_path) not in visible
