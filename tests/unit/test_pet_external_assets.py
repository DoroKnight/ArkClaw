"""Deterministic tests for the read-only external pet asset boundary."""

from __future__ import annotations

import hashlib
import io
import os
import traceback
from dataclasses import replace
from pathlib import Path

import pytest

from sjtuclaw.application.pet_external_assets import (
    ExternalAssetFilesystemError,
    ExternalFileIdentity,
    ExternalPetAssetLoader,
    ExternalPetAssetStatus,
)
from sjtuclaw.application.pet_renderer_model import (
    ExternalPetAssetDescriptor,
    ExternalPetAssetHashes,
    ExternalPetAssetLimits,
)
from sjtuclaw.infrastructure.pet_external_asset_filesystem import (
    WindowsExternalPetAssetFilesystem,
)


def _png(width: int = 16, height: int = 12) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 6, 0, 0, 0))
        + b"\0\0\0\0"
    )


def _atlas(
    texture: str = "fictional.png",
    *,
    region_bounds: str = "1, 2, 8, 7",
) -> bytes:
    return (
        f"{texture}\n"
        "size: 16, 12\n"
        "format: RGBA8888\n"
        "filter: Linear, Linear\n"
        "repeat: none\n"
        "fictional-region\n"
        "  rotate: false\n"
        f"  bounds: {region_bounds}\n"
        "  index: -1\n"
    ).encode()


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        current = value & 0x7F
        value >>= 7
        encoded.append(current | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def _binary_string(value: str) -> bytes:
    encoded = value.encode()
    return _varint(len(encoded) + 1) + encoded


def _skeleton(version: str = "3.8.99") -> bytes:
    return _binary_string("fictional-hash") + _binary_string(version) + bytes(16)


def _descriptor(root: str = "X:\\fictional-assets") -> ExternalPetAssetDescriptor:
    return ExternalPetAssetDescriptor(
        opaque_asset_id="fictional-bundle",
        asset_root=root,
        skeleton_filename="fictional.skel",
        atlas_filename="fictional.atlas",
        texture_filename="fictional.png",
    )


class _FakeRoot:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class _FakeHandle:
    def __init__(
        self,
        data: bytes,
        file_id: int,
        *,
        alternate_stream: bool = False,
        identity_changes: bool = False,
        reported_size_delta: int = 0,
    ) -> None:
        self._reader = io.BytesIO(data)
        self._identity = ExternalFileIdentity(
            volume_id=1,
            file_id=file_id,
            size_bytes=len(data) + reported_size_delta,
            link_count=1,
            modified_ticks=10,
        )
        self._alternate_stream = alternate_stream
        self._identity_changes = identity_changes
        self.close_count = 0

    @property
    def identity(self) -> ExternalFileIdentity:
        return self._identity

    def current_identity(self) -> ExternalFileIdentity:
        if self._identity_changes:
            return replace(self._identity, modified_ticks=11)
        return self._identity

    def has_alternate_data_streams(self) -> bool:
        return self._alternate_stream

    def read(self, size: int = -1) -> bytes:
        return self._reader.read(size)

    def seek(self, offset: int) -> int:
        return self._reader.seek(offset)

    def close(self) -> None:
        self.close_count += 1
        self._reader.close()


class _FakeFilesystem:
    def __init__(self) -> None:
        self.root = _FakeRoot()
        self.root_error: ExternalPetAssetStatus | None = None
        self.file_errors: dict[str, ExternalPetAssetStatus] = {}
        self.handles = {
            "fictional.skel": _FakeHandle(_skeleton(), 1),
            "fictional.atlas": _FakeHandle(_atlas(), 2),
            "fictional.png": _FakeHandle(_png(), 3),
        }
        self.opened_names: list[str] = []

    def open_root(self, root: str) -> _FakeRoot:
        del root
        if self.root_error is not None:
            raise ExternalAssetFilesystemError(self.root_error)
        return self.root

    def open_file(self, root: object, filename: str) -> _FakeHandle:
        assert root is self.root
        self.opened_names.append(filename)
        if filename in self.file_errors:
            raise ExternalAssetFilesystemError(self.file_errors[filename])
        return self.handles[filename]


def test_valid_bundle_publishes_verified_metadata_and_open_handles() -> None:
    filesystem = _FakeFilesystem()
    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.succeeded
    bundle = result.bundle
    assert bundle is not None
    assert bundle.metadata.texture.width == 16
    assert bundle.metadata.texture.height == 12
    assert bundle.metadata.texture.color_type == 6
    assert bundle.metadata.atlas.page_count == 1
    assert bundle.metadata.atlas.region_count == 1
    assert bundle.metadata.skeleton.version == "3.8.99"
    assert bundle.metadata.skeleton.major == 3
    assert bundle.metadata.skeleton.minor == 8
    assert filesystem.opened_names == [
        "fictional.skel",
        "fictional.atlas",
        "fictional.png",
    ]
    assert all(handle.close_count == 0 for handle in filesystem.handles.values())

    bundle.close()
    bundle.close()
    assert bundle.closed
    assert all(handle.close_count == 1 for handle in filesystem.handles.values())
    assert filesystem.root.close_count == 1


def test_successful_load_retains_the_verified_bytes() -> None:
    filesystem = _FakeFilesystem()

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.succeeded
    bundle = result.bundle
    assert bundle is not None
    assert bundle.snapshot.skeleton_bytes == _skeleton()
    assert bundle.snapshot.atlas_bytes == _atlas()
    assert bundle.snapshot.texture_bytes == _png()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle backend")
def test_windows_backend_loads_only_runtime_created_micro_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "fictional.skel").write_bytes(_skeleton())
    (tmp_path / "fictional.atlas").write_bytes(_atlas())
    (tmp_path / "fictional.png").write_bytes(_png())

    result = ExternalPetAssetLoader(
        WindowsExternalPetAssetFilesystem()
    ).load(_descriptor(str(tmp_path)))

    assert result.succeeded
    assert result.bundle is not None
    result.bundle.close()


