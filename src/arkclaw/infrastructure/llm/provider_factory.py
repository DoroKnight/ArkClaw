"""Create providers from profiles through a bounded registry."""

from __future__ import annotations

from arkclaw.config.models import ProviderName, RuntimeConfig
from arkclaw.config.provider_profiles import (
    DEEPSEEK_OFFICIAL_BASE_URL,
    OPENAI_OFFICIAL_BASE_URL,
    builtin_credential_bindings,
    deepseek_profile,
    fake_default_profile,
    ollama_profile,
    openai_profile,
)
from arkclaw.config.secrets import SecretStore
from arkclaw.domain.errors import ArkClawError
from arkclaw.domain.models import (
    DEEPSEEK_PROVIDER_ID,
    FAKE_PROVIDER_ID,
    OLLAMA_PROVIDER_ID,
    OPENAI_PROVIDER_ID,
    ApiProtocol,
    ProviderProfile,
)
from arkclaw.domain.ports import LLMProvider
from arkclaw.infrastructure.llm.deepseek_provider import (
    DEEPSEEK_MAXIMUM_CAPABILITIES,
    DeepSeekProvider,
)
from arkclaw.infrastructure.llm.deepseek_sdk import DeepSeekClientFactory
from arkclaw.infrastructure.llm.fake_provider import FakeProvider
from arkclaw.infrastructure.llm.ollama_provider import OllamaProvider
from arkclaw.infrastructure.llm.openai_provider import (
    OPENAI_MAXIMUM_CAPABILITIES,
    OpenAIProvider,
)
from arkclaw.infrastructure.llm.openai_sdk import OpenAIClientFactory
from arkclaw.infrastructure.llm.provider_registry import (
    CredentialBindingRegistry,
    ProviderBuilder,
    ProviderBuildOptions,
    ProviderRegistry,
    restrict_capabilities,
)


class ProviderNotImplementedError(ArkClawError):
    """Raised when a recognized legacy provider lacks an adapter."""

    def __init__(self, provider: ProviderName) -> None:
        self.provider = provider
        super().__init__(
            f"Provider '{provider.value}' is recognized but not implemented "
            "in this milestone."
        )


class _FakeBuilder:
    def build(
        self,
        profile: ProviderProfile,
        options: ProviderBuildOptions,
    ) -> LLMProvider:
        del profile
        return FakeProvider(
            echo_user_message=True,
            chunk_size=4,
            delay_seconds=0.03,
            stream=options.stream,
        )


class _OpenAIBuilder:
    def __init__(
        self,
        client_factory: OpenAIClientFactory | None,
    ) -> None:
        self._client_factory = client_factory

    def build(
        self,
        profile: ProviderProfile,
        options: ProviderBuildOptions,
    ) -> LLMProvider:
        if (
            profile.provider_id != OPENAI_PROVIDER_ID
            or profile.protocol is not ApiProtocol.RESPONSES
            or profile.base_url != OPENAI_OFFICIAL_BASE_URL
            or profile.credential_id is None
        ):
            raise ValueError("invalid built-in OpenAI profile")
        options.credential_bindings.require_for_profile(profile)
        effective_capabilities = restrict_capabilities(
            OPENAI_MAXIMUM_CAPABILITIES,
            profile.capabilities,
        )
        return OpenAIProvider(
            secret_store=options.secret_store,
            model=profile.model,
            timeout_seconds=options.timeout_seconds,
            max_retries=options.max_retries,
            stream=options.stream,
            client_factory=self._client_factory,
            credential_id=profile.credential_id,
            capabilities=effective_capabilities,
        )


class _DeepSeekBuilder:
    def __init__(
        self,
        client_factory: DeepSeekClientFactory | None,
    ) -> None:
        self._client_factory = client_factory

    def build(
        self,
        profile: ProviderProfile,
        options: ProviderBuildOptions,
    ) -> LLMProvider:
        if (
            profile.provider_id != DEEPSEEK_PROVIDER_ID
            or profile.protocol is not ApiProtocol.CHAT_COMPLETIONS
            or profile.base_url != DEEPSEEK_OFFICIAL_BASE_URL
            or profile.credential_id is None
        ):
            raise ValueError("invalid built-in DeepSeek profile")
        options.credential_bindings.require_for_profile(profile)
        effective_capabilities = restrict_capabilities(
            DEEPSEEK_MAXIMUM_CAPABILITIES,
            profile.capabilities,
        )
        return DeepSeekProvider(
            profile=profile,
            secret_store=options.secret_store,
            timeout_seconds=options.timeout_seconds,
            max_retries=options.max_retries,
            stream=options.stream,
            client_factory=self._client_factory,
            capabilities=effective_capabilities,
        )


class _OllamaBuilder:
    def build(
        self,
        profile: ProviderProfile,
        options: ProviderBuildOptions,
    ) -> LLMProvider:
        return OllamaProvider(
            profile=profile,
            timeout_seconds=options.timeout_seconds,
            max_retries=options.max_retries,
            stream=options.stream,
        )


class ProviderFactory:
    """Compatibility facade that delegates profile creation to a registry."""

    def __init__(
        self,
        secret_store: SecretStore | None = None,
        *,
        openai_client_factory: OpenAIClientFactory | None = None,
        deepseek_client_factory: DeepSeekClientFactory | None = None,
        credential_bindings: CredentialBindingRegistry | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._credential_bindings = (
            credential_bindings
            or CredentialBindingRegistry(builtin_credential_bindings())
        )
        if registry is None:
            registry = ProviderRegistry()
            registry.register(
                FAKE_PROVIDER_ID,
                ApiProtocol.INTERNAL,
                _FakeBuilder(),
            )
            registry.register(
                OPENAI_PROVIDER_ID,
                ApiProtocol.RESPONSES,
                _OpenAIBuilder(openai_client_factory),
            )
            registry.register(
                DEEPSEEK_PROVIDER_ID,
                ApiProtocol.CHAT_COMPLETIONS,
                _DeepSeekBuilder(deepseek_client_factory),
            )
            registry.register(
                OLLAMA_PROVIDER_ID,
                ApiProtocol.OLLAMA_CHAT,
                _OllamaBuilder(),
            )
        self._registry = registry

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    def create(self, config: RuntimeConfig) -> LLMProvider:
        """Create a provider from legacy RuntimeConfig fields."""

        if config.provider is ProviderName.FAKE:
            profile = fake_default_profile()
            max_retries = 0
        elif config.provider is ProviderName.OPENAI:
            profile = openai_profile(config.openai_model)
            max_retries = config.openai_max_retries
        elif config.provider is ProviderName.DEEPSEEK:
            profile = deepseek_profile(config.deepseek_model)
            max_retries = config.deepseek_max_retries
        elif config.provider is ProviderName.OLLAMA:
            profile = ollama_profile(
                config.ollama_model,
                config.ollama_base_url,
            )
            max_retries = getattr(config, "ollama_max_retries", 2)
        else:
            raise ProviderNotImplementedError(config.provider)
        return self.create_profile(
            profile,
            timeout_seconds=config.provider_timeout_seconds,
            max_retries=max_retries,
            stream=config.stream,
        )

    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        """Create exactly the requested profile without fallback."""

        options = ProviderBuildOptions(
            secret_store=self._secret_store,
            credential_bindings=self._credential_bindings,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            stream=stream,
        )
        return self._registry.build(profile, options)


__all__ = [
    "ProviderBuilder",
    "ProviderFactory",
    "ProviderNotImplementedError",
    "ProviderRegistry",
]
