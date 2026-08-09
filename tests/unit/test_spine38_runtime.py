from __future__ import annotations

import importlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _write_valid_build_manifest(directory: Path) -> None:
    (directory / "spine38-build-manifest.json").write_text(
        json.dumps(
            {
                "commit": "8b4844bd4b193ba9e54487ed397a777993cbad56",
                "configuration": "Release",
                "architecture": "x64",
                "bridge_abi": 1,
            }
        ),
        encoding="utf-8",
    )


def test_exact_relax_candidate_is_required() -> None:
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")
    catalog = runtime.Spine38Catalog(
        (runtime.Spine38AnimationInfo("Relax", 3.2),)
    )

    assert catalog.require_animation("Relax").duration_seconds == 3.2
    with pytest.raises(runtime.Spine38CatalogError):
        catalog.require_animation("relax")


def test_catalog_never_selects_by_similarity() -> None:
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")
    catalog = runtime.Spine38Catalog(
        (runtime.Spine38AnimationInfo("Relax_A", 3.2),)
    )

    with pytest.raises(runtime.Spine38CatalogError):
        catalog.require_animation("Relax")


def test_catalog_rejects_duplicate_exact_names_instead_of_guessing() -> None:
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")
    catalog = runtime.Spine38Catalog(
        (
            runtime.Spine38AnimationInfo("Relax", 3.2),
            runtime.Spine38AnimationInfo("Relax", 4.1),
        )
    )

    with pytest.raises(runtime.Spine38CatalogError):
        catalog.require_animation("Relax")


def test_runtime_snapshots_catalog_and_closes_owned_port_once() -> None:
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    class FakePort:
        def __init__(self) -> None:
            self.close_count = 0

        def catalog(self) -> tuple[Any, ...]:
            return (native.Spine38AnimationInfo("Relax", 3.2),)

        def skins(self) -> tuple[str, ...]:
            return ("default",)

        def setup_bounds(self) -> Any:
            return native.Spine38Bounds(-2.0, 3.0, 4.0, 5.0)

        def close(self) -> None:
            self.close_count += 1

    port = FakePort()
    adapter = runtime.Spine38Runtime(port)

    assert adapter.catalog.require_animation("Relax").duration_seconds == 3.2
    assert adapter.skins == ("default",)
    assert adapter.setup_bounds == runtime.Spine38Bounds(-2.0, 3.0, 4.0, 5.0)
    with pytest.raises(FrozenInstanceError):
        adapter.catalog.animations[0].name = "changed"

    adapter.close()
    adapter.close()

    assert port.close_count == 1


def test_runtime_closes_owned_port_when_catalog_snapshot_fails() -> None:
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")

    class FailingPort:
        def __init__(self) -> None:
            self.close_count = 0

        def catalog(self) -> tuple[Any, ...]:
            raise RuntimeError("sensitive-native-detail")

        def skins(self) -> tuple[str, ...]:
            raise AssertionError("unreachable")

        def setup_bounds(self) -> Any:
            raise AssertionError("unreachable")

        def close(self) -> None:
            self.close_count += 1

    port = FailingPort()

    with pytest.raises(RuntimeError):
        runtime.Spine38Runtime(port)

    assert port.close_count == 1


