from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

_ATLAS_SHA256 = "6d42f85b5fd09f7bbd7f8df412437bfa3d48628cc42c0bfe9ae2ba0d7329a737"
_TEXTURE_SHA256 = "7d1654527310334ad658054acfbaF5e58c2a0719a5a1984662713306f656e2a5".lower()
_SKELETON_SHA256 = "4c7ff39d6322d702e11e7a769457d3e4d77b1a43037f8deedf7cd508937da451"
_EXPECTED_ANIMATIONS = {
    "Relax": 5.0,
    "Move": 2.666667,
    "Sit": 3.333333,
    "Sleep": 4.0,
    "Special": 11.533334,
    "Interact": 1.333333,
}


def test_real_schwarz_catalog_confirms_six_production_animations() -> None:
    bridge_value = os.environ.get("SJTUCLAW_SPINE38_BRIDGE_DLL")
    asset_root_value = os.environ.get("SJTUCLAW_SPINE38_ASSET_ROOT")
    if bridge_value is None or asset_root_value is None:
        pytest.skip(
            "requires SJTUCLAW_SPINE38_BRIDGE_DLL and "
            "SJTUCLAW_SPINE38_ASSET_ROOT"
        )

    assets = importlib.import_module("sjtuclaw.application.pet_external_assets")
    model = importlib.import_module("sjtuclaw.application.pet_renderer_model")
    runtime = importlib.import_module("sjtuclaw.application.spine38_runtime")
    filesystem = importlib.import_module(
        "sjtuclaw.infrastructure.pet_external_asset_filesystem"
    )
    native = importlib.import_module("sjtuclaw.infrastructure.spine38_native")

    bridge_path = Path(bridge_value)
    asset_root = Path(asset_root_value)
    if not bridge_path.is_absolute() or not bridge_path.is_file():
        pytest.fail("spine38_bridge_dll_invalid", pytrace=False)
    if not asset_root.is_absolute() or not asset_root.is_dir():
        pytest.fail("spine38_asset_root_invalid", pytrace=False)

    descriptor = model.ExternalPetAssetDescriptor(
        opaque_asset_id="schwarz-original-spine38",
        asset_root=str(asset_root),
        skeleton_filename="build_char_340_shwaz_striker#1.skel",
        atlas_filename="build_char_340_shwaz_striker#1.atlas",
        texture_filename="build_char_340_shwaz_striker#1.png",
        expected_spine_major=3,
        expected_spine_minor=8,
        expected_sha256=model.ExternalPetAssetHashes(
            skeleton_sha256=_SKELETON_SHA256,
            atlas_sha256=_ATLAS_SHA256,
            texture_sha256=_TEXTURE_SHA256,
        ),
    )
    result = assets.ExternalPetAssetLoader(
        filesystem.WindowsExternalPetAssetFilesystem()
    ).load(descriptor)
    if not result.succeeded or result.bundle is None:
        pytest.fail(result.status.value, pytrace=False)

    bundle = result.bundle
    adapter = None
    modules_before = set(sys.modules)
    try:
        native_port = native.Spine38NativeLibrary.from_dll_path(bridge_path).create(
            bundle.snapshot
        )
        filters = native_port.texture_page_info()
        adapter = runtime.Spine38Runtime(native_port)
        metadata = bundle.metadata
        assert metadata.skeleton.sha256 == _SKELETON_SHA256
        assert metadata.atlas.sha256 == _ATLAS_SHA256
        assert metadata.texture.sha256 == _TEXTURE_SHA256
        assert metadata.skeleton.version.startswith("3.8.")
        assert metadata.skeleton.major == 3
        assert metadata.skeleton.minor == 8
        assert adapter.skins
        observed = {
            animation.name: animation.duration_seconds
            for animation in adapter.catalog.animations
        }
        assert observed.keys() == _EXPECTED_ANIMATIONS.keys()
        for name, duration in _EXPECTED_ANIMATIONS.items():
            assert observed[name] == pytest.approx(duration, abs=0.00001)
        assert filters == native.Spine38TexturePageInfo(
            native.Spine38TextureFilter.LINEAR,
            native.Spine38TextureFilter.LINEAR,
        )
        newly_loaded = set(sys.modules) - modules_before
        assert not any(
            name.startswith(
                (
                    "sjtuclaw.agent",
                    "sjtuclaw.infrastructure.llm",
                    "openai",
                    "anthropic",
                )
            )
            for name in newly_loaded
        )
    finally:
        if adapter is not None:
            adapter.close()
        bundle.close()
