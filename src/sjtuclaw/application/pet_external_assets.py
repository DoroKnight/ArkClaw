"""Framework-free, read-only boundary for external desktop-pet assets."""

from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from sjtuclaw.application.pet_renderer_model import (
    ExternalAssetConfigStatus,
    ExternalPetAssetDescriptor,
    ExternalPetAssetHashes,
    validate_external_asset_descriptor,
)


class ExternalPetAssetStatus(StrEnum):
    OK = "ok"
    NOT_CONFIGURED = "external_assets_not_configured"
    ROOT_INVALID = "external_asset_root_invalid"
    PATH_ESCAPE = "external_asset_path_escape"
    REPARSE_POINT = "external_asset_reparse_point"
    HARDLINK_INVALID = "external_asset_hardlink_invalid"
    MISSING = "external_asset_missing"
    NOT_REGULAR = "external_asset_not_regular"
    TOO_LARGE = "external_asset_too_large"
    CHANGED_DURING_READ = "external_asset_changed_during_read"
    HASH_MISMATCH = "external_asset_hash_mismatch"
    TEXTURE_HEADER_INVALID = "texture_header_invalid"
    ATLAS_INVALID = "atlas_invalid"
    ATLAS_TEXTURE_MISMATCH = "atlas_texture_mismatch"
    SKELETON_HEADER_INVALID = "skeleton_header_invalid"
    SPINE_VERSION_INCOMPATIBLE = "spine_version_incompatible"
    READ_FAILED = "external_asset_read_failed"


@dataclass(frozen=True, slots=True)
class ExternalFileIdentity:
    volume_id: int
    file_id: int
    size_bytes: int
    link_count: int
    modified_ticks: int


class ReadOnlyExternalAssetHandle(Protocol):
    @property
    def identity(self) -> ExternalFileIdentity:
        """Return the identity captured from the already-open handle."""

    def current_identity(self) -> ExternalFileIdentity:
        """Re-query identity from the same open handle."""

    def has_alternate_data_streams(self) -> bool:
        """Return whether named streams other than the default stream exist."""

    def read(self, size: int = -1) -> bytes:
        """Read from the already-open, non-inheritable handle."""

    def seek(self, offset: int) -> int:
        """Seek within the already-open handle."""

    def close(self) -> None:
        """Close idempotently."""


class ExternalAssetRootHandle(Protocol):
    def close(self) -> None:
        """Release the root directory handle idempotently."""


class ExternalPetAssetFilesystem(Protocol):
    def open_root(self, root: str) -> ExternalAssetRootHandle:
        """Open and validate an explicit root without following reparse points."""

    def open_file(
        self,
        root: ExternalAssetRootHandle,
        filename: str,
    ) -> ReadOnlyExternalAssetHandle:
        """Open one explicitly named direct child without scanning."""


class ExternalAssetFilesystemError(Exception):
    """Internal fixed-code exception; it never stores paths or OS text."""

    def __init__(self, status: ExternalPetAssetStatus) -> None:
        super().__init__(status.value)
        self.status = status


@dataclass(frozen=True, slots=True)
class PngAssetMetadata:
    width: int
    height: int
    bit_depth: int
    color_type: int
    interlace: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AtlasAssetMetadata:
    page_count: int
    page_filename: str = field(repr=False)
    page_width: int
    page_height: int
    pixel_format: str
    min_filter: str
    mag_filter: str
    repeat: str
    region_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SkeletonAssetMetadata:
    version: str
    major: int
    minor: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExternalPetAssetMetadata:
    texture: PngAssetMetadata
    atlas: AtlasAssetMetadata
    skeleton: SkeletonAssetMetadata
    total_size_bytes: int


@dataclass(frozen=True, slots=True, repr=False)
class ExternalPetAssetSnapshot:
    """Verified immutable asset bytes for in-memory Runtime construction."""

    skeleton_bytes: bytes
    atlas_bytes: bytes
    texture_bytes: bytes


