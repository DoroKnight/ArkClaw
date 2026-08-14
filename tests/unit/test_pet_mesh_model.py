"""Tests for the deliberately small renderer-neutral mesh model."""

from __future__ import annotations

import pytest

from arkclaw.application.pet_mesh_model import (
    PetMeshBlendMode,
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


def test_renderer_neutral_blend_modes_preserve_alpha_compatibility_aliases() -> None:
    modes = PetMeshBlendMode

    assert modes.__members__["STRAIGHT_ALPHA"] is modes.NORMAL_STRAIGHT
    assert (
        modes.__members__["PREMULTIPLIED_ALPHA"]
        is modes.NORMAL_PREMULTIPLIED
    )
    assert {
        modes.NORMAL_STRAIGHT,
        modes.NORMAL_PREMULTIPLIED,
        modes.ADDITIVE,
        modes.MULTIPLY,
        modes.SCREEN,
    } == set(modes)


@pytest.mark.parametrize(
    "clip",
    [
        (
            PetMeshPoint(0.0, 0.0),
            PetMeshPoint(2.0, 2.0),
            PetMeshPoint(0.0, 2.0),
            PetMeshPoint(2.0, 0.0),
        ),
        (
            PetMeshPoint(0.0, 0.0),
            PetMeshPoint(2.0, 0.0),
            PetMeshPoint(1.0, 0.5),
            PetMeshPoint(2.0, 2.0),
            PetMeshPoint(0.0, 2.0),
        ),
        (
            PetMeshPoint(-1.0, 0.0),
            PetMeshPoint(1.0, 0.0),
            PetMeshPoint(0.0, 1.0),
        ),
    ],
)
def test_clip_contract_rejects_self_intersecting_concave_and_unbounded_polygons(
    clip: tuple[PetMeshPoint, ...],
) -> None:
    source = _command()
    scene = _scene(
        PetMeshDrawCommand(
            source.texture_id,
            source.vertices,
            source.triangle_indices,
            source.draw_order,
            clip_polygon=clip,
        )
    )

    with pytest.raises(PetMeshValidationError) as caught:
        validate_pet_mesh_scene(scene)

    assert caught.value.code is PetMeshValidationCode.INVALID_CLIP


def test_clip_contract_accepts_bounded_convex_polygon() -> None:
    source = _command()
    scene = _scene(
        PetMeshDrawCommand(
            source.texture_id,
            source.vertices,
            source.triangle_indices,
            source.draw_order,
            clip_polygon=(
                PetMeshPoint(0.0, 0.0),
                PetMeshPoint(2.0, 0.0),
                PetMeshPoint(1.0, 2.0),
            ),
        )
    )

    validate_pet_mesh_scene(scene)
