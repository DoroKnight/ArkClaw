"""Framework-neutral application model for a Spine 3.8 catalog."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

from sjtuclaw.infrastructure.spine38_native import Spine38CatalogNativePort


class Spine38CatalogError(RuntimeError):
    """Fixed application error for an absent or ambiguous exact name."""

    def __init__(self) -> None:
        super().__init__("spine38_animation_not_exactly_once")


@dataclass(frozen=True, slots=True)
class Spine38AnimationInfo:
    name: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class Spine38Bounds:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Spine38Catalog:
    animations: tuple[Spine38AnimationInfo, ...]

    def require_animation(self, requested_name: str) -> Spine38AnimationInfo:
        """Return one exact, case-sensitive match without aliases or fallback."""

        matches = tuple(
            animation
            for animation in self.animations
            if animation.name == requested_name
        )
        if len(matches) != 1:
            raise Spine38CatalogError
        return matches[0]


class Spine38Runtime:
    """Own a native catalog port and publish immutable application snapshots."""

    def __init__(self, native_port: Spine38CatalogNativePort) -> None:
        self._native_port = native_port
        self._closed = False
        try:
            self.catalog = Spine38Catalog(
                tuple(
                    Spine38AnimationInfo(
                        animation.name,
                        animation.duration_seconds,
                    )
                    for animation in native_port.catalog()
                )
            )
            self.skins = tuple(native_port.skins())
            native_bounds = native_port.setup_bounds()
            self.setup_bounds = Spine38Bounds(
                native_bounds.x,
                native_bounds.y,
                native_bounds.width,
                native_bounds.height,
            )
        except BaseException:
            self._closed = True
            with suppress(Exception):
                native_port.close()
            raise

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Release the owned native port once."""

        if self._closed:
            return
        self._closed = True
        self._native_port.close()
