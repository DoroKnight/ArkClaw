"""Repository ports for non-sensitive provider metadata."""

from __future__ import annotations

from typing import Protocol

from arkclaw.domain.errors import ArkClawError
from arkclaw.domain.models import (
    CredentialBinding,
    CredentialId,
    ProfileId,
    ProviderProfile,
)


class ProviderMetadataError(ArkClawError):
    """Fixed-message failure at the provider metadata boundary."""


class ProviderMetadataNotFoundError(ProviderMetadataError):
    """Requested metadata does not exist."""


class ProviderMetadataConflictError(ProviderMetadataError):
    """Requested mutation conflicts with existing metadata."""


class ProviderMetadataReferenceError(ProviderMetadataError):
    """A profile or binding is still referenced."""


class ProviderMetadataCorruptedError(ProviderMetadataError):
    """Persisted provider metadata is invalid or damaged."""


class ProviderMetadataSchemaError(ProviderMetadataError):
    """Persisted provider metadata uses an unsupported schema."""


class ProviderMetadataWriteError(ProviderMetadataError):
    """Provider metadata could not be written atomically."""


class ProviderProfileRepository(Protocol):
    """Persist versioned, non-sensitive provider profiles."""

    def list_profiles(self) -> tuple[ProviderProfile, ...]: ...

    def get_profile(
        self,
        profile_id: ProfileId,
    ) -> ProviderProfile | None: ...

    def save_profile(self, profile: ProviderProfile) -> None: ...

    def delete_profile(self, profile_id: ProfileId) -> None: ...

    def get_active_profile_id(self) -> ProfileId | None: ...

    def set_active_profile_id(self, profile_id: ProfileId) -> None: ...


class CredentialBindingRepository(Protocol):
    """Persist non-sensitive credential authorization metadata."""

    def list_credential_bindings(
        self,
    ) -> tuple[CredentialBinding, ...]: ...

    def get_credential_binding(
        self,
        credential_id: CredentialId,
    ) -> CredentialBinding | None: ...

    def save_credential_binding(
        self,
        binding: CredentialBinding,
    ) -> None: ...

    def delete_credential_binding(
        self,
        credential_id: CredentialId,
    ) -> None: ...


class ProviderMetadataRepository(
    ProviderProfileRepository,
    CredentialBindingRepository,
    Protocol,
):
    """Combined document boundary for atomic reference validation."""
