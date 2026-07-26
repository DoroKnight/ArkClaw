"""Closed policy for supported provider profile metadata."""

from __future__ import annotations

from dataclasses import replace

from sjtuclaw.config.defaults import (
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
)
from sjtuclaw.config.provider_profiles import (
    DEEPSEEK_OFFICIAL_ORIGIN,
    OPENAI_OFFICIAL_ORIGIN,
    deepseek_profile,
    fake_default_profile,
    ollama_profile,
    openai_profile,
)
from sjtuclaw.domain.errors import SJTUClawError
from sjtuclaw.domain.models import (
    DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    DEEPSEEK_PROVIDER_ID,
    FAKE_PROVIDER_ID,
    OLLAMA_PROVIDER_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_PROVIDER_ID,
    CredentialBinding,
    CredentialId,
    ProfileId,
    ProviderId,
    ProviderProfile,
)


class ProviderProfilePolicyError(SJTUClawError):
    """A profile attempts to leave the reviewed provider boundary."""


_MANUAL_TEST_CREDENTIAL_IDS = frozenset(
    {
        OPENAI_MANUAL_TEST_CREDENTIAL_ID,
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    }
)


def _reject_manual_test_credential_id(
    credential_id: CredentialId,
) -> None:
    if credential_id in _MANUAL_TEST_CREDENTIAL_IDS:
        raise ProviderProfilePolicyError(
            "Manual verification credentials cannot be used by profiles."
        )


def build_supported_profile(
    *,
    provider_id: ProviderId,
    profile_id: ProfileId,
    display_name: str,
    model: str,
    credential_id: CredentialId | None,
) -> ProviderProfile:
    """Build one profile without accepting a caller-controlled endpoint."""

    if provider_id == FAKE_PROVIDER_ID:
        if credential_id is not None:
            raise ProviderProfilePolicyError(
                "The Fake provider cannot use a credential binding."
            )
        return replace(
            fake_default_profile(),
            profile_id=profile_id,
            display_name=display_name,
            model=model,
        )
    if provider_id == OPENAI_PROVIDER_ID:
        if credential_id is None:
            raise ProviderProfilePolicyError(
                "The OpenAI profile requires a credential binding."
            )
        _reject_manual_test_credential_id(credential_id)
        return openai_profile(
            model,
            profile_id=profile_id,
            credential_id=credential_id,
            display_name=display_name,
        )
    if provider_id == DEEPSEEK_PROVIDER_ID:
        if credential_id is None:
            raise ProviderProfilePolicyError(
                "The DeepSeek profile requires a credential binding."
            )
        _reject_manual_test_credential_id(credential_id)
        return deepseek_profile(
            model,
            profile_id=profile_id,
            credential_id=credential_id,
            display_name=display_name,
        )
    if provider_id == OLLAMA_PROVIDER_ID:
        if credential_id is not None:
            raise ProviderProfilePolicyError(
                "The Ollama placeholder cannot use a credential binding."
            )
        return replace(
            ollama_profile(model, DEFAULT_OLLAMA_BASE_URL),
            profile_id=profile_id,
            display_name=display_name,
        )
    raise ProviderProfilePolicyError(
        "The provider profile type is not supported."
    )


def validate_supported_profile(profile: ProviderProfile) -> None:
    """Reject altered protocols, origins, capabilities, or enablement."""

    expected = build_supported_profile(
        provider_id=profile.provider_id,
        profile_id=profile.profile_id,
        display_name=profile.display_name,
        model=profile.model,
        credential_id=profile.credential_id,
    )
    if profile != expected:
        raise ProviderProfilePolicyError(
            "The provider profile leaves the reviewed provider boundary."
        )


def build_supported_credential_binding(
    *,
    provider_id: ProviderId,
    credential_id: CredentialId,
    display_name: str,
) -> CredentialBinding:
    """Build binding metadata for one reviewed cloud provider."""

    _reject_manual_test_credential_id(credential_id)
    if provider_id == OPENAI_PROVIDER_ID:
        origin = OPENAI_OFFICIAL_ORIGIN
    elif provider_id == DEEPSEEK_PROVIDER_ID:
        origin = DEEPSEEK_OFFICIAL_ORIGIN
    else:
        raise ProviderProfilePolicyError(
            "The provider does not support credential bindings."
        )
    return CredentialBinding(
        credential_id=credential_id,
        provider_id=provider_id,
        allowed_origin=origin,
        display_name=display_name,
    )


def validate_supported_credential_binding(
    binding: CredentialBinding,
) -> None:
    expected = build_supported_credential_binding(
        provider_id=binding.provider_id,
        credential_id=binding.credential_id,
        display_name=binding.display_name,
    )
    if binding != expected:
        raise ProviderProfilePolicyError(
            "The credential binding leaves the reviewed provider boundary."
        )


def builtin_managed_profiles() -> tuple[ProviderProfile, ...]:
    """Return stable built-ins for idempotent first-run initialization."""

    return (
        fake_default_profile(),
        openai_profile(DEFAULT_OPENAI_MODEL),
        deepseek_profile(DEFAULT_DEEPSEEK_MODEL),
        ollama_profile(DEFAULT_OLLAMA_MODEL, DEFAULT_OLLAMA_BASE_URL),
    )


def builtin_managed_credential_bindings(
) -> tuple[CredentialBinding, ...]:
    """Return only production-default bindings, never manual test Targets."""

    return (
        build_supported_credential_binding(
            provider_id=OPENAI_PROVIDER_ID,
            credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
            display_name="OpenAI default credential",
        ),
        build_supported_credential_binding(
            provider_id=DEEPSEEK_PROVIDER_ID,
            credential_id=DEEPSEEK_DEFAULT_CREDENTIAL_ID,
            display_name="DeepSeek default credential",
        ),
    )