def test_missing_second_file_closes_first_handle_and_root() -> None:
    filesystem = _FakeFilesystem()
    filesystem.file_errors["fictional.atlas"] = ExternalPetAssetStatus.MISSING

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is ExternalPetAssetStatus.MISSING
    assert result.bundle is None
    assert filesystem.handles["fictional.skel"].close_count == 1
    assert filesystem.handles["fictional.atlas"].close_count == 0
    assert filesystem.root.close_count == 1


def test_reparse_root_is_rejected_without_opening_files() -> None:
    filesystem = _FakeFilesystem()
    filesystem.root_error = ExternalPetAssetStatus.REPARSE_POINT

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is ExternalPetAssetStatus.REPARSE_POINT
    assert filesystem.opened_names == []


@pytest.mark.parametrize(
    "status",
    [
        ExternalPetAssetStatus.REPARSE_POINT,
        ExternalPetAssetStatus.HARDLINK_INVALID,
        ExternalPetAssetStatus.NOT_REGULAR,
        ExternalPetAssetStatus.PATH_ESCAPE,
    ],
)
def test_filesystem_security_failures_are_fixed_and_atomic(
    status: ExternalPetAssetStatus,
) -> None:
    filesystem = _FakeFilesystem()
    filesystem.file_errors["fictional.skel"] = status

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is status
    assert result.bundle is None
    assert filesystem.root.close_count == 1


@pytest.mark.parametrize(
    ("root", "expected"),
    [
        ("https://invalid.example/assets", ExternalPetAssetStatus.ROOT_INVALID),
        ("\\\\host\\share\\assets", ExternalPetAssetStatus.ROOT_INVALID),
        ("\\\\?\\X:\\device", ExternalPetAssetStatus.ROOT_INVALID),
        ("X:\\fictional\\..\\escape", ExternalPetAssetStatus.ROOT_INVALID),
    ],
)
def test_unsafe_roots_fail_before_filesystem_access(
    root: str,
    expected: ExternalPetAssetStatus,
) -> None:
    filesystem = _FakeFilesystem()

    result = ExternalPetAssetLoader(filesystem).load(_descriptor(root))

    assert result.status is expected
    assert filesystem.opened_names == []


@pytest.mark.parametrize(
    "filename",
    [
        "..\\fictional.skel",
        "nested/fictional.skel",
        "X:\\fictional.skel",
        "fictional.skel:stream",
        "fictional\0.skel",
    ],
)
def test_unsafe_filename_fails_without_directory_scanning(filename: str) -> None:
    filesystem = _FakeFilesystem()
    descriptor = replace(_descriptor(), skeleton_filename=filename)

    result = ExternalPetAssetLoader(filesystem).load(descriptor)

    assert result.status is ExternalPetAssetStatus.PATH_ESCAPE
    assert filesystem.opened_names == []


def test_alternate_data_stream_is_rejected() -> None:
    filesystem = _FakeFilesystem()
    filesystem.handles["fictional.skel"] = _FakeHandle(
        _skeleton(),
        1,
        alternate_stream=True,
    )

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is ExternalPetAssetStatus.NOT_REGULAR


