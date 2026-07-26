"""Strict atomic JSON persistence for non-sensitive desktop-pet settings."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import cast

from sjtuclaw.application.pet_settings import (
    PET_SETTINGS_SCHEMA_VERSION,
    PetSettings,
    PetSettingsLoadResult,
    PetSettingsRepository,
    PetSettingsWriteError,
)

_MAX_DOCUMENT_BYTES = 16 * 1024
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "window_x",
        "window_y",
        "always_on_top",
    }
)


class JsonPetSettingsRepository(PetSettingsRepository):
    """Store one exact versioned document without replacing invalid input."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> PetSettingsLoadResult:
        try:
            if self._path.stat().st_size > _MAX_DOCUMENT_BYTES:
                return _invalid_document_result()
            payload = self._path.read_bytes()
        except FileNotFoundError:
            return PetSettingsLoadResult(None, "none", True)
        except OSError:
            return PetSettingsLoadResult(
                None,
                "pet_settings_initialization_failed",
                False,
            )
        if len(payload) > _MAX_DOCUMENT_BYTES:
            return _invalid_document_result()
        try:
            loaded = cast(
                object,
                json.loads(
                    payload.decode("utf-8"),
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_strict_object_pairs,
                ),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            return _invalid_document_result()
        if not isinstance(loaded, dict) or not all(
            isinstance(key, str) for key in loaded
        ):
            return _invalid_document_result()
        document = cast(dict[str, object], loaded)
        schema_version = document.get("schema_version")
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            return _invalid_document_result()
        if schema_version != PET_SETTINGS_SCHEMA_VERSION:
            return PetSettingsLoadResult(
                None,
                "pet_settings_schema_unsupported",
                False,
            )
        try:
            if frozenset(document) != _ROOT_KEYS:
                raise ValueError("keys")
            settings = PetSettings(
                window_x=_integer(document["window_x"]),
                window_y=_integer(document["window_y"]),
                always_on_top=_boolean(document["always_on_top"]),
            )
        except (KeyError, TypeError, ValueError):
            return _invalid_document_result()
        return PetSettingsLoadResult(settings, "none", True)

    def save(self, settings: PetSettings) -> None:
        document = {
            "schema_version": PET_SETTINGS_SCHEMA_VERSION,
            "window_x": settings.window_x,
            "window_y": settings.window_y,
            "always_on_top": settings.always_on_top,
        }
        serialized = (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        payload = serialized.encode("utf-8")
        if len(payload) > _MAX_DOCUMENT_BYTES:
            raise PetSettingsWriteError(
                "The desktop-pet settings could not be written atomically."
            )

        file_descriptor: int | None = None
        temporary_path: Path | None = None
        write_failed = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                file_descriptor = None
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
            temporary_path = None
        except Exception:
            if file_descriptor is not None:
                with suppress(OSError):
                    os.close(file_descriptor)
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()
            write_failed = True
        if write_failed:
            raise PetSettingsWriteError(
                "The desktop-pet settings could not be written atomically."
            )


def _invalid_document_result() -> PetSettingsLoadResult:
    return PetSettingsLoadResult(
        None,
        "pet_settings_corrupted",
        False,
    )


def _reject_json_constant(value: str) -> None:
    del value
    raise ValueError("constant")


def _strict_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("integer")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("boolean")
    return value
