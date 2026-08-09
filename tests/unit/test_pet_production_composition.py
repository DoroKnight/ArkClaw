from __future__ import annotations

import json
from pathlib import Path

import pytest

from sjtuclaw.application.pet_production_actions import ProductionAction
from sjtuclaw.application.pet_role_pack import AnimationRoleRegistry
from sjtuclaw.application.spine38_runtime import Spine38Bounds
from sjtuclaw.bootstrap.pet_production import (
    _sample_session_bounds,
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


class _BoundsRuntime:
    def __init__(self) -> None:
        self.animation_names: list[str] = []
        self._index = 0

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        assert track == 0
        assert loop
        self.animation_names.append(name)
        self._index = len(self.animation_names) - 1

    def update(self, delta_seconds: float) -> tuple[()]:
        assert delta_seconds >= 0.0
        return ()

    def visible_bounds(self) -> Spine38Bounds:
        offset = float(self._index)
        return Spine38Bounds(-offset, -offset, 2.0 + offset, 3.0 + offset)


def test_session_framing_samples_each_of_six_physical_animations_once(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")
    roles = AnimationRoleRegistry.from_manifest(
        load_role_pack_manifest(manifest_path)
    )
    runtime = _BoundsRuntime()

    bounds = _sample_session_bounds(
        runtime,  # type: ignore[arg-type]
        roles,
        {action: 12.0 for action in ProductionAction},
    )

    assert runtime.animation_names == [
        "Relax",
        "Move",
        "Sit",
        "Sleep",
        "Special",
        "Interact",
    ]
    assert bounds == Spine38Bounds(-5.0, -5.0, 7.0, 8.0)
