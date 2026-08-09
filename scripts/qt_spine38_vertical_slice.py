"""Local-only Spine 3.8 vertical-slice diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn, TextIO, cast

if __package__ in {None, ""}:
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[1] / "src"),
    )

from sjtuclaw.application.pet_external_assets import (
    ExternalPetAssetLoader,
    ExternalPetAssetStatus,
)
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
_SMOKE_EVIDENCE_PATH = _EVIDENCE_PATH.with_name("schwarz-smoke.json")
_SMOKE_SAMPLE_TARGETS = (
    ("loop_1_start", 0.02),
    ("loop_1_mid", 0.5),
    ("loop_1_before_end", 0.98),
    ("loop_2_after_start", 1.02),
    ("loop_2_mid", 1.5),
    ("loop_2_before_end", 1.98),
    ("loop_3_after_start", 2.02),
    ("loop_3_mid", 2.5),
    ("loop_3_before_end", 2.98),
    ("loop_3_after_end", 3.02),
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
    list_only: bool
    bridge_dll: Path
    asset_root: Path
    animation: str | None
    loops: int | None


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
    parser.add_argument("--animation")
    parser.add_argument("--loops", type=int)
    parsed = parser.parse_args(argv)
    try:
        bridge_dll = Path(str(parsed.bridge_dll)).resolve(strict=True)
        asset_root = Path(str(parsed.asset_root)).resolve(strict=True)
    except (OSError, RuntimeError):
        raise _CliArgumentError from None
    if not bridge_dll.is_file() or not asset_root.is_dir():
        raise _CliArgumentError
    animation = cast(str | None, parsed.animation)
    loops = cast(int | None, parsed.loops)
    if (animation is None) != (loops is None):
        raise _CliArgumentError
    if animation is not None and (animation != "Relax" or loops != 3):
        raise _CliArgumentError
    return _Arguments(
        bool(parsed.list_only),
        bridge_dll,
        asset_root,
        animation,
        loops,
    )


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


def _emit_json(value: dict[str, Any], stream: TextIO) -> None:
    stream.write(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _forced_hash_failure_evidence(asset_root: Path) -> dict[str, Any]:
    from sjtuclaw.application.pet_geometry import Size
    from sjtuclaw.presentation.qt.pet_renderer import (
        PetRendererSafeCode,
        PlaceholderPetRenderer,
        SafePetRenderer,
    )

    descriptor = _descriptor(asset_root)
    wrong_descriptor = replace(
        descriptor,
        expected_sha256=ExternalPetAssetHashes(
            skeleton_sha256="0" * 64,
            atlas_sha256=_ATLAS_SHA256,
            texture_sha256=_TEXTURE_SHA256,
        ),
    )
    loaded = ExternalPetAssetLoader(
        WindowsExternalPetAssetFilesystem()
    ).load(wrong_descriptor)
    if loaded.bundle is not None:
        loaded.bundle.close()
        raise RuntimeError
    if loaded.status is not ExternalPetAssetStatus.HASH_MISMATCH:
        raise RuntimeError
    fallback = SafePetRenderer(
        PlaceholderPetRenderer(),
        initial_safe_code=PetRendererSafeCode.CONSTRUCTION_FAILED,
    )
    fallback.initialize(Size(160, 180))
    evidence = {
        "bridge_constructed": False,
        "loader_status": loaded.status.value,
        "renderer_safe_code": fallback.safe_code.value,
        "using_placeholder": fallback.using_placeholder,
    }
    fallback.close()
    return evidence


def _alpha_bounds(image: Any) -> dict[str, int]:
    from PySide6.QtGui import QImage

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    bytes_per_line = converted.bytesPerLine()
    rgba = bytes(converted.constBits()[: converted.sizeInBytes()])
    minimum_x = width
    minimum_y = height
    maximum_x = -1
    maximum_y = -1
    nonzero_pixels = 0
    for y in range(height):
        row = y * bytes_per_line
        for x in range(width):
            if rgba[row + x * 4 + 3] == 0:
                continue
            nonzero_pixels += 1
            minimum_x = min(minimum_x, x)
            minimum_y = min(minimum_y, y)
            maximum_x = max(maximum_x, x)
            maximum_y = max(maximum_y, y)
    if nonzero_pixels == 0:
        raise RuntimeError
    return {
        "x": minimum_x,
        "y": minimum_y,
        "width": maximum_x - minimum_x + 1,
        "height": maximum_y - minimum_y + 1,
        "nonzero_pixels": nonzero_pixels,
    }


def _vertex_checksum(runtime: Spine38Runtime) -> str:
    digest = hashlib.sha256()
    vertex_count = 0
    for command in runtime.draw_commands()[:8]:
        digest.update(struct.pack("<ii", command.draw_order, command.texture_page))
        for vertex in command.vertices[:8]:
            digest.update(
                struct.pack(
                    "<ffffBBBB",
                    vertex.x,
                    vertex.y,
                    vertex.u,
                    vertex.v,
                    vertex.r,
                    vertex.g,
                    vertex.b,
                    vertex.a,
                )
            )
            vertex_count += 1
    if vertex_count == 0:
        raise RuntimeError
    return digest.hexdigest()[:16]


def _smoke_sample(
    window: Any,
    runtime: Spine38Runtime,
    *,
    label: str,
    target_seconds: float,
    started_at: float,
) -> dict[str, Any]:
    from PySide6.QtGui import QImage

    image = QImage(160, 180, QImage.Format.Format_RGBA8888)
    image.fill(0)
    window.render(image)
    return {
        "label": label,
        "target_elapsed_seconds": round(target_seconds, 6),
        "observed_elapsed_seconds": round(
            time.perf_counter() - started_at,
            6,
        ),
        "alpha_bounds": _alpha_bounds(image),
        "vertex_checksum": _vertex_checksum(runtime),
    }


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


def _run_three_loop_smoke(
    arguments: _Arguments,
    manifest: _BuildManifest,
) -> tuple[int, str, dict[str, Any] | None]:
    del manifest
    bundle = None
    native_port = None
    runtime = None
    safe_renderer = None
    exit_code = 1
    status = "spine38_runtime_failure"
    evidence: dict[str, Any] | None = None
    try:
        if arguments.animation != "Relax" or arguments.loops != 3:
            raise RuntimeError
        forced_hash_failure = _forced_hash_failure_evidence(
            arguments.asset_root
        )
        loaded = ExternalPetAssetLoader(
            WindowsExternalPetAssetFilesystem()
        ).load(_descriptor(arguments.asset_root))
        if not loaded.succeeded or loaded.bundle is None:
            status = loaded.status.value
        else:
            bundle = loaded.bundle
            native_port = Spine38NativeLibrary.from_dll_path(
                arguments.bridge_dll
            ).create(bundle.snapshot)

            from PySide6.QtCore import Qt, QTimer
            from PySide6.QtWidgets import QApplication

            from sjtuclaw.application.pet_geometry import Size
            from sjtuclaw.presentation.qt.pet_renderer import (
                PetRendererSafeCode,
                SafePetRenderer,
            )
            from sjtuclaw.presentation.qt.pet_window import PetWindow
            from sjtuclaw.presentation.qt.spine38_renderer import (
                Spine38PetRenderer,
            )

            runtime = Spine38Runtime(
                native_port,
                atlas_size=Size(
                    bundle.metadata.atlas.page_width,
                    bundle.metadata.atlas.page_height,
                ),
            )
            native_port = None
            animation = runtime.catalog.require_animation(arguments.animation)
            duration_seconds = animation.duration_seconds
            runtime_probe = runtime
            renderer = Spine38PetRenderer(
                runtime,
                bundle.snapshot.texture_bytes,
                asset_owner=bundle,
            )
            runtime = None
            bundle = None
            safe_renderer = SafePetRenderer(renderer)
            existing = QApplication.instance()
            application = (
                existing
                if isinstance(existing, QApplication)
                else QApplication([])
            )
            application.setApplicationName(
                "SJTUClaw Spine 3.8 Vertical Slice"
            )
            window = PetWindow(renderer=safe_renderer)
            window.safe_exit_requested.connect(application.quit)
            window.show()
            application.processEvents()
            window_transparent = window.testAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground
            )
            window_count = sum(
                isinstance(widget, PetWindow)
                for widget in QApplication.topLevelWidgets()
            )
            samples: list[dict[str, Any]] = []
            sample_failed = False
            started_at = time.perf_counter()

            def collect_sample(
                label: str,
                target_multiple: float,
                final: bool,
            ) -> None:
                nonlocal sample_failed
                target_seconds = target_multiple * duration_seconds
                try:
                    samples.append(
                        _smoke_sample(
                            window,
                            runtime_probe,
                            label=label,
                            target_seconds=target_seconds,
                            started_at=started_at,
                        )
                    )
                except Exception:
                    sample_failed = True
                if final:
                    application.quit()

            for index, (label, target_multiple) in enumerate(
                _SMOKE_SAMPLE_TARGETS
            ):
                final = index == len(_SMOKE_SAMPLE_TARGETS) - 1
                delay_milliseconds = max(
                    1,
                    round(target_multiple * duration_seconds * 1000.0),
                )
                QTimer.singleShot(
                    delay_milliseconds,
                    lambda label=label,
                    target_multiple=target_multiple,
                    final=final: collect_sample(
                        label,
                        target_multiple,
                        final,
                    ),
                )
            application_exit_code = application.exec()
            observed_duration = time.perf_counter() - started_at
            if (
                safe_renderer.using_placeholder
                or safe_renderer.safe_code is not PetRendererSafeCode.NONE
            ):
                status = "spine38_renderer_fallback"
            elif (
                application_exit_code != 0
                or sample_failed
                or len(samples) != len(_SMOKE_SAMPLE_TARGETS)
                or observed_duration < arguments.loops * duration_seconds
            ):
                status = "spine38_runtime_failure"
            else:
                status = "visual_review_required"
                exit_code = 0
                evidence = {
                    "schema_version": 1,
                    "status": status,
                    "animation": arguments.animation,
                    "loops_requested": arguments.loops,
                    "duration_seconds": duration_seconds,
                    "completed_elapsed_seconds": round(
                        observed_duration,
                        6,
                    ),
                    "window_count": window_count,
                    "window_transparent": window_transparent,
                    "renderer_safe_code": safe_renderer.safe_code.value,
                    "sampled_nontransparent_frames": len(samples),
                    "samples": samples,
                    "forced_hash_failure": forced_hash_failure,
                    "agent_modules_imported": (
                        "sjtuclaw.application.agent_loop" in sys.modules
                    ),
                    "visual_review_required": True,
                }
    except Spine38CatalogError:
        exit_code = 3
        status = "spine38_relax_unconfirmed"
    except Spine38NativeError:
        status = "spine38_native_failure"
    except Exception:
        status = "spine38_runtime_failure"
    finally:
        cleanup_failed = False
        for resource in (
            safe_renderer,
            runtime,
            native_port,
            bundle,
        ):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    cleanup_failed = True
        if (
            safe_renderer is not None
            and safe_renderer.safe_code is PetRendererSafeCode.CLOSE_FAILED
        ):
            cleanup_failed = True
        if cleanup_failed:
            exit_code = 1
            status = "spine38_cleanup_failed"
            evidence = None
    if exit_code == 0 and evidence is not None:
        try:
            _write_atomic_json(_SMOKE_EVIDENCE_PATH, evidence)
        except OSError:
            return 1, "spine38_evidence_write_failed", None
    return exit_code, status, evidence


def _run_visible(
    arguments: _Arguments,
    manifest: _BuildManifest,
) -> tuple[int, str]:
    del manifest
    bundle = None
    native_port = None
    runtime = None
    safe_renderer = None
    exit_code = 1
    status = "spine38_runtime_failure"
    try:
        loaded = ExternalPetAssetLoader(
            WindowsExternalPetAssetFilesystem()
        ).load(_descriptor(arguments.asset_root))
        if not loaded.succeeded or loaded.bundle is None:
            status = loaded.status.value
        else:
            bundle = loaded.bundle
            native_port = Spine38NativeLibrary.from_dll_path(
                arguments.bridge_dll
            ).create(bundle.snapshot)

            from PySide6.QtWidgets import QApplication

            from sjtuclaw.application.pet_geometry import Size
            from sjtuclaw.presentation.qt.pet_renderer import (
                PetRendererSafeCode,
                SafePetRenderer,
            )
            from sjtuclaw.presentation.qt.pet_window import PetWindow
            from sjtuclaw.presentation.qt.spine38_renderer import (
                Spine38PetRenderer,
            )

            runtime = Spine38Runtime(
                native_port,
                atlas_size=Size(
                    bundle.metadata.atlas.page_width,
                    bundle.metadata.atlas.page_height,
                ),
            )
            native_port = None
            runtime.catalog.require_animation("Relax")
            renderer = Spine38PetRenderer(
                runtime,
                bundle.snapshot.texture_bytes,
                asset_owner=bundle,
            )
            runtime = None
            bundle = None
            safe_renderer = SafePetRenderer(renderer)
            existing = QApplication.instance()
            application = (
                existing
                if isinstance(existing, QApplication)
                else QApplication([])
            )
            application.setApplicationName(
                "SJTUClaw Spine 3.8 Vertical Slice"
            )
            window = PetWindow(renderer=safe_renderer)
            window.safe_exit_requested.connect(application.quit)
            window.show()
            application_exit_code = application.exec()
            if safe_renderer.using_placeholder:
                status = "spine38_renderer_fallback"
            elif application_exit_code != 0:
                status = "spine38_runtime_failure"
            else:
                exit_code = 0
                status = "spine38_visible_complete"
    except Spine38CatalogError:
        exit_code = 3
        status = "spine38_relax_unconfirmed"
    except Spine38NativeError:
        status = "spine38_native_failure"
    except Exception:
        status = "spine38_runtime_failure"
    finally:
        cleanup_failed = False
        for resource in (
            safe_renderer,
            runtime,
            native_port,
            bundle,
        ):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    cleanup_failed = True
        if (
            safe_renderer is not None
            and safe_renderer.safe_code is PetRendererSafeCode.CLOSE_FAILED
        ):
            cleanup_failed = True
        if cleanup_failed:
            exit_code = 1
            status = "spine38_cleanup_failed"
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
    if arguments.list_only:
        exit_code, status = _run_list_only(arguments, manifest)
        evidence = None
    elif arguments.animation is not None:
        exit_code, status, evidence = _run_three_loop_smoke(
            arguments,
            manifest,
        )
    else:
        exit_code, status = _run_visible(arguments, manifest)
        evidence = None
    stream = sys.stdout if exit_code == 0 else sys.stderr
    if evidence is None:
        _emit_status(status, stream)
    else:
        _emit_json(evidence, stream)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
