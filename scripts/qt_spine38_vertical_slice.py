"""Local-only Spine 3.8 vertical-slice diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, TextIO

if __package__ in {None, ""}:
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[1] / "src"),
    )

from sjtuclaw.application.pet_external_assets import ExternalPetAssetLoader
from sjtuclaw.application.pet_renderer_model import (
    ExternalPetAssetDescriptor,
    ExternalPetAssetHashes,
)
from sjtuclaw.application.spine38_runtime import (
    Spine38CatalogError,
    Spine38Runtime,
)
from sjtuclaw.infrastructure.pet_external_asset_filesystem import (
    WindowsExternalPetAssetFilesystem,
)
from sjtuclaw.infrastructure.spine38_native import (
    Spine38NativeError,
    Spine38NativeLibrary,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ATLAS_FILENAME = "build_char_340_shwaz_striker#1.atlas"
_TEXTURE_FILENAME = "build_char_340_shwaz_striker#1.png"
_SKELETON_FILENAME = "build_char_340_shwaz_striker#1.skel"
_ATLAS_SHA256 = "6d42f85b5fd09f7bbd7f8df412437bfa3d48628cc42c0bfe9ae2ba0d7329a737"
_TEXTURE_SHA256 = "7d1654527310334ad658054acfbaF5e58c2a0719a5a1984662713306f656e2a5".lower()
_SKELETON_SHA256 = "4c7ff39d6322d702e11e7a769457d3e4d77b1a43037f8deedf7cd508937da451"
_RUNTIME_COMMIT = "8b4844bd4b193ba9e54487ed397a777993cbad56"
_BUILD_MANIFEST_FILENAME = "spine38-build-manifest.json"
_BUILD_MANIFEST_MAX_BYTES = 4096
_EVIDENCE_PATH = (
    _PROJECT_ROOT
    / "build"
    / "spine38"
    / "evidence"
    / "schwarz-catalog.json"
)


class _CliArgumentError(Exception):
    pass


class _BuildManifestError(Exception):
    pass


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise _CliArgumentError


@dataclass(frozen=True, slots=True)
class _Arguments:
    bridge_dll: Path
    asset_root: Path


@dataclass(frozen=True, slots=True)
class _BuildManifest:
    commit: str
    configuration: str
    architecture: str
    bridge_abi: int


def _parse_arguments(argv: Sequence[str] | None) -> _Arguments:
    parser = _SafeArgumentParser(add_help=False)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--bridge-dll", required=True)
    parser.add_argument("--asset-root", required=True)
    parsed = parser.parse_args(argv)
    if not parsed.list_only:
        raise _CliArgumentError
    try:
        bridge_dll = Path(str(parsed.bridge_dll)).resolve(strict=True)
        asset_root = Path(str(parsed.asset_root)).resolve(strict=True)
    except (OSError, RuntimeError):
        raise _CliArgumentError from None
    if not bridge_dll.is_file() or not asset_root.is_dir():
        raise _CliArgumentError
    return _Arguments(bridge_dll, asset_root)


def _manifest_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _BuildManifestError
        value[key] = item
    return value


def _load_build_manifest(bridge_dll: Path) -> _BuildManifest:
    path = bridge_dll.with_name(_BUILD_MANIFEST_FILENAME)
    try:
        with path.open("rb") as stream:
            raw = stream.read(_BUILD_MANIFEST_MAX_BYTES + 1)
        if not raw or len(raw) > _BUILD_MANIFEST_MAX_BYTES:
            raise _BuildManifestError
        decoded = raw.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=_manifest_object)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        _BuildManifestError,
    ):
        raise _BuildManifestError from None
    expected_keys = {
        "commit",
        "configuration",
        "architecture",
        "bridge_abi",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise _BuildManifestError
    commit = value["commit"]
    configuration = value["configuration"]
    architecture = value["architecture"]
    bridge_abi = value["bridge_abi"]
    if (
        type(commit) is not str
        or commit != _RUNTIME_COMMIT
        or type(configuration) is not str
        or configuration != "Release"
        or type(architecture) is not str
        or architecture != "x64"
        or type(bridge_abi) is not int
        or bridge_abi != 1
    ):
        raise _BuildManifestError
    return _BuildManifest(commit, configuration, architecture, bridge_abi)


def _descriptor(asset_root: Path) -> ExternalPetAssetDescriptor:
    return ExternalPetAssetDescriptor(
        opaque_asset_id="schwarz-original-spine38",
        asset_root=str(asset_root),
        skeleton_filename=_SKELETON_FILENAME,
        atlas_filename=_ATLAS_FILENAME,
        texture_filename=_TEXTURE_FILENAME,
        expected_spine_major=3,
        expected_spine_minor=8,
        expected_sha256=ExternalPetAssetHashes(
            skeleton_sha256=_SKELETON_SHA256,
            atlas_sha256=_ATLAS_SHA256,
            texture_sha256=_TEXTURE_SHA256,
        ),
    )


def _evidence(
    bundle: Any,
    runtime: Spine38Runtime,
    status: str,
    manifest: _BuildManifest,
) -> dict[str, Any]:
    metadata = bundle.metadata
    bounds = runtime.setup_bounds
    return {
        "schema_version": 1,
        "status": status,
        "approved_hashes": {
            "atlas_sha256": _ATLAS_SHA256,
            "skeleton_sha256": _SKELETON_SHA256,
            "texture_sha256": _TEXTURE_SHA256,
        },
        "assets": {
            "atlas": {
                "mag_filter": metadata.atlas.mag_filter,
                "min_filter": metadata.atlas.min_filter,
                "page_count": metadata.atlas.page_count,
                "page_height": metadata.atlas.page_height,
                "page_width": metadata.atlas.page_width,
                "pixel_format": metadata.atlas.pixel_format,
                "region_count": metadata.atlas.region_count,
                "repeat": metadata.atlas.repeat,
                "sha256": metadata.atlas.sha256,
            },
            "skeleton": {
                "major": metadata.skeleton.major,
                "minor": metadata.skeleton.minor,
                "sha256": metadata.skeleton.sha256,
                "version": metadata.skeleton.version,
            },
            "texture": {
                "bit_depth": metadata.texture.bit_depth,
                "color_type": metadata.texture.color_type,
                "height": metadata.texture.height,
                "interlace": metadata.texture.interlace,
                "sha256": metadata.texture.sha256,
                "width": metadata.texture.width,
            },
            "total_size_bytes": metadata.total_size_bytes,
        },
        "catalog": {
            "animations": [
                {
                    "duration_seconds": animation.duration_seconds,
                    "name": animation.name,
                }
                for animation in runtime.catalog.animations
            ],
            "setup_bounds": {
                "height": bounds.height,
                "width": bounds.width,
                "x": bounds.x,
                "y": bounds.y,
            },
            "skins": list(runtime.skins),
        },
        "runtime": {
            "data_version": "3.8",
            "source_commit": manifest.commit,
            "configuration": manifest.configuration,
            "architecture": manifest.architecture,
            "bridge_abi": manifest.bridge_abi,
        },
    }


def _write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _emit_status(status: str, stream: TextIO) -> None:
    stream.write(json.dumps({"status": status}, separators=(",", ":")) + "\n")


def _run_list_only(
    arguments: _Arguments,
    manifest: _BuildManifest,
) -> tuple[int, str]:
    bundle = None
    runtime = None
    exit_code = 1
    status = "spine38_runtime_failure"
    try:
        loaded = ExternalPetAssetLoader(
            WindowsExternalPetAssetFilesystem()
        ).load(_descriptor(arguments.asset_root))
        if not loaded.succeeded or loaded.bundle is None:
            return 1, loaded.status.value
        bundle = loaded.bundle
        native_port = Spine38NativeLibrary.from_dll_path(
            arguments.bridge_dll
        ).create(bundle.snapshot)
        runtime = Spine38Runtime(native_port)
        try:
            runtime.catalog.require_animation("Relax")
        except Spine38CatalogError:
            status = "spine38_relax_unconfirmed"
            exit_code = 3
        else:
            status = "spine38_catalog_confirmed"
            exit_code = 0
        _write_atomic_json(
            _EVIDENCE_PATH,
            _evidence(bundle, runtime, status, manifest),
        )
    except Spine38NativeError:
        status = "spine38_native_failure"
        exit_code = 1
    except OSError:
        status = "spine38_evidence_write_failed"
        exit_code = 1
    except Exception:
        status = "spine38_runtime_failure"
        exit_code = 1
    finally:
        cleanup_failed = False
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                cleanup_failed = True
        if bundle is not None:
            try:
                bundle.close()
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            status = "spine38_cleanup_failed"
            exit_code = 1
    return exit_code, status


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parse_arguments(argv)
    except _CliArgumentError:
        _emit_status("spine38_arguments_invalid", sys.stderr)
        return 2
    try:
        manifest = _load_build_manifest(arguments.bridge_dll)
    except _BuildManifestError:
        _emit_status("spine38_build_manifest_invalid", sys.stderr)
        return 1
    exit_code, status = _run_list_only(arguments, manifest)
    _emit_status(status, sys.stdout if exit_code == 0 else sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
