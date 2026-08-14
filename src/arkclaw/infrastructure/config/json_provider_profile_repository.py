"""Atomic JSON persistence for non-sensitive provider metadata."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol, cast

from arkclaw.application.provider_profile_repository import (
    ProviderMetadataConflictError,
    ProviderMetadataCorruptedError,
    ProviderMetadataNotFoundError,
    ProviderMetadataReferenceError,
    ProviderMetadataRepository,
    ProviderMetadataSchemaError,
    ProviderMetadataWriteError,
)
from arkclaw.config.provider_profile_policy import (
    ProviderProfilePolicyError,
    validate_supported_credential_binding,
    validate_supported_profile,
)
from arkclaw.domain.models import (
    ApiProtocol,
    ContinuationMode,
    CredentialBinding,
    CredentialId,
    ProfileId,
    ProviderCapabilities,
    ProviderId,
    ProviderProfile,
)

PROVIDER_METADATA_SCHEMA_VERSION = 1
_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_MAX_RECORDS = 1_000
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "active_profile_id",
        "profiles",
        "credential_bindings",
    }
)
_PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "profile_id",
        "display_name",
        "provider_id",
        "protocol",
        "base_url",
        "model",
        "credential_id",
        "capabilities",
        "enabled",
    }
)
_CAPABILITY_KEYS = frozenset(
    {
        "streaming",
        "tools",
        "embeddings",
        "continuation_mode",
        "protocol",
    }
)
_BINDING_KEYS = frozenset(
    {
        "schema_version",
        "credential_id",
        "provider_id",
        "allowed_origin",
        "display_name",
    }
)
_SENSITIVE_METADATA_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credentialblob",
    "secretvalue",
    "bearer ",
    "sk-",
)


class ProviderProfileDocumentMigrator(Protocol):
    """Explicitly migrate one older document to the current schema."""

    def migrate(
        self,
        document: Mapping[str, object],
        *,
        target_version: int,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class _Snapshot:
    active_profile_id: ProfileId | None = None
    profiles: tuple[ProviderProfile, ...] = ()
    credential_bindings: tuple[CredentialBinding, ...] = ()


class JsonProviderProfileRepository(ProviderMetadataRepository):
    """Store one strict, versioned document with atomic replacement."""

    def __init__(
        self,
        path: Path,
        *,
        migrator: ProviderProfileDocumentMigrator | None = None,
    ) -> None:
        self._path = path
        self._migrator = migrator
        self._lock = RLock()

    def list_profiles(self) -> tuple[ProviderProfile, ...]:
        with self._lock:
            return self._read_snapshot().profiles

    def get_profile(
        self,
        profile_id: ProfileId,
    ) -> ProviderProfile | None:
        with self._lock:
            return next(
                (
                    profile
                    for profile in self._read_snapshot().profiles
                    if profile.profile_id == profile_id
                ),
                None,
            )

    def save_profile(self, profile: ProviderProfile) -> None:
        invalid_profile = False
        try:
            validate_supported_profile(profile)
            _reject_sensitive_metadata(profile.display_name, profile.model)
        except (ProviderProfilePolicyError, ValueError, TypeError):
            invalid_profile = True
        if invalid_profile:
            raise ProviderMetadataConflictError(
                "The provider profile cannot be persisted safely."
            )
        with self._lock:
            snapshot = self._read_snapshot()
            binding = _binding_for_profile(
                profile,
                snapshot.credential_bindings,
            )
            if profile.credential_id is not None and binding is None:
                raise ProviderMetadataReferenceError(
                    "The provider profile credential binding is missing."
                )
            profiles = list(snapshot.profiles)
            existing_index = next(
                (
                    index
                    for index, item in enumerate(profiles)
                    if item.profile_id == profile.profile_id
                ),
                None,
            )
            if existing_index is None:
                profiles.append(profile)
            else:
                existing = profiles[existing_index]
                if existing.provider_id != profile.provider_id:
                    raise ProviderMetadataConflictError(
                        "The profile identifier belongs to another provider."
                    )
                profiles[existing_index] = profile
            self._write_snapshot(
                _Snapshot(
                    active_profile_id=snapshot.active_profile_id,
                    profiles=_sorted_profiles(profiles),
                    credential_bindings=snapshot.credential_bindings,
                )
            )

    def delete_profile(self, profile_id: ProfileId) -> None:
        with self._lock:
            snapshot = self._read_snapshot()
            if snapshot.active_profile_id == profile_id:
                raise ProviderMetadataReferenceError(
                    "The active provider profile cannot be deleted."
                )
            profiles = tuple(
                profile
                for profile in snapshot.profiles
                if profile.profile_id != profile_id
            )
            if len(profiles) == len(snapshot.profiles):
                raise ProviderMetadataNotFoundError(
                    "The provider profile does not exist."
                )
            self._write_snapshot(
                _Snapshot(
                    active_profile_id=snapshot.active_profile_id,
                    profiles=profiles,
                    credential_bindings=snapshot.credential_bindings,
                )
            )

    def get_active_profile_id(self) -> ProfileId | None:
        with self._lock:
            return self._read_snapshot().active_profile_id

    def set_active_profile_id(self, profile_id: ProfileId) -> None:
        with self._lock:
            snapshot = self._read_snapshot()
            profile = next(
                (
                    item
                    for item in snapshot.profiles
                    if item.profile_id == profile_id
                ),
                None,
            )
            if profile is None:
                raise ProviderMetadataNotFoundError(
                    "The provider profile does not exist."
                )
            if not profile.enabled:
                raise ProviderMetadataConflictError(
                    "A disabled provider profile cannot become active."
                )
            self._write_snapshot(
                _Snapshot(
                    active_profile_id=profile_id,
                    profiles=snapshot.profiles,
                    credential_bindings=snapshot.credential_bindings,
                )
            )

    def list_credential_bindings(
        self,
    ) -> tuple[CredentialBinding, ...]:
        with self._lock:
            return self._read_snapshot().credential_bindings

    def get_credential_binding(
        self,
        credential_id: CredentialId,
    ) -> CredentialBinding | None:
        with self._lock:
            return next(
                (
                    binding
                    for binding in self._read_snapshot().credential_bindings
                    if binding.credential_id == credential_id
                ),
                None,
            )

    def save_credential_binding(
        self,
        binding: CredentialBinding,
    ) -> None:
        invalid_binding = False
        try:
            validate_supported_credential_binding(binding)
            _reject_sensitive_metadata(binding.display_name)
        except (ProviderProfilePolicyError, ValueError, TypeError):
            invalid_binding = True
        if invalid_binding:
            raise ProviderMetadataConflictError(
                "The credential binding cannot be persisted safely."
            )
        with self._lock:
            snapshot = self._read_snapshot()
            bindings = list(snapshot.credential_bindings)
            existing_index = next(
                (
                    index
                    for index, item in enumerate(bindings)
                    if item.credential_id == binding.credential_id
                ),
                None,
            )
            if existing_index is None:
                bindings.append(binding)
            else:
                existing = bindings[existing_index]
                if (
                    existing.provider_id != binding.provider_id
                    or existing.allowed_origin != binding.allowed_origin
                ):
                    raise ProviderMetadataConflictError(
                        "The credential identifier is already bound."
                    )
                bindings[existing_index] = binding
            self._write_snapshot(
                _Snapshot(
                    active_profile_id=snapshot.active_profile_id,
                    profiles=snapshot.profiles,
                    credential_bindings=_sorted_bindings(bindings),
                )
            )

    def delete_credential_binding(
        self,
        credential_id: CredentialId,
    ) -> None:
        with self._lock:
            snapshot = self._read_snapshot()
            if any(
                profile.credential_id == credential_id
                for profile in snapshot.profiles
            ):
                raise ProviderMetadataReferenceError(
                    "The credential binding is still referenced."
                )
            bindings = tuple(
                binding
                for binding in snapshot.credential_bindings
                if binding.credential_id != credential_id
            )
            if len(bindings) == len(snapshot.credential_bindings):
                raise ProviderMetadataNotFoundError(
                    "The credential binding does not exist."
                )
            self._write_snapshot(
                _Snapshot(
                    active_profile_id=snapshot.active_profile_id,
                    profiles=snapshot.profiles,
                    credential_bindings=bindings,
                )
            )

    def _read_snapshot(self) -> _Snapshot:
        read_failed = False
        payload = b""
        try:
            payload = self._path.read_bytes()
        except FileNotFoundError:
            return _Snapshot()
        except OSError:
            read_failed = True
        if read_failed:
            raise ProviderMetadataCorruptedError(
                "The provider metadata could not be read safely."
            )
        if len(payload) > _MAX_DOCUMENT_BYTES:
            raise ProviderMetadataCorruptedError(
                "The provider metadata document is too large."
            )
        parse_failed = False
        document: dict[str, object] = {}
        try:
            loaded = cast(object, json.loads(payload.decode("utf-8")))
            document = _object_mapping(loaded)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            parse_failed = True
        if parse_failed:
            raise ProviderMetadataCorruptedError(
                "The provider metadata document is corrupted."
            )
        schema_version = document.get("schema_version")
        if schema_version != PROVIDER_METADATA_SCHEMA_VERSION:
            if self._migrator is None:
                raise ProviderMetadataSchemaError(
                    "The provider metadata schema is not supported."
                )
            migration_failed = False
            migrated_document: dict[str, object] = {}
            try:
                migrated_document = dict(
                    self._migrator.migrate(
                        document,
                        target_version=PROVIDER_METADATA_SCHEMA_VERSION,
                    )
                )
            except Exception:
                migration_failed = True
            if migration_failed:
                raise ProviderMetadataSchemaError(
                    "The provider metadata migration failed safely."
                )
            document = migrated_document
            if (
                document.get("schema_version")
                != PROVIDER_METADATA_SCHEMA_VERSION
            ):
                raise ProviderMetadataSchemaError(
                    "The provider metadata migration is incomplete."
                )
        return _parse_snapshot(document)

    def _write_snapshot(self, snapshot: _Snapshot) -> None:
        document = _snapshot_document(snapshot)
        serialized = (
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
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
            raise ProviderMetadataWriteError(
                "The provider metadata could not be written atomically."
            )


def _parse_snapshot(document: Mapping[str, object]) -> _Snapshot:
    parsed_snapshot: _Snapshot | None = None
    try:
        _require_exact_keys(document, _ROOT_KEYS)
        active_raw = document["active_profile_id"]
        active_profile_id = (
            None if active_raw is None else ProfileId(_string(active_raw))
        )
        profile_values = _object_list(document["profiles"])
        binding_values = _object_list(document["credential_bindings"])
        if (
            len(profile_values) > _MAX_RECORDS
            or len(binding_values) > _MAX_RECORDS
        ):
            raise ValueError("record limit")
        profiles = tuple(_parse_profile(value) for value in profile_values)
        bindings = tuple(_parse_binding(value) for value in binding_values)
        if len({item.profile_id for item in profiles}) != len(profiles):
            raise ValueError("duplicate profile")
        if len({item.credential_id for item in bindings}) != len(bindings):
            raise ValueError("duplicate binding")
        for profile in profiles:
            validate_supported_profile(profile)
            _reject_sensitive_metadata(profile.display_name, profile.model)
            binding = _binding_for_profile(profile, bindings)
            if profile.credential_id is not None and binding is None:
                raise ValueError("missing binding")
        for binding in bindings:
            validate_supported_credential_binding(binding)
            _reject_sensitive_metadata(binding.display_name)
        if active_profile_id is not None and all(
            profile.profile_id != active_profile_id
            for profile in profiles
        ):
            raise ValueError("missing active profile")
        parsed_snapshot = _Snapshot(
            active_profile_id=active_profile_id,
            profiles=_sorted_profiles(profiles),
            credential_bindings=_sorted_bindings(bindings),
        )
    except (ProviderProfilePolicyError, KeyError, TypeError, ValueError):
        pass
    if parsed_snapshot is None:
        raise ProviderMetadataCorruptedError(
            "The provider metadata document is corrupted."
        )
    return parsed_snapshot


def _parse_profile(value: object) -> ProviderProfile:
    item = _object_mapping(value)
    _require_exact_keys(item, _PROFILE_KEYS)
    capabilities = _parse_capabilities(item["capabilities"])
    credential_raw = item["credential_id"]
    base_url_raw = item["base_url"]
    if base_url_raw is not None and not isinstance(base_url_raw, str):
        raise TypeError("base_url")
    return ProviderProfile(
        profile_id=ProfileId(_string(item["profile_id"])),
        display_name=_string(item["display_name"]),
        provider_id=ProviderId(_string(item["provider_id"])),
        protocol=ApiProtocol(_string(item["protocol"])),
        base_url=base_url_raw,
        model=_string(item["model"]),
        credential_id=(
            None
            if credential_raw is None
            else CredentialId(_string(credential_raw))
        ),
        capabilities=capabilities,
        enabled=_boolean(item["enabled"]),
        schema_version=_integer(item["schema_version"]),
    )


def _parse_capabilities(value: object) -> ProviderCapabilities:
    item = _object_mapping(value)
    _require_exact_keys(item, _CAPABILITY_KEYS)
    return ProviderCapabilities(
        streaming=_boolean(item["streaming"]),
        tools=_boolean(item["tools"]),
        embeddings=_boolean(item["embeddings"]),
        continuation_mode=ContinuationMode(
            _string(item["continuation_mode"])
        ),
        protocol=ApiProtocol(_string(item["protocol"])),
    )


def _parse_binding(value: object) -> CredentialBinding:
    item = _object_mapping(value)
    _require_exact_keys(item, _BINDING_KEYS)
    return CredentialBinding(
        credential_id=CredentialId(_string(item["credential_id"])),
        provider_id=ProviderId(_string(item["provider_id"])),
        allowed_origin=_string(item["allowed_origin"]),
        display_name=_string(item["display_name"]),
        schema_version=_integer(item["schema_version"]),
    )


def _snapshot_document(snapshot: _Snapshot) -> dict[str, object]:
    return {
        "schema_version": PROVIDER_METADATA_SCHEMA_VERSION,
        "active_profile_id": (
            None
            if snapshot.active_profile_id is None
            else snapshot.active_profile_id.value
        ),
        "profiles": [
            {
                "schema_version": profile.schema_version,
                "profile_id": profile.profile_id.value,
                "display_name": profile.display_name,
                "provider_id": profile.provider_id.value,
                "protocol": profile.protocol.value,
                "base_url": profile.base_url,
                "model": profile.model,
                "credential_id": (
                    None
                    if profile.credential_id is None
                    else profile.credential_id.value
                ),
                "capabilities": {
                    "streaming": profile.capabilities.streaming,
                    "tools": profile.capabilities.tools,
                    "embeddings": profile.capabilities.embeddings,
                    "continuation_mode": (
                        profile.capabilities.continuation_mode.value
                    ),
                    "protocol": profile.capabilities.protocol.value,
                },
                "enabled": profile.enabled,
            }
            for profile in snapshot.profiles
        ],
        "credential_bindings": [
            {
                "schema_version": binding.schema_version,
                "credential_id": binding.credential_id.value,
                "provider_id": binding.provider_id.value,
                "allowed_origin": binding.allowed_origin,
                "display_name": binding.display_name,
            }
            for binding in snapshot.credential_bindings
        ],
    }


def _binding_for_profile(
    profile: ProviderProfile,
    bindings: tuple[CredentialBinding, ...],
) -> CredentialBinding | None:
    if profile.credential_id is None:
        return None
    return next(
        (
            binding
            for binding in bindings
            if (
                binding.credential_id == profile.credential_id
                and binding.provider_id == profile.provider_id
                and binding.allowed_origin == profile.origin
            )
        ),
        None,
    )


def _sorted_profiles(
    profiles: list[ProviderProfile] | tuple[ProviderProfile, ...],
) -> tuple[ProviderProfile, ...]:
    return tuple(sorted(profiles, key=lambda item: item.profile_id.value))


def _sorted_bindings(
    bindings: list[CredentialBinding] | tuple[CredentialBinding, ...],
) -> tuple[CredentialBinding, ...]:
    return tuple(sorted(bindings, key=lambda item: item.credential_id.value))


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError("mapping")
    return cast(dict[str, object], value)


def _object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("list")
    return cast(list[object], value)


def _require_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
) -> None:
    if frozenset(value) != expected:
        raise ValueError("keys")


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("string")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("boolean")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("integer")
    return value


def _reject_sensitive_metadata(*values: str) -> None:
    if any(
        marker in value.casefold()
        for value in values
        for marker in _SENSITIVE_METADATA_MARKERS
    ):
        raise ValueError("sensitive metadata")
