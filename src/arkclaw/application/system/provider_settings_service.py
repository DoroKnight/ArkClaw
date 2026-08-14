"""Framework-neutral Provider settings application boundary."""

from __future__ import annotations

from dataclasses import dataclass

from arkclaw.application.system.provider_profile_repository import (
    ProviderMetadataRepository,
)
from arkclaw.application.system.provider_profile_service import (
    ActiveTurnCoordinator,
    ProviderFactoryBuilder,
    ProviderLifecycleState,
    ProviderProfileService,
    ProviderProfileServiceError,
)
from arkclaw.config.errors import SecretStoreError
from arkclaw.config.provider_profile_policy import (
    ProviderProfilePolicyError,
    validate_supported_credential_binding,
)
from arkclaw.config.secrets import SecretStore, SecretValue
from arkclaw.domain.models import (
    DEEPSEEK_PROVIDER_ID,
    FAKE_PROVIDER_ID,
    OPENAI_PROVIDER_ID,
    CredentialBinding,
    CredentialId,
    ProfileId,
    ProviderCapabilities,
    ProviderId,
    ProviderProfile,
)

_SETTINGS_PROVIDER_IDS = frozenset(
    {
        FAKE_PROVIDER_ID,
        OPENAI_PROVIDER_ID,
        DEEPSEEK_PROVIDER_ID,
    }
)


class ProviderSettingsServiceError(Exception):
    """Fixed-code error safe to map across the GUI boundary."""

    def __init__(self, safe_code: str, safe_message: str) -> None:
        self.safe_code = safe_code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True, slots=True)
class ProviderCapabilitiesView:
    """Non-sensitive Provider capability view."""

    streaming: bool
    tools: bool
    embeddings: bool
    continuation_mode: str
    protocol: str


@dataclass(frozen=True, slots=True)
class ProviderProfileView:
    """Non-sensitive profile data rendered by settings clients."""

    profile_id: str
    display_name: str
    provider_id: str
    model: str
    credential_id: str | None
    fixed_origin: str | None
    capabilities: ProviderCapabilitiesView
    is_runtime_profile: bool


@dataclass(frozen=True, slots=True)
class CredentialBindingView:
    """Credential metadata plus presence, never the credential value."""

    credential_id: str
    display_name: str
    provider_id: str
    fixed_origin: str
    configured: bool


@dataclass(frozen=True, slots=True)
class ProviderSettingsSnapshot:
    """Complete immutable and non-sensitive settings view."""

    profiles: tuple[ProviderProfileView, ...]
    credential_bindings: tuple[CredentialBindingView, ...]
    stored_active_profile_id: str | None
    runtime_profile_id: str | None
    provider_lifecycle: str
    runtime_state: str
    active_turn: bool
    cleanup_pending: bool