def test_individual_and_bundle_size_limits_are_centralized() -> None:
    filesystem = _FakeFilesystem()
    descriptor = replace(
        _descriptor(),
        limits=ExternalPetAssetLimits(
            atlas_max_bytes=1,
            skeleton_max_bytes=1024,
            texture_max_bytes=1024,
            bundle_max_bytes=2048,
        ),
    )

    result = ExternalPetAssetLoader(filesystem).load(descriptor)

    assert result.status is ExternalPetAssetStatus.TOO_LARGE


def test_invalid_png_header_is_rejected() -> None:
    filesystem = _FakeFilesystem()
    filesystem.handles["fictional.png"] = _FakeHandle(b"not-png", 3)

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is ExternalPetAssetStatus.TEXTURE_HEADER_INVALID


@pytest.mark.parametrize(
    ("atlas", "expected"),
    [
        (_atlas("other.png"), ExternalPetAssetStatus.ATLAS_TEXTURE_MISMATCH),
        (
            _atlas(region_bounds="12, 10, 8, 7"),
            ExternalPetAssetStatus.ATLAS_INVALID,
        ),
    ],
)
def test_atlas_texture_and_region_bounds_are_strict(
    atlas: bytes,
    expected: ExternalPetAssetStatus,
) -> None:
    filesystem = _FakeFilesystem()
    filesystem.handles["fictional.atlas"] = _FakeHandle(atlas, 2)

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is expected


def test_atlas_rejects_an_implicit_second_page() -> None:
    filesystem = _FakeFilesystem()
    extra_page = _atlas() + (
        b"\nother.png\nsize: 1, 1\nformat: RGBA8888\n"
        b"filter: Linear, Linear\nrepeat: none\n"
    )
    filesystem.handles["fictional.atlas"] = _FakeHandle(extra_page, 2)

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status in {
        ExternalPetAssetStatus.ATLAS_INVALID,
        ExternalPetAssetStatus.ATLAS_TEXTURE_MISMATCH,
    }


@pytest.mark.parametrize(
    ("skeleton", "expected"),
    [
        (b"\x80", ExternalPetAssetStatus.SKELETON_HEADER_INVALID),
        (_skeleton("4.2.0"), ExternalPetAssetStatus.SPINE_VERSION_INCOMPATIBLE),
    ],
)
def test_skeleton_header_and_version_are_limited(
    skeleton: bytes,
    expected: ExternalPetAssetStatus,
) -> None:
    filesystem = _FakeFilesystem()
    filesystem.handles["fictional.skel"] = _FakeHandle(skeleton, 1)

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is expected


@pytest.mark.parametrize(
    "handle",
    [
        _FakeHandle(_skeleton(), 1, identity_changes=True),
        _FakeHandle(_skeleton(), 1, reported_size_delta=1),
    ],
)
def test_toctou_or_size_change_is_rejected(handle: _FakeHandle) -> None:
    filesystem = _FakeFilesystem()
    filesystem.handles["fictional.skel"] = handle

    result = ExternalPetAssetLoader(filesystem).load(_descriptor())

    assert result.status is ExternalPetAssetStatus.CHANGED_DURING_READ


def test_hash_failure_publishes_no_snapshot() -> None:
    filesystem = _FakeFilesystem()
    descriptor = replace(
        _descriptor(),
        expected_sha256=ExternalPetAssetHashes(
            skeleton_sha256="0" * 64,
            atlas_sha256=hashlib.sha256(_atlas()).hexdigest(),
            texture_sha256=hashlib.sha256(_png()).hexdigest(),
        ),
    )

    result = ExternalPetAssetLoader(filesystem).load(descriptor)

    assert result.status is ExternalPetAssetStatus.HASH_MISMATCH
    assert result.bundle is None


def test_failures_do_not_expose_paths_content_or_exception_text(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive_root = "X:\\private-user\\secret-assets"

    class _ExplodingFilesystem(_FakeFilesystem):
        def open_root(self, root: str) -> _FakeRoot:
            del root
            raise RuntimeError("sensitive-low-level-detail")

    result = ExternalPetAssetLoader(_ExplodingFilesystem()).load(
        _descriptor(sensitive_root)
    )
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            repr(result),
            result.safe_message,
            caplog.text,
            captured.out,
            captured.err,
            "".join(traceback.format_stack()),
        )
    )

    assert result.status is ExternalPetAssetStatus.READ_FAILED
    assert sensitive_root not in visible
    assert "sensitive-low-level-detail" not in visible
