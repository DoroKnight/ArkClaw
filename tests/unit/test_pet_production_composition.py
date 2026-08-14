from __future__ import annotations

import json
from pathlib import Path

import pytest

from arkclaw.application.pet_production_actions import ProductionAction
from arkclaw.application.pet_renderer_model import PetRendererAction
from arkclaw.application.pet_role_calibration import RootMotionKind
from arkclaw.application.pet_role_pack import AnimationRoleRegistry
from arkclaw.application.spine38_runtime import Spine38Bounds, Spine38RootTransform
from arkclaw.bootstrap.pet_production import (
    _classify_root_motion,
    _sample_action_profile,
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
            "foot_baseline": 180.0,
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
    monkeypatch.delenv("ARKCLAW_PET_ROLE_MANIFEST", raising=False)
    monkeypatch.delenv("ARKCLAW_SPINE38_BRIDGE_DLL", raising=False)

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
        return Spine38Bounds(0.0, 0.0, 2.0, 3.0)


def test_session_framing_samples_all_roles_but_returns_relax_body_bounds(
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
    assert bounds == Spine38Bounds(0.0, 0.0, 2.0, 3.0)


class _BodyCalibrationRuntime:
    def __init__(self) -> None:
        self.current_animation = ""
        self.current_time = 0.0
        self.sample_times: dict[str, list[float]] = {}

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        assert track == 0
        assert loop
        self.current_animation = name
        self.current_time = 0.0
        self.sample_times[name] = []

    def update(self, delta_seconds: float) -> tuple[()]:
        self.current_time += delta_seconds
        return ()

    def visible_bounds(self) -> Spine38Bounds:
        self.sample_times[self.current_animation].append(self.current_time)
        if self.current_animation in {"Special", "Interact"}:
            return Spine38Bounds(-100.0, -50.0, 200.0, 100.0)
        return Spine38Bounds(-0.5, 0.0, 1.0, 2.0)


class _CroppedCoreRuntime(_BodyCalibrationRuntime):
    def visible_bounds(self) -> Spine38Bounds:
        self.sample_times[self.current_animation].append(self.current_time)
        if self.current_animation == "Move":
            return Spine38Bounds(100.0, 0.0, 20.0, 2.0)
        return Spine38Bounds(-0.5, 0.0, 1.0, 2.0)


def test_body_calibration_uses_fixed_uniform_samples_without_loop_endpoint(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")
    roles = AnimationRoleRegistry.from_manifest(
        load_role_pack_manifest(manifest_path)
    )
    runtime = _BodyCalibrationRuntime()
    durations = {
        action: {
            ProductionAction.RELAX: 12.0,
            ProductionAction.MOVE_LEFT: 24.0,
            ProductionAction.MOVE_RIGHT: 24.0,
            ProductionAction.SIT: 36.0,
            ProductionAction.SLEEP: 48.0,
            ProductionAction.SPECIAL: 60.0,
            ProductionAction.INTERACT: 72.0,
        }[action]
        for action in ProductionAction
    }

    bounds = _sample_session_bounds(
        runtime,  # type: ignore[arg-type]
        roles,
        durations,
    )

    assert bounds == Spine38Bounds(-0.5, 0.0, 1.0, 2.0)
    for name, duration in {
        "Relax": 12.0,
        "Move": 24.0,
        "Sit": 36.0,
        "Sleep": 48.0,
        "Special": 60.0,
        "Interact": 72.0,
    }.items():
        assert runtime.sample_times[name] == pytest.approx(
            [(index / 12.0) * duration for index in range(12)]
        )
        assert duration not in runtime.sample_times[name]


def test_body_priority_candidate_rejects_cropped_core_motion(tmp_path: Path) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")
    roles = AnimationRoleRegistry.from_manifest(
        load_role_pack_manifest(manifest_path)
    )

    with pytest.raises(ValueError, match="role_pack_body_priority_invalid"):
        _sample_session_bounds(
            _CroppedCoreRuntime(),  # type: ignore[arg-type]
            roles,
            {action: 12.0 for action in ProductionAction},
        )


class _ProfileRuntime:
    def __init__(self) -> None:
        self.current_animation = ""
        self.current_time = 0.0
        self.clear_calls: list[int] = []
        self.set_calls: list[tuple[str, bool]] = []
        self.sample_times: dict[str, list[float]] = {}

    def clear_track(self, track: int) -> None:
        assert track == 0
        self.clear_calls.append(track)
        self.current_animation = ""
        self.current_time = 0.0

    def set_animation(self, track: int, name: str, loop: bool) -> None:
        assert track == 0
        self.current_animation = name
        self.current_time = 0.0
        self.set_calls.append((name, loop))
        self.sample_times[name] = []

    def update(self, delta_seconds: float) -> tuple[()]:
        self.current_time += delta_seconds
        return ()

    def visible_bounds(self) -> Spine38Bounds:
        self.sample_times[self.current_animation].append(self.current_time)
        width = float(len(self.current_animation))
        return Spine38Bounds(0.0, 0.0, width, 2.0)


class _RootMotionRuntime(_ProfileRuntime):
    def root_transform(self) -> Spine38RootTransform:
        if self.current_animation == "Move":
            return Spine38RootTransform(self.current_time, 0.0)
        if self.current_animation == "Sit":
            return Spine38RootTransform(0.0, -2.0)
        return Spine38RootTransform(0.0, 0.0)


def test_root_motion_classification_precedes_grounding_profile(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")
    roles = AnimationRoleRegistry.from_manifest(load_role_pack_manifest(manifest_path))

    result = _classify_root_motion(
        _RootMotionRuntime(),  # type: ignore[arg-type]
        roles,
        {action: 0.1 for action in ProductionAction},
    )

    assert result.by_action[ProductionAction.RELAX] is RootMotionKind.STATIC_ROOT
    assert (
        result.by_action[ProductionAction.MOVE_LEFT]
        is RootMotionKind.TIME_VARYING_ROOT_MOTION
    )
    assert (
        result.by_action[ProductionAction.SIT]
        is RootMotionKind.CONSTANT_ACTION_OFFSET
    )


def test_action_profile_samples_non_loop_at_sixty_hz_with_terminal_pose(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")
    roles = AnimationRoleRegistry.from_manifest(load_role_pack_manifest(manifest_path))
    runtime = _ProfileRuntime()

    profile = _sample_action_profile(
        runtime,  # type: ignore[arg-type]
        roles,
        {action: 0.1 for action in ProductionAction},
        Spine38Bounds(-0.5, 0.0, 1.0, 2.0),
    )

    assert runtime.clear_calls == [0] * 6
    assert runtime.set_calls == [
        ("Relax", False),
        ("Move", False),
        ("Sit", False),
        ("Sleep", False),
        ("Special", False),
        ("Interact", False),
    ]
    assert runtime.sample_times["Relax"] == pytest.approx(
        [(index / 12.0) * 0.1 for index in range(13)]
    )
    assert profile.body_bounds == Spine38Bounds(-0.5, 0.0, 1.0, 2.0)
    assert profile.sampled_action_bounds[PetRendererAction.SPECIAL].width == 7.0
    assert (
        profile.sampled_action_bounds[PetRendererAction.WALK_LEFT]
        is profile.sampled_action_bounds[PetRendererAction.WALK_RIGHT]
    )


def test_action_profile_rejects_duration_and_allocation_contracts(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "schwarz.json"
    manifest_path.write_text(json.dumps(_manifest_value()), encoding="utf-8")
    roles = AnimationRoleRegistry.from_manifest(load_role_pack_manifest(manifest_path))

    with pytest.raises(ValueError, match="role_pack_animation_duration_invalid"):
        _sample_action_profile(
            _ProfileRuntime(),  # type: ignore[arg-type]
            roles,
            {action: 60.01 for action in ProductionAction},
            Spine38Bounds(-0.5, 0.0, 1.0, 2.0),
        )
