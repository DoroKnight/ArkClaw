from __future__ import annotations

import pytest

from arkclaw.presentation.conversation_anchor import (
    AnchorPlacementUnavailable,
    AnchorRect,
    place_conversation_capsule,
)


def test_prefers_upper_side_when_it_fits() -> None:
    anchor = AnchorRect(300, 300, 200, 200)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (220, 120), work_area)

    assert placement.side == "upper"
    assert placement.rect.y + placement.rect.height <= anchor.y
    assert placement.rect.x >= work_area.x
    assert placement.rect.y >= work_area.y
    assert placement.rect.right <= work_area.right
    assert placement.rect.bottom <= work_area.bottom


def test_falls_back_below_when_upper_does_not_fit() -> None:
    anchor = AnchorRect(300, 10, 200, 100)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (220, 120), work_area)

    assert placement.side == "below"
    assert placement.rect.y >= anchor.y + anchor.height
    assert placement.rect.bottom <= work_area.bottom


def test_clamps_placement_into_work_area() -> None:
    anchor = AnchorRect(760, 560, 60, 40)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (220, 120), work_area)

    assert placement.rect.x >= work_area.x
    assert placement.rect.y >= work_area.y
    assert placement.rect.right <= work_area.right
    assert placement.rect.bottom <= work_area.bottom


def test_placement_does_not_overlap_anchor() -> None:
    anchor = AnchorRect(300, 200, 200, 150)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (240, 100), work_area)

    rect = placement.rect
    assert not _overlap(
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        anchor.x,
        anchor.y,
        anchor.width,
        anchor.height,
    )


def _overlap(
    x1: int,
    y1: int,
    w1: int,
    h1: int,
    x2: int,
    y2: int,
    w2: int,
    h2: int,
) -> bool:
    return not (
        x1 + w1 <= x2
        or x2 + w2 <= x1
        or y1 + h1 <= y2
        or y2 + h2 <= y1
    )

def test_falls_back_to_right_side_when_upper_and_below_do_not_fit() -> None:
    anchor = AnchorRect(100, 200, 200, 200)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (220, 300), work_area)

    assert placement.side == "right"
    assert placement.rect.x >= anchor.right
    assert _inside(placement.rect, work_area)
    assert not _overlap(
        placement.rect.x,
        placement.rect.y,
        placement.rect.width,
        placement.rect.height,
        anchor.x,
        anchor.y,
        anchor.width,
        anchor.height,
    )


def test_near_horizontal_edge_falls_back_without_anchor_overlap() -> None:
    anchor = AnchorRect(600, 200, 180, 200)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (220, 300), work_area)

    assert placement.side == "left"
    assert placement.rect.right <= anchor.x
    assert _inside(placement.rect, work_area)
    assert not _overlap(
        placement.rect.x,
        placement.rect.y,
        placement.rect.width,
        placement.rect.height,
        anchor.x,
        anchor.y,
        anchor.width,
        anchor.height,
    )


def test_reduces_size_instead_of_returning_out_of_work_area_rect() -> None:
    anchor = AnchorRect(300, 200, 200, 200)
    work_area = AnchorRect(0, 0, 800, 600)

    placement = place_conversation_capsule(anchor, (900, 700), work_area)

    assert placement.rect.width <= work_area.width
    assert placement.rect.height <= work_area.height
    assert _inside(placement.rect, work_area)
    assert not _overlap(
        placement.rect.x,
        placement.rect.y,
        placement.rect.width,
        placement.rect.height,
        anchor.x,
        anchor.y,
        anchor.width,
        anchor.height,
    )


def test_explicit_no_placement_when_anchor_blocks_every_position() -> None:
    anchor = AnchorRect(0, 0, 800, 600)
    work_area = AnchorRect(0, 0, 800, 600)

    with pytest.raises(AnchorPlacementUnavailable):
        place_conversation_capsule(anchor, (220, 120), work_area)


def _inside(rect: AnchorRect, work_area: AnchorRect) -> bool:
    return (
        rect.x >= work_area.x
        and rect.y >= work_area.y
        and rect.right <= work_area.right
        and rect.bottom <= work_area.bottom
    )
