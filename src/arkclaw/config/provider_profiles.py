"""Built-in non-sensitive provider profiles."""

from __future__ import annotations

from arkclaw.domain.models import (
    DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    DEEPSEEK_DEFAULT_PROFILE_ID,
    DEEPSEEK_PROVIDER_ID,
    FAKE_DEFAULT_PROFILE_ID,
    FAKE_PROVIDER_ID,
    OLLAMA_DEFAULT_PROFILE_ID,
    OLLAMA_PROVIDER_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_DEFAULT_PROFILE_ID,
    OPENAI_PROVIDER_ID,
    ApiProtocol,
    ContinuationMode,
    CredentialBinding,
    CredentialId,
    ProfileId,
    ProviderCapabilities,
    ProviderProfile,
)

OPENAI_OFFICIAL_ORIGIN = "https://api.openai.com"
OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"
DEEPSEEK_OFFICIAL_ORIGIN = "https://api.deepseek.com"
DEEPSEEK_OFFICIAL_BASE_URL = "https://api.deepseek.com"


def builtin_credential_bindings() -> tuple[CredentialBinding, ...]:
    """Return authoritative non-sensitive built-in credential bindings."""

    return (
        CredentialBinding(
            credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
            provider_id=OPENAI_PROVIDER_ID,
            allowed_origin=OPENAI_OFFICIAL_ORIGIN,
            display_name="OpenAI default credential",
        ),
        CredentialBinding(
            credential_id=DEEPSEEK_DEFAULT_CREDENTIAL_ID,
            provider_id=DEEPSEEK_PROVIDER_ID,
            allowed_origin=DEEPSEEK_OFFICIAL_ORIGIN,
            display_name="DeepSeek default credential",
        ),
    )


def fake_default_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id=FAKE_DEFAULT_PROFILE_ID,
        display_name="Built-in Fake",
        provider_id=FAKE_PROVIDER_ID,
        protocol=ApiProtocol.INTERNAL,
        base_url=None,
        model="fake",
        credential_id=None,
        capabilities=ProviderCapabilities(
            streaming=True,
            tools=False,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_MESSAGES,
            protocol=ApiProtocol.INTERNAL,
        ),
    )


def openai_profile(
    model: str,
    *,
    profile_id: ProfileId = OPENAI_DEFAULT_PROFILE_ID,
    credential_id: CredentialId = OPENAI_DEFAULT_CREDENTIAL_ID,
    display_name: str = "OpenAI",
) -> ProviderProfile:
    return ProviderProfile(
        profile_id=profile_id,
        display_name=display_name,
        provider_id=OPENAI_PROVIDER_ID,
        protocol=ApiProtocol.RESPONSES,
        base_url=OPENAI_OFFICIAL_BASE_URL,
        model=model,
        credential_id=credential_id,
        capabilities=ProviderCapabilities(
            streaming=True,
            tools=True,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_PROVIDER_ITEMS,
            protocol=ApiProtocol.RESPONSES,
        ),
    )


def deepseek_profile(
    model: str,
    *,
    profile_id: ProfileId = DEEPSEEK_DEFAULT_PROFILE_ID,
    credential_id: CredentialId = DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    display_name: str = "DeepSeek",
) -> ProviderProfile:
    return ProviderProfile(
        profile_id=profile_id,
        display_name=display_name,
        provider_id=DEEPSEEK_PROVIDER_ID,
        protocol=ApiProtocol.CHAT_COMPLETIONS,
        base_url=DEEPSEEK_OFFICIAL_BASE_URL,
        model=model,
        credential_id=credential_id,
        capabilities=ProviderCapabilities(
            streaming=True,
            tools=False,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_MESSAGES,
            protocol=ApiProtocol.CHAT_COMPLETIONS,
        ),
    )


def ollama_profile(model: str, base_url: str) -> ProviderProfile:
    return ProviderProfile(
        profile_id=OLLAMA_DEFAULT_PROFILE_ID,
        display_name="Ollama",
        provider_id=OLLAMA_PROVIDER_ID,
        protocol=ApiProtocol.OLLAMA_CHAT,
        base_url=base_url,
        model=model,
        credential_id=None,
        capabilities=ProviderCapabilities(
            streaming=True,
            tools=False,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_MESSAGES,
            protocol=ApiProtocol.OLLAMA_CHAT,
        ),
    )