def test_list_only_loads_assets_before_dll_and_closes_in_reverse_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")
    bridge_dll = tmp_path / "bridge.dll"
    bridge_dll.write_bytes(b"fixture")
    _write_valid_build_manifest(tmp_path)
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    evidence_path = tmp_path / "catalog.json"
    calls: list[str] = []

    metadata = SimpleNamespace(
        skeleton=SimpleNamespace(
            version="3.8.99",
            major=3,
            minor=8,
            sha256=script._SKELETON_SHA256,
        ),
        atlas=SimpleNamespace(
            sha256=script._ATLAS_SHA256,
            page_count=1,
            page_width=1024,
            page_height=1024,
            pixel_format="RGBA8888",
            min_filter="Linear",
            mag_filter="Linear",
            repeat="none",
            region_count=7,
        ),
        texture=SimpleNamespace(
            sha256=script._TEXTURE_SHA256,
            width=1024,
            height=1024,
            bit_depth=8,
            color_type=6,
            interlace=0,
        ),
        total_size_bytes=123,
    )

    class FakeBundle:
        snapshot = object()
        closed = False

        def __init__(self) -> None:
            self.metadata = metadata

        def close(self) -> None:
            calls.append("bundle.close")
            self.closed = True

    bundle = FakeBundle()

    class FakeLoader:
        def __init__(self, filesystem: object) -> None:
            del filesystem

        def load(self, descriptor: Any) -> object:
            assert descriptor.asset_root == str(asset_root.resolve())
            calls.append("assets.load")
            return SimpleNamespace(succeeded=True, bundle=bundle)

    class FakePort:
        def catalog(self) -> tuple[Any, ...]:
            return (SimpleNamespace(name="Relax", duration_seconds=3.2),)

        def skins(self) -> tuple[str, ...]:
            return ("default",)

        def setup_bounds(self) -> object:
            return SimpleNamespace(x=-2.0, y=3.0, width=4.0, height=5.0)

        def close(self) -> None:
            calls.append("native.close")

    class FakeLibrary:
        @classmethod
        def from_dll_path(cls, path: Path) -> FakeLibrary:
            assert path == bridge_dll.resolve()
            calls.append("dll.load")
            return cls()

        def create(self, snapshot: object) -> FakePort:
            assert snapshot is bundle.snapshot
            calls.append("native.create")
            return FakePort()

    monkeypatch.setattr(script, "ExternalPetAssetLoader", FakeLoader)
    monkeypatch.setattr(script, "WindowsExternalPetAssetFilesystem", object)
    monkeypatch.setattr(script, "Spine38NativeLibrary", FakeLibrary)
    monkeypatch.setattr(script, "Spine38Runtime", runtime.Spine38Runtime)
    monkeypatch.setattr(script, "_EVIDENCE_PATH", evidence_path)

    exit_code = script.main(
        [
            "--list-only",
            "--bridge-dll",
            str(bridge_dll),
            "--asset-root",
            str(asset_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == '{"status":"spine38_catalog_confirmed"}\n'
    assert captured.err == ""
    assert calls == [
        "assets.load",
        "dll.load",
        "native.create",
        "native.close",
        "bundle.close",
    ]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["catalog"]["animations"] == [
        {"duration_seconds": 3.2, "name": "Relax"}
    ]
    assert evidence["runtime"]["source_commit"] == script._RUNTIME_COMMIT
    assert evidence["runtime"]["configuration"] == "Release"
    assert evidence["runtime"]["architecture"] == "x64"
    assert evidence["runtime"]["bridge_abi"] == 1


@pytest.mark.parametrize(
    "manifest_case",
    [
        "missing",
        "malformed",
        "duplicate",
        "commit",
        "configuration",
        "architecture",
        "bridge_abi",
        "extra_field",
    ],
)
def test_list_only_rejects_invalid_adjacent_build_manifest_before_loading(
    manifest_case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    bridge_dll = tmp_path / "private-bridge-name.dll"
    bridge_dll.write_bytes(b"fixture")
    asset_root = tmp_path / "private-asset-root"
    asset_root.mkdir()
    evidence_path = tmp_path / "evidence.json"
    manifest_path = tmp_path / "spine38-build-manifest.json"
    manifest = {
        "commit": "8b4844bd4b193ba9e54487ed397a777993cbad56",
        "configuration": "Release",
        "architecture": "x64",
        "bridge_abi": 1,
    }
    if manifest_case == "malformed":
        manifest_path.write_text("{", encoding="utf-8")
    elif manifest_case == "duplicate":
        manifest_path.write_text(
            '{"commit":"8b4844bd4b193ba9e54487ed397a777993cbad56",'
            '"commit":"8b4844bd4b193ba9e54487ed397a777993cbad56",'
            '"configuration":"Release","architecture":"x64",'
            '"bridge_abi":1}',
            encoding="utf-8",
        )
    elif manifest_case != "missing":
        if manifest_case == "commit":
            manifest["commit"] = "0" * 40
        elif manifest_case == "configuration":
            manifest["configuration"] = "Debug"
        elif manifest_case == "architecture":
            manifest["architecture"] = "Win32"
        elif manifest_case == "bridge_abi":
            manifest["bridge_abi"] = True
        elif manifest_case == "extra_field":
            manifest["unexpected"] = "value"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class ForbiddenLoader:
        def __init__(self, filesystem: object) -> None:
            del filesystem
            raise AssertionError("assets must not load")

    class ForbiddenLibrary:
        @classmethod
        def from_dll_path(cls, path: Path) -> None:
            del path
            raise AssertionError("DLL must not load")

    monkeypatch.setattr(script, "ExternalPetAssetLoader", ForbiddenLoader)
    monkeypatch.setattr(script, "Spine38NativeLibrary", ForbiddenLibrary)
    monkeypatch.setattr(script, "_EVIDENCE_PATH", evidence_path)

    exit_code = script.main(
        [
            "--list-only",
            "--bridge-dll",
            str(bridge_dll),
            "--asset-root",
            str(asset_root),
        ]
    )

    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == '{"status":"spine38_build_manifest_invalid"}\n'
    assert not evidence_path.exists()
    assert "private-bridge-name" not in rendered
    assert "private-asset-root" not in rendered


def test_list_only_asset_failure_never_loads_the_dll_or_leaks_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")
    bridge_dll = tmp_path / "private-bridge-name.dll"
    bridge_dll.write_bytes(b"fixture")
    _write_valid_build_manifest(tmp_path)
    asset_root = tmp_path / "private-asset-root"
    asset_root.mkdir()

    class FakeLoader:
        def __init__(self, filesystem: object) -> None:
            del filesystem

        def load(self, descriptor: object) -> object:
            del descriptor
            return SimpleNamespace(
                succeeded=False,
                bundle=None,
                status=SimpleNamespace(value="external_asset_hash_mismatch"),
            )

    class ForbiddenLibrary:
        @classmethod
        def from_dll_path(cls, path: Path) -> None:
            del path
            raise AssertionError("DLL must not load after asset failure")

    monkeypatch.setattr(script, "ExternalPetAssetLoader", FakeLoader)
    monkeypatch.setattr(script, "WindowsExternalPetAssetFilesystem", object)
    monkeypatch.setattr(script, "Spine38NativeLibrary", ForbiddenLibrary)

    exit_code = script.main(
        [
            "--list-only",
            "--bridge-dll",
            str(bridge_dll),
            "--asset-root",
            str(asset_root),
        ]
    )

    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == '{"status":"external_asset_hash_mismatch"}\n'
    assert "private-bridge-name" not in rendered
    assert "private-asset-root" not in rendered


def test_list_only_missing_arguments_use_fixed_content_free_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = importlib.import_module("scripts.qt_spine38_vertical_slice")

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == '{"status":"spine38_arguments_invalid"}\n'


def test_direct_cli_uses_worktree_source_and_emits_fixed_error() -> None:
    project_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "qt_spine38_vertical_slice.py"),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == '{"status":"spine38_arguments_invalid"}\n'
