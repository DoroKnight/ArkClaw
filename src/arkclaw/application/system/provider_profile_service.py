"""Application service for provider metadata and safe runtime switching."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from arkclaw.application.system.provider_profile_repository import (
    ProviderMetadataError,
    ProviderMetadataRepository,
)
from arkclaw.config.provider_profile_policy import (
    ProviderProfilePolicyError,
    build_supported_credential_binding,
    build_supported_profile,
    builtin_managed_credential_bindings,
    builtin_managed_profiles,
)
from arkclaw.domain.errors import ArkClawError
from arkclaw.domain.events import LLMEvent, LLMEventType
from arkclaw.domain.models import (
    FAKE_DEFAULT_PROFILE_ID,
    CredentialBinding,
    CredentialId,
    Embedding,
    LLMRequest,
    ProfileId,
    ProviderCapabilities,
    ProviderContinuation,
    ProviderId,
    ProviderProfile,
)
from arkclaw.domain.ports import LLMProvider


class ProviderProfileServiceError(ArkClawError):
    """Fixed-message failure at the profile management boundary."""


class ActiveTurnHandling(Enum):
    """An explicit upper-layer decision for in-flight Agent turns."""

    CANCEL_ACTIVE = "cancel_active"
    WAIT_FOR_ACTIVE = "wait_for_active"


class ProviderLifecycleState(Enum):
    """Observable lifecycle state of the managed Provider slot."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    SWITCHING = "switching"
    CLEANUP_PENDING = "cleanup_pending"
    CLOSED = "closed"


class ActiveTurnCoordinator(Protocol):
    """Quiesce routing before an active Provider is closed."""

    async def prepare_for_provider_switch(
        self,
        *,
        old_profile_id: ProfileId,
        new_profile_id: ProfileId,
        handling: ActiveTurnHandling,
    ) -> None: ...


class _ProviderFactoryPort(Protocol):
    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider: ...


class ProviderFactoryBuilder(Protocol):
    """Build a ProviderFactory with the latest persisted bindings."""

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _ProviderFactoryPort: ...


@dataclass(frozen=True, slots=True)
class ProviderActivationOptions:
    timeout_seconds: float
    max_retries: int
    stream: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError(
                "timeout_seconds must be a finite positive number"
            )
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if not isinstance(self.stream, bool):
            raise TypeError("stream must be a boolean")


async def _close_managed_provider_stream(
    stream: AsyncIterator[LLMEvent],
) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


class _ManagedProvider:
    """Revocable routing handle around an unchanged Provider adapter."""

    def __init__(
        self,
        delegate: LLMProvider,
        profile_id: ProfileId,
        expected_provider_name: str,
    ) -> None:
        self._delegate = delegate
        self._profile_id = profile_id
        self._expected_provider_name = expected_provider_name
        self._accepting_requests = True

    @property
    def name(self) -> str:
        return self._delegate.name

    def capabilities(self) -> ProviderCapabilities:
        return self._delegate.capabilities()

    async def generate_stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[LLMEvent]:
        if not self._accepting_requests:
            yield LLMEvent.failure(
                "provider_switching",
                "The Provider is not accepting new requests.",
            )
            return
        continuation = request.continuation
        if continuation is not None and (
            continuation.profile_id is None
            or continuation.profile_id != self._profile_id
            or continuation.provider_name
            != self._expected_provider_name
        ):
            yield LLMEvent.failure(
                "provider_continuation_mismatch",
                "The continuation does not belong to the active profile.",
            )
            return
        stream = self._delegate.generate_stream(request)
        try:
            async for event in stream:
                if (
                    event.type is not LLMEventType.COMPLETED
                    or event.continuation is None
                ):
                    yield event
                    continue
                returned_continuation = event.continuation
                if (
                    returned_continuation.provider_name
                    != self._expected_provider_name
                    or (
                        returned_continuation.profile_id is not None
                        and returned_continuation.profile_id
                        != self._profile_id
                    )
                ):
                    yield LLMEvent.failure(
                        "provider_continuation_mismatch",
                        "The Provider returned continuation state for "
                        "a different profile.",
                    )
                    return
                if returned_continuation.profile_id is None:
                    returned_continuation = replace(
                        returned_continuation,
                        profile_id=self._profile_id,
                    )
                    yield replace(
                        event,
                        continuation=returned_continuation,
                    )
                else:
                    yield event
        finally:
            await _close_managed_provider_stream(stream)

    async def embed(
        self,
        texts: Sequence[str],
    ) -> Sequence[Embedding]:
        if not self._accepting_requests:
            raise ProviderProfileServiceError(
                "The Provider is not accepting new requests."
            )
        return await self._delegate.embed(texts)

    async def aclose(self) -> None:
        self.revoke()
        await self._delegate.aclose()

    def revoke(self) -> None:
        self._accepting_requests = False

    def resume(self) -> None:
        self._accepting_requests = True


