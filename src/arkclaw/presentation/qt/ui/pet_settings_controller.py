"""Qt composition boundary for non-sensitive desktop-pet settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

from arkclaw.application.pet.pet_settings import (
    PetSettings,
    PetSettingsLoadResult,
    PetSettingsRepository,
)
from arkclaw.infrastructure.config.json_pet_settings_repository import (
    JsonPetSettingsRepository,
)

_PET_SETTINGS_FILENAME = "pet_settings.json"


class PetSettingsController:
    """Load once and save once without exposing filesystem failures to Qt."""

    def __init__(
        self,
        repository: PetSettingsRepository | None,
    ) -> None:
        self._repository = repository
        self._load_result: PetSettingsLoadResult | None = None
        self._load_count = 0
        self._save_attempted = False
        self._save_count = 0
        self._safe_code = "none"
        self._write_blocked = repository is None

    @classmethod
    def initialization_failed(cls) -> PetSettingsController:
        """Build an inert controller after optional setup failed."""

        controller = cls(None)
        controller._load_result = PetSettingsLoadResult(
            None,
            "pet_settings_initialization_failed",
            False,
        )
        controller._safe_code = "pet_settings_initialization_failed"
        return controller

    @property
    def safe_code(self) -> str:
        return self._safe_code

    @property
    def save_count(self) -> int:
        return self._save_count

    @property
    def load_count(self) -> int:
        return self._load_count

    @property
    def write_allowed(self) -> bool:
        return (
            self.load_once().write_allowed
            and not self._write_blocked
            and not self._save_attempted
        )

    def load_once(self) -> PetSettingsLoadResult:
        if self._load_result is None:
            self._load_count += 1
            if self._repository is None:
                self._load_result = PetSettingsLoadResult(
                    None,
                    "pet_settings_initialization_failed",
                    False,
                )
                self._safe_code = self._load_result.safe_code
                return self._load_result
            try:
                self._load_result = self._repository.load()
            except Exception:
                self._load_result = PetSettingsLoadResult(
                    None,
                    "pet_settings_initialization_failed",
                    False,
                )
                self._write_blocked = True
            self._safe_code = self._load_result.safe_code
        return self._load_result

    def record_restore_failure(self) -> None:
        self._safe_code = "pet_settings_restore_failed"
        self._write_blocked = True

    def record_snapshot_failure(self) -> None:
        self._safe_code = "pet_settings_snapshot_failed"
        self._write_blocked = True
        self._save_attempted = True

    def save_once(self, settings: PetSettings) -> str:
        if self._save_attempted:
            return self._safe_code
        self._save_attempted = True
        load_result = self.load_once()
        if not load_result.write_allowed or self._write_blocked:
            return self._safe_code
        if self._repository is None:
            self._safe_code = "pet_settings_initialization_failed"
            return self._safe_code
        try:
            self._repository.save(settings)
        except Exception:
            self._safe_code = "pet_settings_write_failed"
            return self._safe_code
        self._save_count += 1
        self._safe_code = "none"
        return self._safe_code


def default_pet_settings_path() -> Path:
    """Return the fixed per-user Qt application-data settings path."""

    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not location:
        raise RuntimeError("The desktop-pet settings location is unavailable.")
    return Path(location) / _PET_SETTINGS_FILENAME


def create_production_pet_settings_controller() -> PetSettingsController:
    """Construct the production controller without reading its document."""

    return PetSettingsController(
        JsonPetSettingsRepository(default_pet_settings_path())
    )