class ProviderSettingsService(ProviderProfileService):
    """Add credential-safe settings use cases to profile lifecycle management."""

    def __init__(
        self,
        repository: ProviderMetadataRepository,
        provider_factory_builder: ProviderFactoryBuilder,
        secret_store: SecretStore,
        *,
        turn_coordinator: ActiveTurnCoordinator | None = None,
    ) -> None:
        super().__init__(
            repository,
            provider_factory_builder,
            turn_coordinator=turn_coordinator,
        )
        self._settings_repository = repository
        self._settings_secret_store = secret_store

    def settings_snapshot(
        self,
        *,
        runtime_state: str,
        active_turn: bool,
    ) -> ProviderSettingsSnapshot:
        """Read settings only after an explicit UI command."""

        try:
            profiles = tuple(
                self._profile_view(profile)
                for profile in self.list_profiles()
                if profile.provider_id in _SETTINGS_PROVIDER_IDS
            )
            bindings = tuple(
                self._binding_view(binding)
                for binding in self._settings_repository.list_credential_bindings()
            )
            stored_active = self.get_active_profile_id()
            runtime_profile = self.runtime_profile_id
        except (ProviderProfileServiceError, SecretStoreError):
            raise ProviderSettingsServiceError(
                "provider_settings_unavailable",
                "Provider settings are unavailable.",
            ) from None
        except Exception:
            raise ProviderSettingsServiceError(
                "provider_settings_unavailable",
                "Provider settings are unavailable.",
            ) from None
        return ProviderSettingsSnapshot(
            profiles=profiles,
            credential_bindings=bindings,
            stored_active_profile_id=(
                None if stored_active is None else stored_active.value
            ),
            runtime_profile_id=(
                None if runtime_profile is None else runtime_profile.value
            ),
            provider_lifecycle=self.lifecycle_state.value,
            runtime_state=runtime_state,
            active_turn=active_turn,
            cleanup_pending=(
                self.lifecycle_state is ProviderLifecycleState.CLEANUP_PENDING
            ),
        )

    def create_settings_profile(
        self,
        *,
        provider_id: ProviderId,
        display_name: str,
        model: str,
        credential_id: CredentialId | None,
    ) -> ProviderProfile:
        self._require_mutation_allowed()
        self._require_settings_provider(provider_id)
        try:
            return self.create_profile(
                provider_id=provider_id,
                display_name=display_name,
                model=model,
                credential_id=credential_id,
            )
        except ProviderProfileServiceError:
            raise ProviderSettingsServiceError(
                "provider_profile_create_failed",
                "The Provider profile could not be created safely.",
            ) from None

    def update_settings_profile(
        self,
        profile_id: ProfileId,
        *,
        display_name: str,
        model: str,
        credential_id: CredentialId | None,
    ) -> ProviderProfile:
        self._require_mutation_allowed()
        existing = self.get_profile(profile_id)
        if existing is None or existing.provider_id not in _SETTINGS_PROVIDER_IDS:
            raise ProviderSettingsServiceError(
                "provider_profile_not_found",
                "The Provider profile does not exist.",
            )
        if self.runtime_profile_id == profile_id and (
            existing.model != model
            or existing.credential_id != credential_id
        ):
            raise ProviderSettingsServiceError(
                "active_profile_update_requires_switch",
                "Switch away from the active Profile before changing its model "
                "or credential.",
            )
        try:
            return self.update_profile(
                profile_id,
                display_name=display_name,
                model=model,
                credential_id=credential_id,
            )
        except ProviderProfileServiceError:
            raise ProviderSettingsServiceError(
                "provider_profile_update_failed",
                "The Provider profile could not be updated safely.",
            ) from None

    def delete_settings_profile(self, profile_id: ProfileId) -> None:
        self._require_mutation_allowed()
        if self.runtime_profile_id == profile_id:
            raise ProviderSettingsServiceError(
                "active_profile_delete_rejected",
                "The active Provider profile cannot be deleted.",
            )
        try:
            self.delete_profile(profile_id)
        except ProviderProfileServiceError:
            raise ProviderSettingsServiceError(
                "provider_profile_delete_failed",
                "The Provider profile could not be deleted safely.",
            ) from None

    def save_credential(
        self,
        credential_id: CredentialId,
        secret: str,
    ) -> None:
        self._require_mutation_allowed()
        self._require_supported_binding(credential_id)
        self._require_inactive_credential(credential_id)
        secret_value: SecretValue | None = None
        failure: ProviderSettingsServiceError | None = None
        try:
            secret_value = SecretValue(secret)
            self._settings_secret_store.set_secret(
                credential_id,
                secret_value,
            )
        except (SecretStoreError, ValueError):
            failure = ProviderSettingsServiceError(
                "credential_save_failed",
                "The credential could not be saved safely.",
            )
        except Exception:
            failure = ProviderSettingsServiceError(
                "credential_save_failed",
                "The credential could not be saved safely.",
            )
        finally:
            secret_value = None
        if failure is not None:
            raise failure from None

    def delete_credential(self, credential_id: CredentialId) -> None:
        self._require_mutation_allowed()
        self._require_supported_binding(credential_id)
        self._require_inactive_credential(credential_id)
        failure: ProviderSettingsServiceError | None = None
        try:
            self._settings_secret_store.delete_secret(credential_id)
        except SecretStoreError:
            failure = ProviderSettingsServiceError(
                "credential_delete_failed",
                "The credential could not be deleted safely.",
            )
        except Exception:
            failure = ProviderSettingsServiceError(
                "credential_delete_failed",
                "The credential could not be deleted safely.",
            )
        if failure is not None:
            raise failure from None

    def _profile_view(self, profile: ProviderProfile) -> ProviderProfileView:
        return ProviderProfileView(
            profile_id=profile.profile_id.value,
            display_name=profile.display_name,
            provider_id=profile.provider_id.value,
            model=profile.model,
            credential_id=(
                None
                if profile.credential_id is None
                else profile.credential_id.value
            ),
            fixed_origin=profile.origin,
            capabilities=self._capabilities_view(profile.capabilities),
            is_runtime_profile=self.runtime_profile_id == profile.profile_id,
        )

    def _binding_view(
        self,
        binding: CredentialBinding,
    ) -> CredentialBindingView:
        configured = False
        failure: ProviderSettingsServiceError | None = None
        try:
            validate_supported_credential_binding(binding)
            configured = self._settings_secret_store.has_secret(
                binding.credential_id
            )
        except (ProviderProfilePolicyError, SecretStoreError):
            failure = ProviderSettingsServiceError(
                "credential_status_unavailable",
                "Credential status is unavailable.",
            )
        except Exception:
            failure = ProviderSettingsServiceError(
                "credential_status_unavailable",
                "Credential status is unavailable.",
            )
        if failure is not None:
            raise failure from None
        return CredentialBindingView(
            credential_id=binding.credential_id.value,
            display_name=binding.display_name,
            provider_id=binding.provider_id.value,
            fixed_origin=binding.allowed_origin,
            configured=configured,
        )

    @staticmethod
    def _capabilities_view(
        capabilities: ProviderCapabilities,
    ) -> ProviderCapabilitiesView:
        return ProviderCapabilitiesView(
            streaming=capabilities.streaming,
            tools=capabilities.tools,
            embeddings=capabilities.embeddings,
            continuation_mode=capabilities.continuation_mode.value,
            protocol=capabilities.protocol.value,
        )

    def _require_mutation_allowed(self) -> None:
        if self.lifecycle_state is ProviderLifecycleState.CLEANUP_PENDING:
            raise ProviderSettingsServiceError(
                "provider_cleanup_pending",
                "Provider cleanup must complete before settings can change.",
            )
        if self.lifecycle_state in {
            ProviderLifecycleState.SWITCHING,
            ProviderLifecycleState.CLOSED,
        }:
            raise ProviderSettingsServiceError(
                "provider_settings_mutation_blocked",
                "Provider settings cannot change in the current runtime state.",
            )

    @staticmethod
    def _require_settings_provider(provider_id: ProviderId) -> None:
        if provider_id not in _SETTINGS_PROVIDER_IDS:
            raise ProviderSettingsServiceError(
                "unsupported_provider_profile",
                "Only reviewed built-in Providers can be configured.",
            )

    def _require_supported_binding(
        self,
        credential_id: CredentialId,
    ) -> CredentialBinding:
        binding = self._settings_repository.get_credential_binding(
            credential_id
        )
        if binding is None:
            raise ProviderSettingsServiceError(
                "credential_binding_not_found",
                "The credential binding does not exist.",
            )
        try:
            validate_supported_credential_binding(binding)
        except ProviderProfilePolicyError:
            raise ProviderSettingsServiceError(
                "credential_binding_rejected",
                "The credential binding is not permitted.",
            ) from None
        return binding

    def _require_inactive_credential(
        self,
        credential_id: CredentialId,
    ) -> None:
        runtime_profile = self.runtime_profile_snapshot
        if (
            runtime_profile is not None
            and runtime_profile.credential_id == credential_id
        ):
            raise ProviderSettingsServiceError(
                "active_profile_credential_change_requires_switch",
                "Switch away from the active Profile before changing its "
                "credential.",
            )