class ExternalPetAssetBundle:
    """Own three verified read-only handles until a future renderer closes it."""

    def __init__(
        self,
        opaque_asset_id: str,
        root_handle: ExternalAssetRootHandle,
        skeleton_handle: ReadOnlyExternalAssetHandle,
        atlas_handle: ReadOnlyExternalAssetHandle,
        texture_handle: ReadOnlyExternalAssetHandle,
        metadata: ExternalPetAssetMetadata,
        snapshot: ExternalPetAssetSnapshot,
    ) -> None:
        self.opaque_asset_id = opaque_asset_id
        self._root_handle = root_handle
        self.skeleton_handle = skeleton_handle
        self.atlas_handle = atlas_handle
        self.texture_handle = texture_handle
        self.metadata = metadata
        self.snapshot = snapshot
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in (
            self.texture_handle,
            self.atlas_handle,
            self.skeleton_handle,
            self._root_handle,
        ):
            try:
                handle.close()
            except Exception:
                continue

    def __enter__(self) -> ExternalPetAssetBundle:
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.close()

    def __repr__(self) -> str:
        return (
            "ExternalPetAssetBundle("
            f"opaque_asset_id={self.opaque_asset_id!r}, "
            f"closed={self._closed!r})"
        )


@dataclass(frozen=True, slots=True)
class ExternalPetAssetLoadResult:
    status: ExternalPetAssetStatus
    bundle: ExternalPetAssetBundle | None = field(default=None, repr=False)

    @property
    def succeeded(self) -> bool:
        return self.status is ExternalPetAssetStatus.OK and self.bundle is not None

    @property
    def safe_message(self) -> str:
        if self.succeeded:
            return "External pet assets were validated safely."
        return "External pet assets could not be loaded safely."


@dataclass(frozen=True, slots=True)
class _ReadResult:
    data: bytes
    sha256: str
    size_bytes: int


