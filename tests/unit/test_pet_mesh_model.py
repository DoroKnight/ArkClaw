"""Tests for the deliberately small renderer-neutral mesh model."""

from __future__ import annotations

import pytest

from sjtuclaw.application.pet_mesh_model import (
    PetMeshDrawCommand,
    PetMeshPoint,
    PetMeshScene,
    PetMeshTextureData,
    PetMeshValidationCode,
    PetMeshValidationError,
    PetMeshVertex,
    sorted_draw_commands,
    validate_pet_mesh_scene,
)


def _texture(texture_id: str = "texture") -> PetMeshTextureData:
    return PetMeshTextureData(texture_id, 1, 1, bytes((255, 255, 255, 255)))


def _command(*, texture_id: str = "texture", draw_order: int = 0) -> PetMeshDrawCommand:
    return PetMeshDrawCommand(
        texture_id=texture_id,
        vertices=(
            PetMeshVertex(PetMeshPoint(0.0, 0.0), 0.0, 0.0),
            PetMeshVertex(PetMeshPoint(1.0, 0.0), 1.0, 0.0),
            PetMeshVertex(PetMeshPoint(0.0, 1.0), 0.0, 1.0),
        ),
        triangle_indices=(0, 1, 2),
        draw_order=draw_order,
    )


def _scene(*commands: PetMeshDrawCommand) -> PetMeshScene:
    return PetMeshScene(2, 2, 1.5, (_texture(),), commands or (_command(),))


def test_valid_scene_and_stable_draw_order() -> None:
    later = _command(draw_order=20)
    first_equal = _command(draw_order=10)
    second_equal = _command(draw_order=10)
    scene = _scene(later, first_equal, second_equal)

    validate_pet_mesh_scene(scene)

    assert sorted_draw_commands(scene) == (first_equal, second_equal, later)


@pytest.mark.parametrize(
    ("scene", "code"),
    [
        (
            PetMeshScene(0, 2, 1.0, (_texture(),), (_command(),)),
            PetMeshValidationCode.INVALID_VIEWPORT,
        ),
        (
            PetMeshScene(2, 2, 1.0, (_texture(),), (_command(texture_id="missing"),)),
            PetMeshValidationCode.MISSING_TEXTURE,
        ),
        (
            PetMeshScene(2, 2, 1.0, (_texture(), _texture()), (_command(),)),
            PetMeshValidationCode.DUPLICATE_TEXTURE,
        ),
        (
            _scene(
                PetMeshDrawCommand(
                    "texture",
                    _command().vertices,
                    (0, 1, 4),
                    0,
                )
            ),
            PetMeshValidationCode.INVALID_INDEX,
        ),
    ],
)
def test_invalid_scene_uses_fixed_public_error(
    scene: PetMeshScene,
    code: PetMeshValidationCode,
) -> None:
    with pytest.raises(PetMeshValidationError) as caught:
        validate_pet_mesh_scene(scene)

    assert caught.value.code is code
    assert str(caught.value) == "The pet mesh is invalid."
    assert "missing" not in str(caught.value)


def test_model_is_minimal_and_contains_no_spine_structures() -> None:
    fields = set(PetMeshDrawCommand.__dataclass_fields__)

    assert fields == {
        "texture_id",
        "vertices",
        "triangle_indices",
        "draw_order",
        "blend_mode",
        "clip_polygon",
    }
    assert fields.isdisjoint({"bone", "slot", "skin", "attachment", "deform"})
