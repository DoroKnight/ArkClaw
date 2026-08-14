"""Provider builder registry keyed by implementation and wire protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from arkclaw.config.secrets import SecretStore
from arkclaw.domain.errors import ArkClawError
from arkclaw.domain.models import (
    ApiProtocol,
    ContinuationMode,
    CredentialBinding,
    CredentialId,
    ProviderCapabilities,
    ProviderId,
    ProviderProfile,
)
from arkclaw.domain.ports import LLMProvider


class ProviderRegistryError(ArkClawError):
    """Safe registry failure with no credential or request content."""


@dataclass(frozen=True, slots=True)
class ProviderBuildOptions:
    secret_store: SecretStore | None
    credential_bindings: CredentialBindingRegistry
    timeout_seconds: float
    max_retries: int
    stream: bool


class ProviderBuilder(Protocol):
    def build(
        self,
        profile: ProviderProfile,
        options: ProviderBuildOptions,
    ) -> LLMProvider: ...


class CredentialBindingRegistry:
    """Authoritative non-sensitive bindings for credential use."""

    def __init__(
        self,
        bindings: tuple[CredentialBinding, ...] = (),
    ) -> None:
        self._bindings: dict[CredentialId, CredentialBinding] = {}
        for binding in bindings:
            self.register(binding)

    def register(self, binding: CredentialBinding) -> None:
        if binding.credential_id in self._bindings:
            raise ProviderRegistryError(
                "The credential binding is already registered."
            )
        self._bindings[binding.credential_id] = binding

    def require_for_profile(
        self,
        profile: ProviderProfile,
    ) -> CredentialBinding:
        credential_id = profile.credential_id
        if credential_id is None:
            raise ProviderRegistryError(
                "The provider profile requires a credential binding."
            )
        binding = self._bindings.get(credential_id)
        if (
            binding is None
            or binding.provider_id != profile.provider_id
            or binding.allowed_origin != profile.origin
        ):
            raise ProviderRegistryError(
                "The credential binding does not match the provider profile."
            )
        return binding


def restrict_capabilities(
    maximum: ProviderCapabilities,
    requested: ProviderCapabilities,
) -> ProviderCapabilities:
    """Apply profile restrictions without falsifying adapter capabilities."""

    if requested.protocol is not maximum.protocol:
        raise ProviderRegistryError(
            "The capability protocol does not match the adapter."
        )
    if requested.streaming is not maximum.streaming:
        raise ProviderRegistryError(
            "The profile cannot change the adapter streaming capability."
        )
    if requested.tools and not maximum.tools:
        raise ProviderRegistryError(
            "The profile requests unsupported tools."
        )
    if requested.embeddings and not maximum.embeddings:
        raise ProviderRegistryError(
            "The profile requests unsupported embeddings."
        )
    if requested.continuation_mode not in {
        ContinuationMode.NONE,
        maximum.continuation_mode,
    }:
        raise ProviderRegistryError(
            "The profile requests an unsupported continuation mode."
        )
    return ProviderCapabilities(
        streaming=maximum.streaming,
        tools=maximum.tools and requested.tools,
        embeddings=maximum.embeddings and requested.embeddings,
        continuation_mode=requested.continuation_mode,
        protocol=maximum.protocol,
    )


class ProviderRegistry:
    """Map a validated provider/protocol pair to one narrow builder."""

    def __init__(self) -> None:
        self._builders: dict[
            tuple[ProviderId, ApiProtocol],
            ProviderBuilder,
        ] = {}

    def register(
        self,
        provider_id: ProviderId,
        protocol: ApiProtocol,
        builder: ProviderBuilder,
    ) -> None:
        key = (provider_id, protocol)
        if key in self._builders:
            raise ProviderRegistryError(
                "The provider builder is already registered."
            )
        self._builders[key] = builder

    def build(
        self,
        profile: ProviderProfile,
        options: ProviderBuildOptions,
    ) -> LLMProvider:
        if not profile.enabled:
            raise ProviderRegistryError("The provider profile is disabled.")
        if profile.credential_id is not None:
            options.credential_bindings.require_for_profile(profile)
        builder = self._builders.get(
            (profile.provider_id, profile.protocol)
        )
        if builder is None:
            raise ProviderRegistryError(
                "No provider builder is registered for this profile."
            )
        return builder.build(profile, options)
