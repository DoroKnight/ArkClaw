"""Pure geometry and display-workspace selection for the desktop pet."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Size:
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Window dimensions must be positive.")


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Workspace dimensions must be positive.")

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)


def physical_to_logical_rect(rect: Rect, scale_factor: float) -> Rect:
    """Convert physical display pixels to Qt-style logical coordinates."""

    if scale_factor <= 0:
        raise ValueError("The display scale factor must be positive.")
    return Rect(
        rect.x / scale_factor,
        rect.y / scale_factor,
        rect.width / scale_factor,
        rect.height / scale_factor,
    )


def clamp_window_position(
    position: Point,
    window_size: Size,
    workspace: Rect,
) -> Point:
    """Keep the whole window in a display's available workspace."""

    max_x = max(workspace.x, workspace.right - window_size.width)
    max_y = max(workspace.y, workspace.bottom - window_size.height)
    return Point(
        min(max(position.x, workspace.x), max_x),
        min(max(position.y, workspace.y), max_y),
    )


def clamp_drag_position(
    position: Point,
    window_size: Size,
    workspace: Rect,
    *,
    recoverable_strip: float = 16.0,
) -> Point:
    """Keep a draggable window recoverable without constraining vertical motion."""

    if recoverable_strip <= 0.0 or recoverable_strip > window_size.width:
        raise ValueError("Recoverable drag strip is invalid.")
    minimum_x = workspace.x - (window_size.width - recoverable_strip)
    maximum_x = workspace.right - recoverable_strip
    return Point(
        min(max(position.x, minimum_x), maximum_x),
        position.y,
    )


def select_workspace(
    position: Point,
    window_size: Size,
    workspaces: tuple[Rect, ...],
) -> Rect:
    """Choose the display with most overlap, then the nearest display."""

    if not workspaces:
        raise ValueError("At least one display workspace is required.")
    window = Rect(
        position.x,
        position.y,
        window_size.width,
        window_size.height,
    )
    overlaps = tuple(_overlap_area(window, workspace) for workspace in workspaces)
    greatest = max(overlaps)
    if greatest > 0:
        return workspaces[overlaps.index(greatest)]
    center = window.center
    return min(
        workspaces,
        key=lambda workspace: hypot(
            center.x - workspace.center.x,
            center.y - workspace.center.y,
        ),
    )


def _overlap_area(first: Rect, second: Rect) -> float:
    width = max(
        0.0,
        min(first.right, second.right) - max(first.x, second.x),
    )
    height = max(
        0.0,
        min(first.bottom, second.bottom) - max(first.y, second.y),
    )
    return width * height