class ExternalPetAssetLoader:
    """Open exactly three configured files and publish only an atomic bundle."""

    _CHUNK_BYTES = 64 * 1024
    _PNG_PREFIX_BYTES = 33
    _SKELETON_PREFIX_BYTES = 1024

    def __init__(self, filesystem: ExternalPetAssetFilesystem) -> None:
        self._filesystem = filesystem

    def load(
        self,
        descriptor: ExternalPetAssetDescriptor | None,
    ) -> ExternalPetAssetLoadResult:
        if descriptor is None:
            return ExternalPetAssetLoadResult(
                ExternalPetAssetStatus.NOT_CONFIGURED
            )
        config_status = validate_external_asset_descriptor(descriptor)
        if config_status is not ExternalAssetConfigStatus.VALID:
            return ExternalPetAssetLoadResult(
                self._configuration_error(config_status)
            )

        root: ExternalAssetRootHandle | None = None
        handles: list[ReadOnlyExternalAssetHandle] = []
        try:
            root = self._filesystem.open_root(descriptor.asset_root)
            skeleton = self._filesystem.open_file(
                root,
                descriptor.skeleton_filename,
            )
            handles.append(skeleton)
            atlas = self._filesystem.open_file(
                root,
                descriptor.atlas_filename,
            )
            handles.append(atlas)
            texture = self._filesystem.open_file(
                root,
                descriptor.texture_filename,
            )
            handles.append(texture)

            limits = descriptor.limits
            remaining_bundle_bytes = limits.bundle_max_bytes
            skeleton_read = self._read_verified(
                skeleton,
                min(limits.skeleton_max_bytes, remaining_bundle_bytes),
            )
            remaining_bundle_bytes -= skeleton_read.size_bytes
            atlas_read = self._read_verified(
                atlas,
                min(limits.atlas_max_bytes, remaining_bundle_bytes),
            )
            remaining_bundle_bytes -= atlas_read.size_bytes
            texture_read = self._read_verified(
                texture,
                min(limits.texture_max_bytes, remaining_bundle_bytes),
            )
            total_size = (
                skeleton_read.size_bytes
                + atlas_read.size_bytes
                + texture_read.size_bytes
            )
            if total_size > limits.bundle_max_bytes:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.TOO_LARGE
                )
            self._verify_expected_hashes(
                descriptor.expected_sha256,
                skeleton_read,
                atlas_read,
                texture_read,
            )
            texture_metadata = _parse_png_metadata(
                texture_read.data[: self._PNG_PREFIX_BYTES],
                texture_read.sha256,
            )
            atlas_metadata = _parse_atlas_metadata(
                atlas_read.data,
                atlas_read.sha256,
                descriptor.texture_filename,
            )
            if (
                atlas_metadata.page_width != texture_metadata.width
                or atlas_metadata.page_height != texture_metadata.height
            ):
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.ATLAS_TEXTURE_MISMATCH
            )
            skeleton_metadata = _parse_skeleton_metadata(
                skeleton_read.data[: self._SKELETON_PREFIX_BYTES],
                skeleton_read.sha256,
                descriptor.expected_spine_major,
                descriptor.expected_spine_minor,
            )
            snapshot = ExternalPetAssetSnapshot(
                skeleton_bytes=skeleton_read.data,
                atlas_bytes=atlas_read.data,
                texture_bytes=texture_read.data,
            )
            for handle in handles:
                handle.seek(0)
            bundle = ExternalPetAssetBundle(
                descriptor.opaque_asset_id,
                root,
                skeleton,
                atlas,
                texture,
                ExternalPetAssetMetadata(
                    texture=texture_metadata,
                    atlas=atlas_metadata,
                    skeleton=skeleton_metadata,
                    total_size_bytes=total_size,
                ),
                snapshot,
            )
            return ExternalPetAssetLoadResult(
                ExternalPetAssetStatus.OK,
                bundle,
            )
        except ExternalAssetFilesystemError as error:
            self._close_partial(handles, root)
            return ExternalPetAssetLoadResult(error.status)
        except Exception:
            self._close_partial(handles, root)
            return ExternalPetAssetLoadResult(
                ExternalPetAssetStatus.READ_FAILED
            )

    def _read_verified(
        self,
        handle: ReadOnlyExternalAssetHandle,
        maximum_bytes: int,
    ) -> _ReadResult:
        initial = handle.identity
        if initial.size_bytes > maximum_bytes:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.TOO_LARGE
            )
        if handle.has_alternate_data_streams():
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.NOT_REGULAR
            )
        handle.seek(0)
        digest = hashlib.sha256()
        data = bytearray()
        total = 0
        while True:
            block = handle.read(self._CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            if total > maximum_bytes:
                raise ExternalAssetFilesystemError(
                    ExternalPetAssetStatus.TOO_LARGE
                )
            digest.update(block)
            data.extend(block)
        final = handle.current_identity()
        if final != initial or total != initial.size_bytes:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.CHANGED_DURING_READ
            )
        return _ReadResult(bytes(data), digest.hexdigest(), total)

    @staticmethod
    def _verify_expected_hashes(
        expected: ExternalPetAssetHashes | None,
        skeleton: _ReadResult,
        atlas: _ReadResult,
        texture: _ReadResult,
    ) -> None:
        if expected is None:
            return
        pairs = (
            (expected.skeleton_sha256, skeleton.sha256),
            (expected.atlas_sha256, atlas.sha256),
            (expected.texture_sha256, texture.sha256),
        )
        if any(value is not None and value != actual for value, actual in pairs):
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.HASH_MISMATCH
            )

    @staticmethod
    def _configuration_error(
        status: ExternalAssetConfigStatus,
    ) -> ExternalPetAssetStatus:
        if status is ExternalAssetConfigStatus.INVALID_ROOT:
            return ExternalPetAssetStatus.ROOT_INVALID
        if status is ExternalAssetConfigStatus.INVALID_FILENAME:
            return ExternalPetAssetStatus.PATH_ESCAPE
        return ExternalPetAssetStatus.READ_FAILED

    @staticmethod
    def _close_partial(
        handles: list[ReadOnlyExternalAssetHandle],
        root: ExternalAssetRootHandle | None,
    ) -> None:
        for handle in reversed(handles):
            try:
                handle.close()
            except Exception:
                continue
        if root is not None:
            with suppress(Exception):
                root.close()


def _parse_png_metadata(data: bytes, sha256: str) -> PngAssetMetadata:
    if (
        len(data) < 33
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or int.from_bytes(data[8:12], "big") != 13
        or data[12:16] != b"IHDR"
    ):
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.TEXTURE_HEADER_INVALID
        )
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    bit_depth = data[24]
    color_type = data[25]
    compression = data[26]
    filter_method = data[27]
    interlace = data[28]
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if (
        width <= 0
        or height <= 0
        or color_type not in valid_depths
        or bit_depth not in valid_depths[color_type]
        or compression != 0
        or filter_method != 0
        or interlace not in {0, 1}
    ):
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.TEXTURE_HEADER_INVALID
        )
    return PngAssetMetadata(
        width,
        height,
        bit_depth,
        color_type,
        interlace,
        sha256,
    )