class ProviderProfileService:
    """The sole mutation and activation service for provider profiles."""

    def __init__(
        self,
        repository: ProviderMetadataRepository,
        provider_factory_builder: ProviderFactoryBuilder,
        *,
        turn_coordinator: ActiveTurnCoordinator | None = None,
    ) -> None:
        self._repository = repository
        self._provider_factory_builder = provider_factory_builder
        self._turn_coordinator = turn_coordinator
        self._switch_lock = asyncio.Lock()
        self._active_provider: _ManagedProvider | None = None
        self._runtime_profile_id: ProfileId | None = None
        self._runtime_profile_snapshot: ProviderProfile | None = None
        self._runtime_activation_options: (
            ProviderActivationOptions | None
        ) = None
        self._retiring_providers: dict[int, _ManagedProvider] = {}
        self._candidate_cleanup_pending: dict[
            int, _ManagedProvider
        ] = {}
        self._lifecycle_state = ProviderLifecycleState.INACTIVE
        self._closed = False

    def ensure_builtin_metadata(self) -> None:
        """Idempotently initialize reviewed built-ins without duplication."""

        try:
            for binding in builtin_managed_credential_bindings():
                existing_binding = (
                    self._repository.get_credential_binding(
                        binding.credential_id
                    )
                )
                if existing_binding is None:
                    self._repository.save_credential_binding(binding)
                elif (
                    existing_binding.provider_id != binding.provider_id
                    or existing_binding.allowed_origin
                    != binding.allowed_origin
                ):
                    raise ProviderProfileServiceError(
                        "A built-in credential binding conflicts with metadata."
                    )
            for profile in builtin_managed_profiles():
                existing_profile = self._repository.get_profile(
                    profile.profile_id
                )
                if existing_profile is None:
                    self._repository.save_profile(profile)
                elif (
                    existing_profile.provider_id != profile.provider_id
                    or existing_profile.protocol is not profile.protocol
                    or existing_profile.base_url != profile.base_url
                ):
                    raise ProviderProfileServiceError(
                        "A built-in provider profile conflicts with metadata."
                    )
            if self._repository.get_active_profile_id() is None:
                self._repository.set_active_profile_id(
                    FAKE_DEFAULT_PROFILE_ID
                )
        except ProviderProfileServiceError:
            raise
        except ProviderMetadataError:
            raise ProviderProfileServiceError(
                "Built-in provider metadata could not be initialized safely."
            ) from None

    def list_profiles(self) -> tuple[ProviderProfile, ...]:
        return self._repository.list_profiles()

    def get_profile(
        self,
        profile_id: ProfileId,
    ) -> ProviderProfile | None:
        return self._repository.get_profile(profile_id)

    def get_active_profile_id(self) -> ProfileId | None:
        return self._repository.get_active_profile_id()

    def create_credential_binding(
        self,
        *,
        provider_id: ProviderId,
        credential_id: CredentialId,
        display_name: str,
    ) -> CredentialBinding:
        if self._repository.get_credential_binding(credential_id) is not None:
            raise ProviderProfileServiceError(
                "The credential identifier is already registered."
            )
        try:
            binding = build_supported_credential_binding(
                provider_id=provider_id,
                credential_id=credential_id,
                display_name=display_name,
            )
            self._repository.save_credential_binding(binding)
        except (ProviderProfilePolicyError, ProviderMetadataError):
            raise ProviderProfileServiceError(
                "The credential binding could not be created safely."
            ) from None
        return binding

    def delete_credential_binding(
        self,
        credential_id: CredentialId,
    ) -> None:
        try:
            self._repository.delete_credential_binding(credential_id)
        except ProviderMetadataError:
            raise ProviderProfileServiceError(
                "The credential binding could not be deleted safely."
            ) from None

    def create_profile(
        self,
        *,
        provider_id: ProviderId,
        display_name: str,
        model: str,
        credential_id: CredentialId | None = None,
        profile_id: ProfileId | None = None,
    ) -> ProviderProfile:
        selected_profile_id = profile_id or ProfileId.new()
        if self._repository.get_profile(selected_profile_id) is not None:
            raise ProviderProfileServiceError(
                "The provider profile identifier already exists."
            )
        self._require_binding(provider_id, credential_id)
        try:
            profile = build_supported_profile(
                provider_id=provider_id,
                profile_id=selected_profile_id,
                display_name=display_name,
                model=model,
                credential_id=credential_id,
            )
            self._repository.save_profile(profile)
        except (ProviderProfilePolicyError, ProviderMetadataError):
            raise ProviderProfileServiceError(
                "The provider profile could not be created safely."
            ) from None
        return profile

    def update_profile(
        self,
        profile_id: ProfileId,
        *,
        display_name: str | None = None,
        model: str | None = None,
        credential_id: CredentialId | None = None,
    ) -> ProviderProfile:
        existing = self._repository.get_profile(profile_id)
        if existing is None:
            raise ProviderProfileServiceError(
                "The provider profile does not exist."
            )
        if self._lifecycle_state in {
            ProviderLifecycleState.SWITCHING,
            ProviderLifecycleState.CLEANUP_PENDING,
        }:
            raise ProviderProfileServiceError(
                "Provider metadata cannot be changed during lifecycle cleanup."
            )
        selected_credential_id = (
            credential_id
            if credential_id is not None
            else existing.credential_id
        )
        is_runtime_profile = self._runtime_profile_id == profile_id
        runtime_snapshot = self._runtime_profile_snapshot
        if is_runtime_profile:
            if (
                runtime_snapshot is None
                or not self._runtime_behavior_matches(
                    existing,
                    runtime_snapshot,
                )
            ):
                raise ProviderProfileServiceError(
                    "The active profile differs from its runtime snapshot."
                )
            if (
                model is not None
                and model != runtime_snapshot.model
            ) or selected_credential_id != runtime_snapshot.credential_id:
                raise ProviderProfileServiceError(
                    "Stop or switch the active Provider before changing "
                    "its model or credential."
                )
        self._require_binding(
            existing.provider_id,
            selected_credential_id,
        )
        try:
            updated = build_supported_profile(
                provider_id=existing.provider_id,
                profile_id=existing.profile_id,
                display_name=(
                    existing.display_name
                    if display_name is None
                    else display_name
                ),
                model=existing.model if model is None else model,
                credential_id=selected_credential_id,
            )
            self._repository.save_profile(updated)
        except (ProviderProfilePolicyError, ProviderMetadataError):
            raise ProviderProfileServiceError(
                "The provider profile could not be updated safely."
            ) from None
        if is_runtime_profile:
            self._runtime_profile_snapshot = updated
        return updated

    def delete_profile(self, profile_id: ProfileId) -> None:
        if self._runtime_profile_id == profile_id:
            raise ProviderProfileServiceError(
                "The active runtime profile cannot be deleted."
            )
        try:
            self._repository.delete_profile(profile_id)
        except ProviderMetadataError:
            raise ProviderProfileServiceError(
                "The provider profile could not be deleted safely."
            ) from None

    @property
    def active_provider(self) -> LLMProvider | None:
        """Return the published Provider, or None while switching."""

        return self._active_provider

    @property
    def runtime_profile_id(self) -> ProfileId | None:
        return self._runtime_profile_id

    @property
    def runtime_profile_snapshot(self) -> ProviderProfile | None:
        return self._runtime_profile_snapshot

    @property
    def runtime_activation_options(
        self,
    ) -> ProviderActivationOptions | None:
        return self._runtime_activation_options

    @property
    def lifecycle_state(self) -> ProviderLifecycleState:
        return self._lifecycle_state

    @property
    def retiring_provider_count(self) -> int:
        return len(self._retiring_providers)

    @property
    def candidate_cleanup_pending_count(self) -> int:
        return len(self._candidate_cleanup_pending)

    def validate_continuation(
        self,
        profile_id: ProfileId,
        continuation: ProviderContinuation,
    ) -> None:
        profile = self._runtime_profile_snapshot
        if (
            profile is None
            or profile.profile_id != profile_id
            or self._runtime_profile_id != profile_id
            or self._active_provider is None
            or continuation.profile_id is None
            or continuation.profile_id != profile_id
            or continuation.provider_name != profile.provider_id.value
        ):
            raise ProviderProfileServiceError(
                "The continuation does not belong to the active profile."
            )

    async def activate_profile(
        self,
        profile_id: ProfileId,
        options: ProviderActivationOptions,
        *,
        turn_handling: ActiveTurnHandling | None = None,
        continuation: ProviderContinuation | None = None,
    ) -> LLMProvider:
        """Close the old Provider before constructing and publishing the new."""

        async with self._switch_lock:
            await self._retry_pending_cleanup_locked()
            if self._closed:
                raise ProviderProfileServiceError(
                    "The Provider profile service is closed."
                )
            profile = self._repository.get_profile(profile_id)
            if profile is None:
                raise ProviderProfileServiceError(
                    "The provider profile does not exist."
                )
            if continuation is not None:
                self.validate_continuation(profile_id, continuation)
            if (
                self._active_provider is not None
                and self._runtime_profile_id == profile_id
            ):
                if (
                    self._runtime_profile_snapshot == profile
                    and self._runtime_activation_options == options
                ):
                    return self._active_provider
                raise ProviderProfileServiceError(
                    "The active profile or activation options changed; "
                    "switch or stop it before rebuilding."
                )

            old_provider = self._active_provider
            old_profile_id = self._runtime_profile_id
            old_profile_snapshot = self._runtime_profile_snapshot
            old_activation_options = self._runtime_activation_options
            if old_provider is not None:
                if (
                    old_profile_id is None
                    or old_profile_snapshot is None
                    or old_activation_options is None
                    or turn_handling is None
                    or self._turn_coordinator is None
                ):
                    raise ProviderProfileServiceError(
                        "Provider switching requires an explicit turn policy."
                    )
                self._lifecycle_state = ProviderLifecycleState.SWITCHING
                old_provider.revoke()
                self._clear_runtime()
                self._retiring_providers[id(old_provider)] = old_provider
                coordination_failed = False
                try:
                    await self._turn_coordinator.prepare_for_provider_switch(
                        old_profile_id=old_profile_id,
                        new_profile_id=profile_id,
                        handling=turn_handling,
                    )
                except asyncio.CancelledError:
                    self._retiring_providers.pop(id(old_provider), None)
                    old_provider.resume()
                    self._active_provider = old_provider
                    self._runtime_profile_id = old_profile_id
                    self._runtime_profile_snapshot = old_profile_snapshot
                    self._runtime_activation_options = (
                        old_activation_options
                    )
                    self._lifecycle_state = ProviderLifecycleState.ACTIVE
                    raise
                except Exception:
                    self._retiring_providers.pop(id(old_provider), None)
                    old_provider.resume()
                    self._active_provider = old_provider
                    self._runtime_profile_id = old_profile_id
                    self._runtime_profile_snapshot = old_profile_snapshot
                    self._runtime_activation_options = (
                        old_activation_options
                    )
                    self._lifecycle_state = ProviderLifecycleState.ACTIVE
                    coordination_failed = True
                if coordination_failed:
                    raise ProviderProfileServiceError(
                        "The active Agent turn could not be quiesced safely."
                    )
                if not await self._close_tracked_provider(
                    old_provider,
                    self._retiring_providers,
                ):
                    self._lifecycle_state = (
                        ProviderLifecycleState.CLEANUP_PENDING
                    )
                    raise ProviderProfileServiceError(
                        "The previous Provider could not be closed safely."
                    ) from None
            else:
                self._lifecycle_state = ProviderLifecycleState.SWITCHING

            construction_failed = False
            new_delegate: LLMProvider | None = None
            try:
                factory = self._provider_factory_builder(
                    self._repository.list_credential_bindings()
                )
                new_delegate = factory.create_profile(
                    profile,
                    timeout_seconds=options.timeout_seconds,
                    max_retries=options.max_retries,
                    stream=options.stream,
                )
            except Exception:
                construction_failed = True
            if construction_failed or new_delegate is None:
                self._lifecycle_state = ProviderLifecycleState.INACTIVE
                raise ProviderProfileServiceError(
                    "The selected Provider could not be constructed safely."
                )
            new_provider = _ManagedProvider(
                new_delegate,
                profile_id,
                profile.provider_id.value,
            )

            identity_failed = False
            try:
                identity_failed = (
                    new_delegate.name != profile.provider_id.value
                    or new_delegate.capabilities().protocol
                    is not profile.protocol
                )
            except Exception:
                identity_failed = True
            if identity_failed:
                self._candidate_cleanup_pending[
                    id(new_provider)
                ] = new_provider
                if not await self._close_tracked_provider(
                    new_provider,
                    self._candidate_cleanup_pending,
                ):
                    self._lifecycle_state = (
                        ProviderLifecycleState.CLEANUP_PENDING
                    )
                    raise ProviderProfileServiceError(
                        "The invalid candidate Provider could not be "
                        "closed safely."
                    ) from None
                self._lifecycle_state = ProviderLifecycleState.INACTIVE
                raise ProviderProfileServiceError(
                    "The selected Provider identity does not match "
                    "the active profile."
                ) from None

            persistence_failed = False
            try:
                self._repository.set_active_profile_id(profile_id)
            except Exception:
                persistence_failed = True
            if persistence_failed:
                self._candidate_cleanup_pending[
                    id(new_provider)
                ] = new_provider
                if not await self._close_tracked_provider(
                    new_provider,
                    self._candidate_cleanup_pending,
                ):
                    self._lifecycle_state = (
                        ProviderLifecycleState.CLEANUP_PENDING
                    )
                    raise ProviderProfileServiceError(
                        "The candidate Provider could not be closed after "
                        "active profile persistence failed."
                    ) from None
                self._lifecycle_state = ProviderLifecycleState.INACTIVE
                raise ProviderProfileServiceError(
                    "The active profile could not be persisted safely."
                ) from None

            self._active_provider = new_provider
            self._runtime_profile_id = profile_id
            self._runtime_profile_snapshot = profile
            self._runtime_activation_options = options
            self._lifecycle_state = ProviderLifecycleState.ACTIVE
            return new_provider

    async def aclose(self) -> None:
        """Retry and close every retained Provider without background tasks."""

        async with self._switch_lock:
            self._closed = True
            provider = self._active_provider
            if provider is not None:
                provider.revoke()
                self._retiring_providers[id(provider)] = provider
            self._clear_runtime()
            await self._retry_pending_cleanup_locked()
            self._lifecycle_state = ProviderLifecycleState.CLOSED

    async def _retry_pending_cleanup_locked(self) -> None:
        if not self._has_pending_cleanup():
            return
        self._lifecycle_state = ProviderLifecycleState.SWITCHING
        cleanup_failed = False
        for providers in (
            self._retiring_providers,
            self._candidate_cleanup_pending,
        ):
            for provider in tuple(providers.values()):
                if not await self._close_tracked_provider(
                    provider,
                    providers,
                ):
                    cleanup_failed = True
        if cleanup_failed:
            self._lifecycle_state = (
                ProviderLifecycleState.CLEANUP_PENDING
            )
            raise ProviderProfileServiceError(
                "Pending Provider cleanup could not be completed safely."
            ) from None
        self._lifecycle_state = (
            ProviderLifecycleState.CLOSED
            if self._closed
            else ProviderLifecycleState.INACTIVE
        )

    async def _close_tracked_provider(
        self,
        provider: _ManagedProvider,
        providers: dict[int, _ManagedProvider],
    ) -> bool:
        try:
            await provider.aclose()
        except asyncio.CancelledError:
            self._lifecycle_state = (
                ProviderLifecycleState.CLEANUP_PENDING
            )
            raise
        except Exception:
            return False
        providers.pop(id(provider), None)
        return True

    def _clear_runtime(self) -> None:
        self._active_provider = None
        self._runtime_profile_id = None
        self._runtime_profile_snapshot = None
        self._runtime_activation_options = None

    def _has_pending_cleanup(self) -> bool:
        return bool(
            self._retiring_providers
            or self._candidate_cleanup_pending
        )

    @staticmethod
    def _runtime_behavior_matches(
        profile: ProviderProfile,
        runtime_snapshot: ProviderProfile,
    ) -> bool:
        return (
            replace(
                profile,
                display_name=runtime_snapshot.display_name,
            )
            == runtime_snapshot
        )

    def _require_binding(
        self,
        provider_id: ProviderId,
        credential_id: CredentialId | None,
    ) -> None:
        if credential_id is None:
            return
        binding = self._repository.get_credential_binding(credential_id)
        if binding is None or binding.provider_id != provider_id:
            raise ProviderProfileServiceError(
                "The credential binding does not match the provider."
            )
