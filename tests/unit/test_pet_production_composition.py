from __future__ import annotations

import json
from pathlib import Path

import pytest

from sjtuclaw.application.pet_production_actions import ProductionAction
from sjtuclaw.application.pet_role_pack import AnimationRoleRegistry
from sjtuclaw.bootstrap.pet_production import (
    create_optional_production_pet_composition,
    load_role_pack_manifest,
)


def _manifest_value() -> dict[str, object]:
    return {
        "schema_version": 1,
        "pack_id": "schwarz-production",
        "spine_version": "3.8",
        "assets": {
            "skeleton": r"D:\ArkModels\Schwarz\character.skel",
            "atlas": r"D:\ArkModels\Schwarz\character.atlas",
            "texture": r"D:\ArkModels\Schwarz\character.png",
        },
        "expected_sha256": {
            "skeleton": "a" * 64,
            "atlas": "b" * 64,
            "texture": "c" * 64,
        },
        "animations": {
            "relax": "Relax",
            "move": "Move",
            "sit": "Sit",
            "sleep": "Sleep",
            "special": "Special",
            "interact": "Interact",
        },
        "direction_policy": "mirror_move",
        "framing": {
            "scale": 1.0,
            "x_offset": 0.0,
            "foot_baseline": 176.0,
        },
        "texture_page_count": 1,
    }


def test_manifest_json_builds_complete_data_driven_role_pack(tmp_path: Path) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")

    manifest = load_role_pack_manifest(manifest_path)
    roles = AnimationRoleRegistry.from_manifest(manifest)

    assert manifest.pack_id == "schwarz-production"
    assert roles.capabilities == frozenset(ProductionAction)
    assert roles.resolve(ProductionAction.MOVE_LEFT).physical_name == "Move"
    assert roles.resolve(ProductionAction.MOVE_LEFT).mirrored


def test_invalid_manifest_has_one_stable_public_failure(tmp_path: Path) -> None:
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        load_role_pack_manifest(manifest_path)

    assert str(caught.value) == "role_pack_manifest_invalid"


def test_unconfigured_production_composition_preserves_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SJTUCLAW_PET_ROLE_MANIFEST", raising=False)
    monkeypatch.delenv("SJTUCLAW_SPINE38_BRIDGE_DLL", raising=False)

    assert create_optional_production_pet_composition() is None
