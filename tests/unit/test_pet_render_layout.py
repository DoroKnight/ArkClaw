"""Behavior tests for action projection and desktop render layout."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from arkclaw.application.pet.pet_geometry import Point, Rect
from arkclaw.application.pet.pet_render_layout import (
    LAYOUT_SCALE_EPSILON,
    MIN_EFFECT_SCALE_MULTIPLIER,
    PetBodyTransform,
    PetRenderLayout,
    PetRenderLayoutFailure,
    PetRenderLayoutFailureReason,
    PetRenderLayoutQuality,
    PetRenderSurfaceMode,
    ProjectedActionEnvelope,
    ProjectedFacingEnvelope,
    RenderContainmentPolicy,
    RolePackRenderProfile,
    plan_pet_render_layout,
    project_action_envelope,
)
from arkclaw.application.pet.pet_renderer_model import PetRendererAction
from arkclaw.application.pet.pet_state import PetFacing
from arkclaw.application.pet.spine38_runtime import Spine38Bounds

BODY = Rect(500.0, 700.0, 160.0, 180.0)
WORKSPACE = Rect(0.0, 0.0, 1920.0, 880.0)


_DEFAULT_ANCHOR = Point(80.0, 180.0)


def _facing(bounds: Rect, anchor: Point = _DEFAULT_ANCHOR) -> ProjectedFacingEnvelope:
    return ProjectedFacingEnvelope(bounds, anchor)


def _envelope(
    right: Rect,
    left: Rect | None = None,
    *,
    right_anchor: Point = _DEFAULT_ANCHOR,
    left_anchor: Point = _DEFAULT_ANCHOR,
) -> ProjectedActionEnvelope:
    return ProjectedActionEnvelope(
        right=_facing(right, right_anchor),
        left=_facing(left or right, left_anchor),
    )


def _plan(
    envelope: ProjectedActionEnvelope,
    *,
    policy: RenderContainmentPolicy,
    body: Rect = BODY,
    workspace: Rect = WORKSPACE,
    display: Rect | None = None,
    facing: PetFacing = PetFacing.RIGHT,
    dpr: float = 1.0,
) -> PetRenderLayout | PetRenderLayoutFailure:
    return plan_pet_render_layout(
        body_rect=body,
        workspace=workspace,
        display=display,
        envelope=envelope,
        preferred_facing=facing,
        policy=policy,
        device_pixel_ratio=dpr,
    )


def test_sit_right_uses_full_sampled_surface_without_moving_body_anchor() -> None:
    body = Rect(500.0, 839.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(
                -15.5314137629547,
                68.7579243590932,
                161.7336231942777,
                142.3009864726378,
            )
        ),
        policy=RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=Rect(0.0, 0.0, 1707.0, 1019.0),
        display=Rect(0.0, 0.0, 1707.0, 1067.0),
    )

    assert isinstance(result, PetRenderLayout)
    assert result.mode is PetRenderSurfaceMode.OVERFLOW
    assert result.surface_rect == Rect(482.0, 905.0, 167.0, 148.0)
    assert result.body_window_offset == Point(18.0, -66.0)
    assert result.resolved_body_position == Point(500.0, 839.0)
    assert result.ground_correction == 0.0
    assert result.effective_facing is PetFacing.RIGHT
    assert result.scale_multiplier == 1.0
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE


def test_sit_left_uses_mirrored_surface_without_changing_requested_facing() -> None:
    body = Rect(500.0, 839.0, 160.0, 180.0)
    bounds = Rect(
        -15.5314137629547,
        68.7579243590932,
        161.7336231942777,
        142.3009864726378,
    )
    result = _plan(
        _envelope(
            bounds,
            Rect(
                13.797790568677,
                68.7579243590932,
                161.7336231942777,
                142.3009864726378,
            ),
        ),
        policy=RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=Rect(0.0, 0.0, 1707.0, 1019.0),
        display=Rect(0.0, 0.0, 1707.0, 1067.0),
        facing=PetFacing.LEFT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.surface_rect == Rect(511.0, 905.0, 167.0, 148.0)
    assert result.body_window_offset == Point(-11.0, -66.0)
    assert result.resolved_body_position == Point(500.0, 839.0)
    assert result.ground_correction == 0.0
    assert result.effective_facing is PetFacing.LEFT
    assert result.scale_multiplier == 1.0


def test_sit_requires_same_screen_display_geometry() -> None:
    result = _plan(
        _envelope(Rect(-15.0, 68.0, 161.0, 143.0)),
        policy=RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS,
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.SIT_DISPLAY_GEOMETRY_REQUIRED
    )


def test_sit_fails_closed_when_full_surface_does_not_fit_display() -> None:
    result = _plan(
        _envelope(Rect(-15.0, 68.0, 161.0, 143.0)),
        policy=RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS,
        body=Rect(500.0, 839.0, 160.0, 180.0),
        workspace=Rect(0.0, 0.0, 1707.0, 1019.0),
        display=Rect(0.0, 0.0, 1707.0, 1051.0),
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.SIT_DISPLAY_FIT_INFEASIBLE
    )


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_sit_logical_surface_is_stable_across_supported_dpr(dpr: float) -> None:
    result = _plan(
        _envelope(
            Rect(
                -15.5314137629547,
                68.7579243590932,
                161.7336231942777,
                142.3009864726378,
            )
        ),
        policy=RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS,
        body=Rect(500.0, 839.0, 160.0, 180.0),
        workspace=Rect(0.0, 0.0, 1707.0, 1019.0),
        display=Rect(0.0, 0.0, 1707.0, 1067.0),
        dpr=dpr,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.surface_rect == Rect(482.0, 905.0, 167.0, 148.0)


@pytest.mark.parametrize(
    "policy",
    [
        RenderContainmentPolicy.BODY_PRIORITY,
        RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
    ],
)
def test_non_sit_policies_ignore_display_geometry(
    policy: RenderContainmentPolicy,
) -> None:
    with_display = _plan(
        _envelope(Rect(10.0, 10.0, 140.0, 170.0)),
        policy=policy,
        display=Rect(9999.0, 9999.0, 1.0, 1.0),
    )
    without_display = _plan(
        _envelope(Rect(10.0, 10.0, 140.0, 170.0)),
        policy=policy,
    )

    assert with_display == without_display


def test_profile_mapping_is_defensively_copied_and_immutable() -> None:
    source = {PetRendererAction.IDLE: Spine38Bounds(0.0, 0.0, 1.0, 2.0)}
    profile = RolePackRenderProfile(
        body_bounds=Spine38Bounds(0.0, 0.0, 1.0, 2.0),
        sampled_action_bounds=source,
    )
    source.clear()

    assert isinstance(profile.sampled_action_bounds, MappingProxyType)
    assert profile.sampled_action_bounds[PetRendererAction.IDLE].height == 2.0
    with pytest.raises(TypeError):
        profile.sampled_action_bounds[PetRendererAction.SLEEP] = Spine38Bounds(  # type: ignore[index]
            0.0, 0.0, 1.0, 1.0
        )


def test_dynamic_visible_bounds_never_write_back_into_calibration() -> None:
    body_bounds = Spine38Bounds(-0.5, 0.0, 1.0, 2.0)
    profile = RolePackRenderProfile(
        body_bounds,
        {PetRendererAction.SITTING: Spine38Bounds(-1.0, -0.4, 2.0, 1.8)},
    )
    before = profile.body_bounds

    result = _plan(
        project_action_envelope(
            sampled_bounds=profile.sampled_action_bounds[PetRendererAction.SITTING],
            body_transform=PetBodyTransform(100.0, 80.0, 180.0, 80.0),
        ),
        policy=RenderContainmentPolicy.BODY_PRIORITY,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.ground_correction == 0.0
    assert profile.body_bounds is before


def test_projector_uses_one_transform_for_bounds_anchor_and_mirror_axis() -> None:
    projected = project_action_envelope(
        sampled_bounds=Spine38Bounds(-2.0, 1.0, 6.0, 10.0),
        body_transform=PetBodyTransform(3.0, 70.0, 175.0, 80.0),
    )

    assert projected.right.content_bounds == Rect(64.0, 142.0, 18.0, 30.0)
    assert projected.right.body_anchor == Point(70.0, 175.0)
    assert projected.left.content_bounds == Rect(78.0, 142.0, 18.0, 30.0)
    assert projected.left.body_anchor == Point(90.0, 175.0)


def test_sit_does_not_apply_frame_bounds_ground_correction() -> None:
    result = _plan(
        _envelope(Rect(-15.0, 68.0, 161.0, 143.0)),
        policy=RenderContainmentPolicy.BODY_PRIORITY,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.mode is PetRenderSurfaceMode.BODY
    assert result.surface_rect == BODY
    assert result.body_window_offset == Point(0.0, 0.0)
    assert result.ground_correction == 0.0
    assert result.scale_multiplier == 1.0


def test_body_priority_negative_corrected_top_is_typed_failure() -> None:
    result = _plan(
        _envelope(Rect(10.0, -40.0, 120.0, 250.0)),
        policy=RenderContainmentPolicy.BODY_PRIORITY,
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.BODY_VERTICAL_INFEASIBLE
    )


def test_real_schwarz_special_effect_underflow_keeps_body_grounded() -> None:
    result = _plan(
        _envelope(Rect(-31.91, -546.04, 477.87, 741.90)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.ground_correction == 0.0
    assert result.surface_rect.bottom > WORKSPACE.bottom
    assert result.surface_rect.bottom <= WORKSPACE.bottom + 18.0
    assert result.surface_rect.y + result.body_window_offset.y == BODY.y


def test_special_scene_floor_lift_above_sixteen_pixels_fails_closed() -> None:
    result = _plan(
        _envelope(Rect(10.0, -20.0, 370.0, 216.01)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.SPECIAL_EFFECT_FLOOR_INFEASIBLE
    )


def test_special_full_scale_uses_overflow_and_preserves_body_offset_equation() -> None:
    result = _plan(
        _envelope(Rect(12.9, -83.3, 370.7, 264.0)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.mode is PetRenderSurfaceMode.OVERFLOW
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.scale_multiplier == 1.0
    assert result.ground_correction == 0.0
    assert result.surface_rect == Rect(510.0, 614.0, 376.0, 269.0)
    assert Point(
        result.surface_rect.x + result.body_window_offset.x,
        result.surface_rect.y + result.body_window_offset.y,
    ) == Point(BODY.x, BODY.y)


def test_workspace_fit_uses_visible_content_not_transparent_padding() -> None:
    workspace = Rect(0.0, 0.0, 400.0, 300.0)
    body = Rect(100.0, 120.0, 160.0, 180.0)
    result = _plan(
        _envelope(Rect(-100.0, -120.0, 400.0, 300.0)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=workspace,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.scale_multiplier == 1.0
    assert result.surface_rect == Rect(-2.0, -2.0, 404.0, 304.0)


def test_padding_that_exceeds_body_draw_surface_selects_overflow() -> None:
    result = _plan(
        _envelope(Rect(1.0, 1.0, 158.0, 178.0)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.mode is PetRenderSurfaceMode.OVERFLOW


def test_degraded_fit_selects_largest_scale_and_keeps_two_pixel_padding() -> None:
    workspace = Rect(0.0, 0.0, 300.0, 220.0)
    body = Rect(40.0, 40.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-100.0, -40.0, 500.0, 220.0),
            Rect(-20.0, -40.0, 350.0, 220.0),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=workspace,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.DEGRADED_FIT
    assert result.effective_facing is PetFacing.LEFT
    assert 0.71 < result.scale_multiplier < 0.73
    visible_width = 350.0 * result.scale_multiplier
    assert result.surface_rect.width >= visible_width + 4.0


def test_degraded_fit_scale_tie_within_epsilon_preserves_preferred_facing() -> None:
    workspace = Rect(0.0, 0.0, 280.0, 220.0)
    body = Rect(60.0, 40.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-80.0, -40.0, 400.0, 220.0),
            Rect(-80.0, -40.0, 400.0 + LAYOUT_SCALE_EPSILON, 220.0),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=workspace,
        facing=PetFacing.LEFT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.effective_facing is PetFacing.LEFT


def test_degraded_fit_below_quality_floor_is_typed_failure() -> None:
    result = _plan(
        _envelope(Rect(-320.0, -200.0, 800.0, 380.0)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=Rect(20.0, 20.0, 160.0, 180.0),
        workspace=Rect(0.0, 0.0, 200.0, 200.0),
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.WORKSPACE_FIT_INFEASIBLE
    )


@pytest.mark.parametrize("dpr", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_dpr_is_typed_environment_failure(dpr: float) -> None:
    result = _plan(
        _envelope(Rect(10.0, 10.0, 140.0, 170.0)),
        policy=RenderContainmentPolicy.BODY_PRIORITY,
        dpr=dpr,
    )

    assert result == PetRenderLayoutFailure(PetRenderLayoutFailureReason.INVALID_DPR)


def test_outward_rounded_surface_drives_logical_resource_failure() -> None:
    result = _plan(
        _envelope(Rect(-0.1, -0.1, 1020.2, 180.1)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=Rect(0.0, 0.0, 160.0, 180.0),
        workspace=Rect(-1000.0, -1000.0, 3000.0, 3000.0),
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.LOGICAL_RESOURCE_LIMIT_EXCEEDED
    )


def test_outward_rounded_surface_drives_physical_resource_failure() -> None:
    result = _plan(
        _envelope(Rect(-400.0, -400.0, 900.0, 580.0)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=Rect(500.0, 500.0, 160.0, 180.0),
        workspace=Rect(0.0, 0.0, 2000.0, 1200.0),
        dpr=3.0,
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.PHYSICAL_RESOURCE_LIMIT_EXCEEDED
    )


def test_special_at_left_edge_moves_inward_without_scaling() -> None:
    body = Rect(0.0, 700.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-31.91, -546.04, 477.87, 741.90),
            Rect(-285.96, -546.04, 477.87, 741.90),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.RIGHT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.scale_multiplier == 1.0
    assert result.effective_facing is PetFacing.RIGHT
    assert result.resolved_body_position == Point(32.0, 700.0)
    assert result.resolved_body_position.x - 31.91 >= -LAYOUT_SCALE_EPSILON
    assert (
        result.resolved_body_position.x - 31.91 + 477.87
        <= WORKSPACE.right + LAYOUT_SCALE_EPSILON
    )


def test_special_at_right_edge_moves_inward_without_scaling() -> None:
    body = Rect(1760.0, 700.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-31.91, -546.04, 477.87, 741.90),
            Rect(-285.96, -546.04, 477.87, 741.90),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.LEFT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.scale_multiplier == 1.0
    assert result.effective_facing is PetFacing.LEFT
    assert result.resolved_body_position == Point(1728.0, 700.0)
    assert result.resolved_body_position.x - 285.96 >= -LAYOUT_SCALE_EPSILON
    assert (
        result.resolved_body_position.x - 285.96 + 477.87
        <= WORKSPACE.right + LAYOUT_SCALE_EPSILON
    )


def test_special_center_does_not_move_or_swap_facing() -> None:
    result = _plan(
        _envelope(Rect(-31.91, -546.04, 477.87, 741.90)),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        facing=PetFacing.RIGHT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.effective_facing is PetFacing.RIGHT
    assert result.resolved_body_position == Point(BODY.x, BODY.y)


def test_special_switches_facing_without_moving_when_alternate_fits() -> None:
    body = Rect(1700.0, 700.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(150.0, -50.0, 200.0, 230.0),
            Rect(-20.0, -50.0, 100.0, 230.0),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.RIGHT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.effective_facing is PetFacing.LEFT
    assert result.resolved_body_position.x == 1700.0


def test_special_picks_smaller_displacement_over_preferred_facing() -> None:
    body = Rect(0.0, 700.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-10.0, -50.0, 100.0, 230.0),
            Rect(-60.0, -50.0, 200.0, 230.0),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.LEFT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.effective_facing is PetFacing.RIGHT
    assert result.resolved_body_position.x == 10.0


def test_special_keeps_preferred_facing_when_displacements_tie() -> None:
    body = Rect(0.0, 700.0, 160.0, 180.0)
    symmetric = Rect(-100.0, -50.0, 360.0, 230.0)
    result = _plan(
        _envelope(symmetric, symmetric),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.LEFT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.effective_facing is PetFacing.LEFT
    assert result.resolved_body_position.x == 100.0


def test_special_keeps_preferred_facing_when_displacements_differ_within_epsilon() -> None:
    body = Rect(0.0, 700.0, 160.0, 180.0)
    tiny = LAYOUT_SCALE_EPSILON * 0.5
    result = _plan(
        _envelope(
            Rect(-10.0, -50.0, 100.0, 230.0),
            Rect(-10.0 - tiny, -50.0, 100.0, 230.0),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.LEFT,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.FULL_SCALE
    assert result.effective_facing is PetFacing.LEFT
    assert result.resolved_body_position.x == 10.0


def test_special_plan_is_deterministic_across_calls() -> None:
    body = Rect(0.0, 700.0, 160.0, 180.0)
    envelope = _envelope(
        Rect(-31.91, -546.04, 477.87, 741.90),
        Rect(-285.96, -546.04, 477.87, 741.90),
    )

    first = _plan(
        envelope,
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.RIGHT,
    )
    second = _plan(
        envelope,
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        facing=PetFacing.RIGHT,
    )

    assert first == second


def test_special_narrow_workspace_still_degrades_without_deleting_safety() -> None:
    workspace = Rect(0.0, 0.0, 360.0, 880.0)
    body = Rect(70.0, 700.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-31.91, -546.04, 477.87, 741.90),
            Rect(-285.96, -546.04, 477.87, 741.90),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=workspace,
    )

    assert isinstance(result, PetRenderLayout)
    assert result.quality is PetRenderLayoutQuality.DEGRADED_FIT
    assert result.scale_multiplier < 1.0
    assert (
        result.scale_multiplier
        >= MIN_EFFECT_SCALE_MULTIPLIER - LAYOUT_SCALE_EPSILON
    )


def test_special_workspace_too_narrow_for_quality_floor_is_typed_failure() -> None:
    workspace = Rect(0.0, 0.0, 180.0, 880.0)
    body = Rect(10.0, 700.0, 160.0, 180.0)
    result = _plan(
        _envelope(
            Rect(-31.91, -546.04, 477.87, 741.90),
            Rect(-285.96, -546.04, 477.87, 741.90),
        ),
        policy=RenderContainmentPolicy.FULL_SAMPLED_BOUNDS,
        body=body,
        workspace=workspace,
    )

    assert result == PetRenderLayoutFailure(
        PetRenderLayoutFailureReason.WORKSPACE_FIT_INFEASIBLE
    )
