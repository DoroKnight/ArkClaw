"""Pure render-profile projection and desktop-surface planning."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from arkclaw.application.pet_geometry import Point, Rect
from arkclaw.application.pet_renderer_model import PetRendererAction
from arkclaw.application.pet_state import PetFacing
from arkclaw.application.spine38_runtime import Spine38Bounds

BODY_WIDTH = 160.0
BODY_HEIGHT = 180.0
CLIPPING_PADDING = 2.0
MAX_SPECIAL_EFFECT_FLOOR_LIFT = 16.0
MIN_EFFECT_SCALE_MULTIPLIER = 0.40
LAYOUT_SCALE_EPSILON = 1e-6
MAX_LOGICAL_DIMENSION = 1024
MAX_LOGICAL_AREA = 1_048_576
MAX_PHYSICAL_DIMENSION = 4096
MAX_PHYSICAL_AREA = 4_194_304


@dataclass(frozen=True, slots=True)
class RolePackRenderProfile:
    body_bounds: Spine38Bounds
    sampled_action_bounds: Mapping[PetRendererAction, Spine38Bounds]

    def __post_init__(self) -> None:
        _require_bounds(self.body_bounds)
        copied = dict(self.sampled_action_bounds)
        if not copied:
            raise ValueError("render profile requires sampled action bounds")
        for bounds in copied.values():
            _require_bounds(bounds)
        object.__setattr__(self, "sampled_action_bounds", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class PetBodyTransform:
    scale: float
    origin_x: float
    origin_y: float
    mirror_axis_x: float

    def __post_init__(self) -> None:
        if (
            not all(
                math.isfinite(value)
                for value in (
                    self.scale,
                    self.origin_x,
                    self.origin_y,
                    self.mirror_axis_x,
                )
            )
            or self.scale <= 0.0
        ):
            raise ValueError("body transform is invalid")


@dataclass(frozen=True, slots=True)
class ProjectedFacingEnvelope:
    content_bounds: Rect
    body_anchor: Point


@dataclass(frozen=True, slots=True)
class ProjectedActionEnvelope:
    right: ProjectedFacingEnvelope
    left: ProjectedFacingEnvelope


class RenderContainmentPolicy(StrEnum):
    BODY_PRIORITY = "body_priority"
    SIT_FULL_SAMPLED_BOUNDS = "sit_full_sampled_bounds"
    FULL_SAMPLED_BOUNDS = "full_sampled_bounds"


class PetRenderSurfaceMode(StrEnum):
    BODY = "body"
    OVERFLOW = "overflow"


class PetRenderLayoutQuality(StrEnum):
    FULL_SCALE = "full_scale"
    DEGRADED_FIT = "degraded_fit"


class PetRenderLayoutFailureReason(StrEnum):
    BODY_VERTICAL_INFEASIBLE = "body_vertical_infeasible"
    SPECIAL_EFFECT_FLOOR_INFEASIBLE = "special_effect_floor_infeasible"
    LOGICAL_RESOURCE_LIMIT_EXCEEDED = "logical_resource_limit_exceeded"
    INVALID_DPR = "invalid_dpr"
    PHYSICAL_RESOURCE_LIMIT_EXCEEDED = "physical_resource_limit_exceeded"
    WORKSPACE_FIT_INFEASIBLE = "workspace_fit_infeasible"
    SIT_DISPLAY_GEOMETRY_REQUIRED = "sit_display_geometry_required"
    SIT_DISPLAY_FIT_INFEASIBLE = "sit_display_fit_infeasible"


@dataclass(frozen=True, slots=True)
class PetRenderLayout:
    mode: PetRenderSurfaceMode
    surface_rect: Rect
    body_window_offset: Point
    resolved_body_position: Point
    ground_correction: float
    effective_facing: PetFacing
    scale_multiplier: float
    quality: PetRenderLayoutQuality

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value)
            for value in (
                self.surface_rect.x,
                self.surface_rect.y,
                self.surface_rect.width,
                self.surface_rect.height,
                self.body_window_offset.x,
                self.body_window_offset.y,
                self.resolved_body_position.x,
                self.resolved_body_position.y,
                self.ground_correction,
                self.scale_multiplier,
            )
        ):
            raise ValueError("render layout contains non-finite values")
        if self.scale_multiplier <= 0.0:
            raise ValueError("scale_multiplier must be positive")
        if self.quality is PetRenderLayoutQuality.FULL_SCALE and not math.isclose(
            self.scale_multiplier, 1.0, abs_tol=LAYOUT_SCALE_EPSILON
        ):
            raise ValueError("FULL_SCALE requires a 1.0 scale multiplier")
        if self.quality is PetRenderLayoutQuality.DEGRADED_FIT and not (
            self.scale_multiplier + LAYOUT_SCALE_EPSILON
            >= MIN_EFFECT_SCALE_MULTIPLIER
            and self.scale_multiplier < 1.0 - LAYOUT_SCALE_EPSILON
        ):
            raise ValueError("DEGRADED_FIT scale multiplier is out of range")
        expected = Point(
            self.surface_rect.x + self.body_window_offset.x,
            self.surface_rect.y + self.body_window_offset.y,
        )
        if not (
            math.isclose(
                expected.x,
                self.resolved_body_position.x,
                abs_tol=LAYOUT_SCALE_EPSILON,
            )
            and math.isclose(
                expected.y,
                self.resolved_body_position.y,
                abs_tol=LAYOUT_SCALE_EPSILON,
            )
        ):
            raise ValueError(
                "body window offset must recover the resolved body position"
            )
        if self.mode is PetRenderSurfaceMode.BODY:
            if self.body_window_offset != Point(0.0, 0.0):
                raise ValueError("BODY layout must use a zero body window offset")
            if not (
                math.isclose(
                    self.surface_rect.x,
                    self.resolved_body_position.x,
                    abs_tol=LAYOUT_SCALE_EPSILON,
                )
                and math.isclose(
                    self.surface_rect.y,
                    self.resolved_body_position.y,
                    abs_tol=LAYOUT_SCALE_EPSILON,
                )
            ):
                raise ValueError("BODY surface must coincide with resolved position")


@dataclass(frozen=True, slots=True)
class PetRenderLayoutFailure:
    reason: PetRenderLayoutFailureReason


PetRenderLayoutResult = PetRenderLayout | PetRenderLayoutFailure


@dataclass(frozen=True, slots=True)
class _CorrectedFacing:
    content_bounds: Rect
    body_anchor: Point
    correction: float


@dataclass(frozen=True, slots=True)
class _AvoidanceCandidate:
    target: Point
    raw_displacement: float


def project_action_envelope(
    *,
    sampled_bounds: Spine38Bounds,
    body_transform: PetBodyTransform,
) -> ProjectedActionEnvelope:
    """Project one sampled Spine-space union into both body-local facings."""

    _require_bounds(sampled_bounds)
    scale = body_transform.scale
    right_bounds = Rect(
        body_transform.origin_x + sampled_bounds.x * scale,
        body_transform.origin_y
        - (sampled_bounds.y + sampled_bounds.height) * scale,
        sampled_bounds.width * scale,
        sampled_bounds.height * scale,
    )
    mirror_axis = body_transform.mirror_axis_x
    left_bounds = Rect(
        2.0 * mirror_axis - right_bounds.right,
        right_bounds.y,
        right_bounds.width,
        right_bounds.height,
    )
    return ProjectedActionEnvelope(
        right=ProjectedFacingEnvelope(
            right_bounds,
            Point(body_transform.origin_x, body_transform.origin_y),
        ),
        left=ProjectedFacingEnvelope(
            left_bounds,
            Point(
                2.0 * mirror_axis - body_transform.origin_x,
                body_transform.origin_y,
            ),
        ),
    )


def plan_pet_render_layout(
    *,
    body_rect: Rect,
    workspace: Rect,
    envelope: ProjectedActionEnvelope,
    preferred_facing: PetFacing,
    policy: RenderContainmentPolicy,
    device_pixel_ratio: float,
    display: Rect | None = None,
) -> PetRenderLayoutResult:
    """Plan one immutable logical composition without Qt or bootstrap effects."""

    if not math.isfinite(device_pixel_ratio) or device_pixel_ratio <= 0.0:
        return PetRenderLayoutFailure(PetRenderLayoutFailureReason.INVALID_DPR)
    if policy is RenderContainmentPolicy.SIT_FULL_SAMPLED_BOUNDS:
        if display is None:
            return PetRenderLayoutFailure(
                PetRenderLayoutFailureReason.SIT_DISPLAY_GEOMETRY_REQUIRED
            )
        corrected = _correct(
            _for_facing(envelope, preferred_facing),
            maximum_lift=0.0,
        )
        result = _successful_layout(
            body_rect,
            corrected,
            preferred_facing,
            1.0,
            device_pixel_ratio,
        )
        if isinstance(result, PetRenderLayoutFailure):
            return result
        if not _contains(display, result.surface_rect):
            return PetRenderLayoutFailure(
                PetRenderLayoutFailureReason.SIT_DISPLAY_FIT_INFEASIBLE
            )
        return result
    if policy is RenderContainmentPolicy.BODY_PRIORITY:
        corrected = _correct(
            _for_facing(envelope, preferred_facing),
            maximum_lift=0.0,
        )
        if corrected.content_bounds.y < 0.0:
            return PetRenderLayoutFailure(
                PetRenderLayoutFailureReason.BODY_VERTICAL_INFEASIBLE
            )
        physical_failure = _physical_resource_failure(
            body_rect, device_pixel_ratio
        )
        if physical_failure is not None:
            return physical_failure
        return PetRenderLayout(
            PetRenderSurfaceMode.BODY,
            body_rect,
            Point(0.0, 0.0),
            Point(body_rect.x, body_rect.y),
            corrected.correction,
            preferred_facing,
            1.0,
            PetRenderLayoutQuality.FULL_SCALE,
        )

    corrected_by_facing: dict[PetFacing, _CorrectedFacing] = {}
    for facing in (PetFacing.RIGHT, PetFacing.LEFT):
        candidate = _for_facing(envelope, facing)
        correction = max(0.0, candidate.content_bounds.bottom - BODY_HEIGHT)
        if correction > MAX_SPECIAL_EFFECT_FLOOR_LIFT + LAYOUT_SCALE_EPSILON:
            return PetRenderLayoutFailure(
                PetRenderLayoutFailureReason.SPECIAL_EFFECT_FLOOR_INFEASIBLE
            )
        corrected_by_facing[facing] = _correct(
            candidate,
            maximum_lift=0.0,
        )

    # Logical profile safety is candidate-static and cannot be bypassed by fitting.
    full_surface = _surface_for(
        body_rect,
        corrected_by_facing[preferred_facing],
        1.0,
    )
    if _exceeds_logical_resources(full_surface):
        return PetRenderLayoutFailure(
            PetRenderLayoutFailureReason.LOGICAL_RESOURCE_LIMIT_EXCEEDED
        )

    alternate = (
        PetFacing.LEFT
        if preferred_facing is PetFacing.RIGHT
        else PetFacing.RIGHT
    )
    for facing in (preferred_facing, alternate):
        corrected = corrected_by_facing[facing]
        if _visible_content_fits(body_rect, corrected, 1.0, workspace):
            return _successful_layout(
                body_rect,
                corrected,
                facing,
                1.0,
                device_pixel_ratio,
            )

    avoidance: dict[PetFacing, _AvoidanceCandidate] = {}
    for facing in (preferred_facing, alternate):
        avoidance_candidate = _horizontal_avoidance(
            body_rect,
            corrected_by_facing[facing],
            workspace,
        )
        if avoidance_candidate is not None:
            avoidance[facing] = avoidance_candidate
    if avoidance:
        selected = _select_avoidance_facing(preferred_facing, avoidance)
        target = avoidance[selected].target
        moved_body = Rect(
            target.x, body_rect.y, body_rect.width, body_rect.height
        )
        return _successful_layout(
            moved_body,
            corrected_by_facing[selected],
            selected,
            1.0,
            device_pixel_ratio,
        )

    scales = {
        facing: _largest_feasible_scale(body_rect, corrected, workspace)
        for facing, corrected in corrected_by_facing.items()
    }
    viable = {
        facing: scale
        for facing, scale in scales.items()
        if scale is not None
        and scale + LAYOUT_SCALE_EPSILON >= MIN_EFFECT_SCALE_MULTIPLIER
    }
    if not viable:
        return PetRenderLayoutFailure(
            PetRenderLayoutFailureReason.WORKSPACE_FIT_INFEASIBLE
        )
    right_scale = viable.get(PetFacing.RIGHT)
    left_scale = viable.get(PetFacing.LEFT)
    if right_scale is None:
        selected = PetFacing.LEFT
    elif left_scale is None:
        selected = PetFacing.RIGHT
    elif abs(right_scale - left_scale) <= LAYOUT_SCALE_EPSILON:
        selected = preferred_facing
    else:
        selected = (
            PetFacing.RIGHT if right_scale > left_scale else PetFacing.LEFT
        )
    return _successful_layout(
        body_rect,
        corrected_by_facing[selected],
        selected,
        viable[selected],
        device_pixel_ratio,
    )


def _successful_layout(
    body_rect: Rect,
    corrected: _CorrectedFacing,
    facing: PetFacing,
    scale: float,
    dpr: float,
) -> PetRenderLayoutResult:
    surface = _surface_for(body_rect, corrected, scale)
    if _exceeds_logical_resources(surface):
        return PetRenderLayoutFailure(
            PetRenderLayoutFailureReason.LOGICAL_RESOURCE_LIMIT_EXCEEDED
        )
    physical_failure = _physical_resource_failure(surface, dpr)
    if physical_failure is not None:
        return physical_failure
    body_contains_surface = _contains(body_rect, surface)
    actual_surface = body_rect if body_contains_surface else surface
    return PetRenderLayout(
        (
            PetRenderSurfaceMode.BODY
            if body_contains_surface
            else PetRenderSurfaceMode.OVERFLOW
        ),
        actual_surface,
        Point(body_rect.x - actual_surface.x, body_rect.y - actual_surface.y),
        Point(body_rect.x, body_rect.y),
        corrected.correction,
        facing,
        scale,
        (
            PetRenderLayoutQuality.FULL_SCALE
            if math.isclose(scale, 1.0, abs_tol=LAYOUT_SCALE_EPSILON)
            else PetRenderLayoutQuality.DEGRADED_FIT
        ),
    )


def _correct(
    facing: ProjectedFacingEnvelope,
    *,
    maximum_lift: float | None,
) -> _CorrectedFacing:
    correction = max(0.0, facing.content_bounds.bottom - BODY_HEIGHT)
    if maximum_lift is not None:
        correction = min(correction, maximum_lift)
    return _CorrectedFacing(
        _translate(facing.content_bounds, 0.0, -correction),
        Point(facing.body_anchor.x, facing.body_anchor.y - correction),
        correction,
    )


def _for_facing(
    envelope: ProjectedActionEnvelope,
    facing: PetFacing,
) -> ProjectedFacingEnvelope:
    return envelope.left if facing is PetFacing.LEFT else envelope.right


def _visible_content_fits(
    body_rect: Rect,
    corrected: _CorrectedFacing,
    scale: float,
    workspace: Rect,
) -> bool:
    visible = _desktop_scaled_content(body_rect, corrected, scale)
    return (
        visible.x >= workspace.x - LAYOUT_SCALE_EPSILON
        and visible.y >= workspace.y - LAYOUT_SCALE_EPSILON
        and visible.right <= workspace.right + LAYOUT_SCALE_EPSILON
        and visible.bottom
        <= workspace.bottom
        + MAX_SPECIAL_EFFECT_FLOOR_LIFT
        + LAYOUT_SCALE_EPSILON
    )


def _horizontal_avoidance(
    body_rect: Rect,
    corrected: _CorrectedFacing,
    workspace: Rect,
) -> _AvoidanceCandidate | None:
    """Return a quantized full-scale placement, or None when it cannot fit.

    The feasible displacement interval keeps both the full-scale visible
    content and the 160x180 body window inside the active workspace. The
    candidate carries the raw displacement for ordering and the quantized
    target position for the actual submit.
    """

    content = _desktop_scaled_content(body_rect, corrected, 1.0)
    delta_lower = max(
        workspace.x - content.x,
        workspace.x - body_rect.x,
    )
    delta_upper = min(
        workspace.right - content.right,
        workspace.right - body_rect.right,
    )
    if delta_lower > delta_upper + LAYOUT_SCALE_EPSILON:
        return None
    if delta_lower <= LAYOUT_SCALE_EPSILON and delta_upper >= -LAYOUT_SCALE_EPSILON:
        delta = 0.0
    elif delta_upper < -LAYOUT_SCALE_EPSILON:
        delta = delta_upper
    else:
        delta = delta_lower
    target_x = body_rect.x + delta
    quantized_x: float
    if delta > LAYOUT_SCALE_EPSILON:
        quantized_x = float(math.ceil(target_x - LAYOUT_SCALE_EPSILON))
    elif delta < -LAYOUT_SCALE_EPSILON:
        quantized_x = float(math.floor(target_x + LAYOUT_SCALE_EPSILON))
    else:
        quantized_x = body_rect.x
    quantized_body = Rect(
        quantized_x, body_rect.y, body_rect.width, body_rect.height
    )
    if not (
        quantized_x >= workspace.x - LAYOUT_SCALE_EPSILON
        and quantized_x + body_rect.width
        <= workspace.right + LAYOUT_SCALE_EPSILON
    ):
        return None
    if not _visible_content_fits(quantized_body, corrected, 1.0, workspace):
        return None
    return _AvoidanceCandidate(
        Point(quantized_x, body_rect.y),
        delta,
    )


def _select_avoidance_facing(
    preferred_facing: PetFacing,
    candidates: Mapping[PetFacing, _AvoidanceCandidate],
) -> PetFacing:
    right = candidates.get(PetFacing.RIGHT)
    left = candidates.get(PetFacing.LEFT)
    if right is None:
        return PetFacing.LEFT
    if left is None:
        return PetFacing.RIGHT
    if (
        abs(right.raw_displacement - left.raw_displacement)
        <= LAYOUT_SCALE_EPSILON
    ):
        return preferred_facing
    if abs(right.raw_displacement) < abs(left.raw_displacement):
        return PetFacing.RIGHT
    return PetFacing.LEFT


def _desktop_scaled_content(
    body_rect: Rect,
    corrected: _CorrectedFacing,
    scale: float,
) -> Rect:
    pivot = Point(
        body_rect.x + corrected.body_anchor.x,
        body_rect.y + BODY_HEIGHT,
    )
    desktop = _translate(
        corrected.content_bounds,
        body_rect.x,
        body_rect.y,
    )
    left = pivot.x + scale * (desktop.x - pivot.x)
    top = pivot.y + scale * (desktop.y - pivot.y)
    right = pivot.x + scale * (desktop.right - pivot.x)
    bottom = pivot.y + scale * (desktop.bottom - pivot.y)
    return Rect(left, top, right - left, bottom - top)


def _surface_for(
    body_rect: Rect,
    corrected: _CorrectedFacing,
    scale: float,
) -> Rect:
    visible = _desktop_scaled_content(body_rect, corrected, scale)
    padded = Rect(
        visible.x - CLIPPING_PADDING,
        visible.y - CLIPPING_PADDING,
        visible.width + 2.0 * CLIPPING_PADDING,
        visible.height + 2.0 * CLIPPING_PADDING,
    )
    left = math.floor(padded.x)
    top = math.floor(padded.y)
    right = math.ceil(padded.right)
    bottom = math.ceil(padded.bottom)
    return Rect(float(left), float(top), float(right - left), float(bottom - top))


def _largest_feasible_scale(
    body_rect: Rect,
    corrected: _CorrectedFacing,
    workspace: Rect,
) -> float | None:
    if _visible_content_fits(body_rect, corrected, 1.0, workspace):
        return 1.0
    pivot = Point(
        body_rect.x + corrected.body_anchor.x,
        body_rect.y + BODY_HEIGHT,
    )
    if not (
        workspace.x <= pivot.x <= workspace.right
        and workspace.y <= pivot.y <= workspace.bottom
    ):
        return None
    low = 0.0
    high = 1.0
    for _ in range(64):
        middle = (low + high) / 2.0
        if _visible_content_fits(body_rect, corrected, middle, workspace):
            low = middle
        else:
            high = middle
    return low


def _physical_resource_failure(
    surface: Rect,
    dpr: float,
) -> PetRenderLayoutFailure | None:
    width = math.ceil(surface.width * dpr)
    height = math.ceil(surface.height * dpr)
    if (
        width > MAX_PHYSICAL_DIMENSION
        or height > MAX_PHYSICAL_DIMENSION
        or width * height > MAX_PHYSICAL_AREA
    ):
        return PetRenderLayoutFailure(
            PetRenderLayoutFailureReason.PHYSICAL_RESOURCE_LIMIT_EXCEEDED
        )
    return None


def _exceeds_logical_resources(surface: Rect) -> bool:
    return (
        surface.width > MAX_LOGICAL_DIMENSION
        or surface.height > MAX_LOGICAL_DIMENSION
        or surface.width * surface.height > MAX_LOGICAL_AREA
    )


def _contains(container: Rect, content: Rect) -> bool:
    return (
        content.x >= container.x - LAYOUT_SCALE_EPSILON
        and content.y >= container.y - LAYOUT_SCALE_EPSILON
        and content.right <= container.right + LAYOUT_SCALE_EPSILON
        and content.bottom <= container.bottom + LAYOUT_SCALE_EPSILON
    )


def _translate(rect: Rect, dx: float, dy: float) -> Rect:
    return Rect(rect.x + dx, rect.y + dy, rect.width, rect.height)


def _require_bounds(bounds: Spine38Bounds) -> None:
    if (
        not all(
            math.isfinite(value)
            for value in (bounds.x, bounds.y, bounds.width, bounds.height)
        )
        or bounds.width <= 0.0
        or bounds.height <= 0.0
    ):
        raise ValueError("sampled bounds are invalid")
