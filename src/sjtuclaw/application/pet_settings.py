"""Framework-independent model and repository port for desktop-pet settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sjtuclaw.domain.errors import SJTUClawError

PET_SETTINGS_SCHEMA_VERSION = 1
PET_SETTINGS_COORDINATE_LIMIT = 1_000_000


@dataclass(frozen=True, slots=True)
class PetSettings:
    """The complete non-sensitive desktop-pet settings document."""

    window_x: int
    window_y: int
    always_on_top: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.window_x, bool)
            or not isinstance(self.window_x, int)
            or isinstance(self.window_y, bool)
            or not isinstance(self.window_y, int)
            or not isinstance(self.always_on_top, bool)
            or abs(self.window_x) > PET_SETTINGS_COORDINATE_LIMIT
            or abs(self.window_y) > PET_SETTINGS_COORDINATE_LIMIT
        ):
            raise ValueError("The desktop-pet settings are invalid.")


@dataclass(frozen=True, slots=True)
class PetSettingsLoadResult:
    """Return safe defaults metadata without exposing raw persisted content."""

    settings: PetSettings | None
    safe_code: str
    write_allowed: bool


class PetSettingsError(SJTUClawError):
    """Fixed-message failure at the desktop-pet settings boundary."""


class PetSettingsWriteError(PetSettingsError):
    """The settings document could not be replaced atomically."""


class PetSettingsRepository(Protocol):
    """Persist only the non-sensitive desktop-pet presentation settings."""

    def load(self) -> PetSettingsLoadResult: ...

    def save(self, settings: PetSettings) -> None: ...