def _parse_atlas_metadata(
    data: bytes,
    sha256: str,
    expected_texture_filename: str,
) -> AtlasAssetMetadata:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        ) from error
    if "\0" in text:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    page_filename = lines[0].strip()
    if page_filename != expected_texture_filename:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_TEXTURE_MISMATCH
        )
    page_values: dict[str, str] = {}
    regions: list[dict[str, str]] = []
    current_region: dict[str, str] | None = None
    page_count = 1
    after_blank = False
    for raw_line in lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            after_blank = True
            current_region = None
            continue
        if ":" not in stripped:
            if after_blank:
                page_count += 1
                after_blank = False
                continue
            current_region = {}
            regions.append(current_region)
            continue
        key, value = (part.strip() for part in stripped.split(":", 1))
        target = page_values if current_region is None else current_region
        if not key or key in target:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.ATLAS_INVALID
            )
        target[key] = value
        after_blank = False
    if page_count != 1:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_TEXTURE_MISMATCH
        )
    page_width, page_height = _parse_pair(page_values.get("size"))
    pixel_format = page_values.get("format", "")
    filters = _parse_string_pair(page_values.get("filter"))
    repeat = page_values.get("repeat", "none")
    if (
        page_width <= 0
        or page_height <= 0
        or not pixel_format
        or repeat not in {"none", "x", "y", "xy"}
        or not regions
    ):
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    for region in regions:
        rotate = region.get("rotate", "false")
        if rotate not in {"false", "true", "0", "90", "180", "270"}:
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.ATLAS_INVALID
            )
        if "bounds" in region:
            x, y, width, height = _parse_quad(region["bounds"])
        else:
            x, y = _parse_pair(region.get("xy"))
            width, height = _parse_pair(region.get("size"))
        packed_width, packed_height = (
            (height, width) if rotate in {"true", "90"} else (width, height)
        )
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + packed_width > page_width
            or y + packed_height > page_height
        ):
            raise ExternalAssetFilesystemError(
                ExternalPetAssetStatus.ATLAS_INVALID
            )
    return AtlasAssetMetadata(
        page_count=page_count,
        page_filename=page_filename,
        page_width=page_width,
        page_height=page_height,
        pixel_format=pixel_format,
        min_filter=filters[0],
        mag_filter=filters[1],
        repeat=repeat,
        region_count=len(regions),
        sha256=sha256,
    )


def _parse_skeleton_metadata(
    data: bytes,
    sha256: str,
    expected_major: int,
    expected_minor: int,
) -> SkeletonAssetMetadata:
    try:
        _, offset = _read_binary_string(data, 0)
        version, offset = _read_binary_string(data, offset)
    except (UnicodeDecodeError, ValueError) as error:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.SKELETON_HEADER_INVALID
        ) from error
    if version is None or len(data) < offset + 16:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.SKELETON_HEADER_INVALID
        )
    match = re.match(r"^(\d+)\.(\d+)(?:\.\d+)?", version)
    if match is None:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.SKELETON_HEADER_INVALID
        )
    major = int(match.group(1))
    minor = int(match.group(2))
    if major != expected_major or minor != expected_minor:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.SPINE_VERSION_INCOMPATIBLE
        )
    return SkeletonAssetMetadata(version, major, minor, sha256)


def _read_binary_string(
    data: bytes,
    offset: int,
) -> tuple[str | None, int]:
    length, offset = _read_varint(data, offset)
    if length == 0:
        return None, offset
    byte_count = length - 1
    if byte_count > 256 or offset + byte_count > len(data):
        raise ValueError
    value = data[offset : offset + byte_count].decode("utf-8")
    return value, offset + byte_count


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    for shift in range(0, 35, 7):
        if offset >= len(data):
            raise ValueError
        value = data[offset]
        offset += 1
        result |= (value & 0x7F) << shift
        if value & 0x80 == 0:
            return result, offset
    raise ValueError


def _parse_pair(value: str | None) -> tuple[int, int]:
    parts = _parse_integer_parts(value, 2)
    return parts[0], parts[1]


def _parse_quad(value: str | None) -> tuple[int, int, int, int]:
    parts = _parse_integer_parts(value, 4)
    return parts[0], parts[1], parts[2], parts[3]


def _parse_integer_parts(value: str | None, count: int) -> tuple[int, ...]:
    if value is None:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    parts = tuple(part.strip() for part in value.split(","))
    if len(parts) != count:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    try:
        return tuple(int(part) for part in parts)
    except ValueError as error:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        ) from error


def _parse_string_pair(value: str | None) -> tuple[str, str]:
    if value is None:
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    parts = tuple(part.strip() for part in value.split(","))
    if len(parts) != 2 or not all(parts):
        raise ExternalAssetFilesystemError(
            ExternalPetAssetStatus.ATLAS_INVALID
        )
    return parts[0], parts[1]
