"""Qt-free geometric anchor contract for the Conversation Capsule.

The placement seam is independent from Qt widget visibility and from Character
BODY/OVERFLOW geometry.  It implements the frozen upper-side preference with
directional fallback, work-area containment, no visible/hit overlap, and a
final size-reduction step before reporting no placement.
"""

from __future__ import annotations

from dataclasses import dataclass


class AnchorPlacementUnavailable(Exception):
    """Raised when no legal capsule rectangle exists in the supplied work area."""


@dataclass(frozen=True, slots=True)
class AnchorRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True, slots=True)
class AnchorPlacement:
    side: str
    rect: AnchorRect
    fallback: tuple[str, ...] = ()
    reduced: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    side: str
    x: int
    y: int


def place_conversation_capsule(
    anchor: AnchorRect,
    size: tuple[int, int],
    work_area: AnchorRect,
) -> AnchorPlacement:
    """Return the first legal placement for the preferred capsule size.

    Candidate order follows the frozen product direction language:

    1. upper-side placements (right/center/left alignment);
    2. below placements (right/center/left alignment);
    3. the clearer horizontal side (interior side for edge anchors);

    If no candidate fits, the largest reduced size that still avoids the
    anchor and stays inside the work area is selected.  If no such size
    exists, :class:`AnchorPlacementUnavailable` is raised instead of
    returning a rectangle that violates the work-area/no-overlap contract.
    """

    width, height = size
    if width <= 0 or height <= 0:
        raise AnchorPlacementUnavailable("capsule size must be positive")
    if work_area.width <= 0 or work_area.height <= 0:
        raise AnchorPlacementUnavailable("work area must be positive")

    candidate = _first_valid_candidate(anchor, work_area, width, height)
    if candidate is not None:
        return _to_placement(candidate, width, height)

    max_percent = _max_scale_percent(width, height, work_area)
    low = 1
    high = max_percent
    best_candidate: _Candidate | None = None
    best_size: tuple[int, int] | None = None

    while low <= high:
        mid = (low + high) // 2
        reduced_width = max(1, (width * mid) // 100)
        reduced_height = max(1, (height * mid) // 100)
        candidate = _first_valid_candidate(
            anchor,
            work_area,
            reduced_width,
            reduced_height,
        )
        if candidate is None:
            high = mid - 1
            continue

        best_candidate = candidate
        best_size = (reduced_width, reduced_height)
        low = mid + 1

    if best_candidate is None or best_size is None:
        raise AnchorPlacementUnavailable(
            "anchor blocks every legal capsule placement"
        )

    placement = _to_placement(best_candidate, *best_size)
    return AnchorPlacement(
        side=placement.side,
        rect=placement.rect,
        fallback=("reduce-size",),
        reduced=True,
    )


def _to_placement(
    candidate: _Candidate,
    width: int,
    height: int,
) -> AnchorPlacement:
    return AnchorPlacement(
        side=candidate.side,
        rect=AnchorRect(candidate.x, candidate.y, width, height),
    )


def _first_valid_candidate(
    anchor: AnchorRect,
    work_area: AnchorRect,
    width: int,
    height: int,
) -> _Candidate | None:
    for candidate in _ordered_candidates(anchor, work_area, width, height):
        if _is_valid(candidate, anchor, work_area, width, height):
            return candidate
    return None


def _ordered_candidates(
    anchor: AnchorRect,
    work_area: AnchorRect,
    width: int,
    height: int,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []

    x_alignments = (
        anchor.right - width,
        anchor.x + anchor.width // 2 - width // 2,
        anchor.x,
    )
    for x in x_alignments:
        candidates.append(_Candidate("upper", x, anchor.y - height))
    for x in x_alignments:
        candidates.append(_Candidate("below", x, anchor.bottom))

    y_alignments = (
        anchor.bottom - height,
        anchor.y + anchor.height // 2 - height // 2,
        anchor.y,
    )
    left_clearance = anchor.x - work_area.x
    right_clearance = work_area.right - anchor.right
    side_order = (
        ("left", "right")
        if left_clearance > right_clearance
        else ("right", "left")
    )

    for side in side_order:
        x = anchor.x - width if side == "left" else anchor.right
        for y in y_alignments:
            candidates.append(_Candidate(side, x, y))

    return candidates


def _is_valid(
    candidate: _Candidate,
    anchor: AnchorRect,
    work_area: AnchorRect,
    width: int,
    height: int,
) -> bool:
    if candidate.x < work_area.x or candidate.y < work_area.y:
        return False
    if candidate.x + width > work_area.right:
        return False
    if candidate.y + height > work_area.bottom:
        return False

    return (
        candidate.x + width <= anchor.x
        or anchor.right <= candidate.x
        or candidate.y + height <= anchor.y
        or anchor.bottom <= candidate.y
    )


def _max_scale_percent(
    width: int,
    height: int,
    work_area: AnchorRect,
) -> int:
    width_percent = (work_area.width * 100) // width
    height_percent = (work_area.height * 100) // height
    return max(1, min(100, width_percent, height_percent))


__all__ = [
    "AnchorPlacement",
    "AnchorPlacementUnavailable",
    "AnchorRect",
    "place_conversation_capsule",
]