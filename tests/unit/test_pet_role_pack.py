from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from arkclaw.application.pet_production_actions import ProductionAction
from arkclaw.application.pet_role_pack import (
    AnimationRoleRegistry,
    MoveDirectionPolicy,
    RoleAnimationNames,
    RolePackFraming,
    RolePackHashes,
    RolePackManifest,
    RolePackManifestError,
    ValidatedRolePackIdentity,
)


def _manifest(tmp_path: Path) -> RolePackManifest:
    return RolePackManifest(
        schema_version=1,
        pack_id="schwarz-production",
        spine_version="3.8",
        manifest_path=(tmp_path / "role-pack.json").resolve(),
        skeleton_path=(tmp_path / "character.skel").resolve(),
        atlas_path=(tmp_path / "character.atlas").resolve(),
        texture_path=(tmp_path / "character.png").resolve(),
        expected_sha256=RolePackHashes("1" * 64, "2" * 64, "3" * 64),
        animations=RoleAnimationNames(
            relax="Relax",
            move="Move",
            sit="Sit",
            sleep="Sleep",
            special="Special",
            interact="Interact",
        ),
        direction_policy=MoveDirectionPolicy.MIRROR_MOVE,
        framing=RolePackFraming(scale=1.0, x_offset=0.0, foot_baseline=180.0),
        texture_page_count=1,
    )


def test_registry_maps_both_move_directions_to_one_physical_animation(
    tmp_path: Path,
) -> None:
    registry = AnimationRoleRegistry.from_manifest(_manifest(tmp_path))

    assert registry.resolve(ProductionAction.MOVE_LEFT).physical_name == "Move"
    assert registry.resolve(ProductionAction.MOVE_RIGHT).physical_name == "Move"
    assert registry.resolve(ProductionAction.MOVE_LEFT).mirrored is True
    assert registry.resolve(ProductionAction.MOVE_RIGHT).mirrored is False
    assert registry.capabilities == frozenset(ProductionAction)


def test_missing_optional_binding_is_disabled_not_substituted(tmp_path: Path) -> None:
    manifest = replace(
        _manifest(tmp_path),
        animations=replace(_manifest(tmp_path).animations, sleep=None),
    )
    registry = AnimationRoleRegistry.from_manifest(manifest)

    assert not registry.supports(ProductionAction.SLEEP)
    with pytest.raises(KeyError):
        registry.resolve(ProductionAction.SLEEP)
    assert registry.resolve(ProductionAction.RELAX).physical_name == "Relax"


def test_same_manifest_identity_uses_hashes_not_manifest_path(tmp_path: Path) -> None:
    first = _manifest(tmp_path)
    same_content_elsewhere = replace(
        first,
        manifest_path=(tmp_path / "renamed.json").resolve(),
        skeleton_path=(tmp_path / "copy.skel").resolve(),
        atlas_path=(tmp_path / "copy.atlas").resolve(),
        texture_path=(tmp_path / "copy.png").resolve(),
    )
    changed_same_path = replace(
        first,
        expected_sha256=replace(first.expected_sha256, texture="4" * 64),
    )

    assert ValidatedRolePackIdentity.from_manifest(first) == (
        ValidatedRolePackIdentity.from_manifest(same_content_elsewhere)
    )
    assert ValidatedRolePackIdentity.from_manifest(first) != (
        ValidatedRolePackIdentity.from_manifest(changed_same_path)
    )


@pytest.mark.parametrize(
    "change",
    (
        lambda manifest: replace(manifest, schema_version=2),
        lambda manifest: replace(manifest, spine_version="4.2"),
        lambda manifest: replace(manifest, texture_page_count=2),
        lambda manifest: replace(manifest, skeleton_path=Path("relative.skel")),
    ),
)
def test_manifest_rejects_unsupported_or_relative_inputs(
    tmp_path: Path,
    change: Callable[[RolePackManifest], RolePackManifest],
) -> None:
    with pytest.raises(RolePackManifestError):
        change(_manifest(tmp_path))


def test_schwarz_production_requires_all_six_physical_bindings(tmp_path: Path) -> None:
    manifest = replace(
        _manifest(tmp_path),
        animations=replace(_manifest(tmp_path).animations, interact=None),
    )

    with pytest.raises(RolePackManifestError, match="six animations"):
        AnimationRoleRegistry.from_manifest(manifest).require_schwarz_production()
