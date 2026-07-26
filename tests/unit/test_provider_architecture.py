from __future__ import annotations

import asyncio
import hashlib
import logging
import traceback
from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.fakes.deepseek_sdk import (
    FakeDeepSeekClientFactory,
    FakeDeepSeekScenario,
)
from tests.fakes.openai_sdk import (
    FakeOpenAIClientFactory,
    FakeOpenAIScenario,
)

from sjtuclaw.config.provider_profiles import (
    DEEPSEEK_OFFICIAL_ORIGIN,
    OPENAI_OFFICIAL_ORIGIN,
    deepseek_profile,
    openai_profile,
)
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.events import LLMEventType
from sjtuclaw.domain.models import (
    DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    ApiProtocol,
    ChatMessage,
    ContinuationMode,
    CredentialBinding,
    CredentialId,
    LLMRequest,
    MessageRole,
    ProfileId,
    ProviderCapabilities,
    ProviderId,
    ProviderProfile,
)
from sjtuclaw.infrastructure.llm.deepseek_provider import DeepSeekProvider
from sjtuclaw.infrastructure.llm.deepseek_sdk import (
    DeepSeekEvent,
    DeepSeekEventKind,
)
from sjtuclaw.infrastructure.llm.fake_provider import FakeProvider
from sjtuclaw.infrastructure.llm.openai_provider import OpenAIProvider
from sjtuclaw.infrastructure.llm.openai_sdk import (
    OpenAIResponseEvent,
    OpenAIResponseEventKind,
)
from sjtuclaw.infrastructure.llm.provider_factory import ProviderFactory
from sjtuclaw.infrastructure.llm.provider_registry import (
    CredentialBindingRegistry,
    ProviderBuildOptions,
    ProviderRegistry,
    ProviderRegistryError,
)
from sjtuclaw.infrastructure.security.windows_credential_store import (
    DEEPSEEK_API_KEY_TARGET,
    OPENAI_API_KEY_TARGET,
    CredentialTargetResolver,
    WindowsCredentialSecretStore,
)

_OPENAI_FAKE_KEY = "sk-openai-test-never-use"
_DEEPSEEK_FAKE_KEY = "sk-deepseek-test-never-use"


class _MappingCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def read(self, target_name: str) -> bytes | None:
        return self.values.get(target_name)

    def write(self, target_name: str, secret_bytes: bytes) -> None:
        self.values[target_name] = secret_bytes

    def delete(self, target_name: str) -> None:
        self.values.pop(target_name, None)


def _request() -> LLMRequest:
    return LLMRequest(
        instructions="Be concise.",
        messages=(
            ChatMessage(role=MessageRole.USER, content="hello"),
        ),
        max_output_tokens=64,
    )


def _successful_scenario() -> FakeDeepSeekScenario:
    return FakeDeepSeekScenario(
        events=(
            DeepSeekEvent(
                kind=DeepSeekEventKind.TEXT_DELTA,
                text="ok",
            ),
            DeepSeekEvent(
                kind=DeepSeekEventKind.COMPLETED,
                finish_reason="stop",
            ),
        )
    )


def test_generic_secret_store_isolates_credential_ids() -> None:
    first_id = CredentialId.new()
    second_id = CredentialId.new()
    store = InMemorySecretStore()

    store.set_secret(first_id, SecretValue("first-fake-secret"))
    store.set_secret(second_id, SecretValue("second-fake-secret"))

    first = store.get_secret(first_id)
    second = store.get_secret(second_id)
    assert first is not None and first.reveal() == "first-fake-secret"
    assert second is not None and second.reveal() == "second-fake-secret"
    store.delete_secret(first_id)
    assert store.get_secret(first_id) is None
    assert store.has_secret(second_id)


def test_openai_compatibility_facade_uses_legacy_reserved_credential() -> None:
    store = InMemorySecretStore()
    store.set_openai_api_key(SecretValue(_OPENAI_FAKE_KEY))

    generic = store.get_secret(OPENAI_DEFAULT_CREDENTIAL_ID)

    assert generic is not None
    assert generic.reveal() == _OPENAI_FAKE_KEY
    assert store.get_secret(DEEPSEEK_DEFAULT_CREDENTIAL_ID) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "../credential",
        "not-a-uuid",
        "A" * 65,
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_credential_id_rejects_empty_malicious_or_non_uuid_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="credential_id"):
        CredentialId(value)


def test_windows_target_resolution_preserves_legacy_and_isolates_uuid_ids() -> None:
    first_id = CredentialId.new()
    second_id = CredentialId.new()

    assert (
        CredentialTargetResolver.resolve(OPENAI_DEFAULT_CREDENTIAL_ID)
        == OPENAI_API_KEY_TARGET
    )
    assert (
        CredentialTargetResolver.resolve(DEEPSEEK_DEFAULT_CREDENTIAL_ID)
        == DEEPSEEK_API_KEY_TARGET
    )
    assert CredentialTargetResolver.resolve(first_id) == (
        f"SJTUClaw/Credentials/{first_id.value}"
    )
    assert CredentialTargetResolver.resolve(first_id) != (
        CredentialTargetResolver.resolve(second_id)
    )


def test_windows_store_keeps_two_credentials_in_separate_targets() -> None:
    backend = _MappingCredentialBackend()
    store = WindowsCredentialSecretStore(backend=backend)
    first_id = CredentialId.new()
    second_id = CredentialId.new()

    store.set_secret(first_id, SecretValue("first-fake-secret"))
    store.set_secret(second_id, SecretValue("second-fake-secret"))

    first = store.get_secret(first_id)
    second = store.get_secret(second_id)
    assert first is not None and first.reveal() == "first-fake-secret"
    assert second is not None and second.reveal() == "second-fake-secret"
    assert len(backend.values) == 2


def test_profile_display_model_and_url_cannot_change_credential_target() -> None:
    credential_id = CredentialId.new()
    profile = deepseek_profile(
        "model/with/user-text",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
        display_name="display/../../credential",
    )

    assert profile.credential_id is not None
    target = CredentialTargetResolver.resolve(profile.credential_id)

    assert target == f"SJTUClaw/Credentials/{credential_id.value}"
    assert profile.display_name not in target
    assert profile.model not in target
    assert profile.base_url is not None
    assert profile.base_url not in target


def test_builtin_deepseek_factory_rejects_an_unreviewed_origin() -> None:
    profile = replace(
        deepseek_profile("deepseek-v4-flash"),
        base_url="https://example.invalid",
    )

    with pytest.raises(
        ProviderRegistryError,
        match="credential binding does not match",
    ):
        ProviderFactory().create_profile(
            profile,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )


def test_deepseek_profiles_read_only_their_bound_credentials() -> None:
    async def scenario() -> None:
        first_id = CredentialId.new()
        second_id = CredentialId.new()
        store = InMemorySecretStore()
        store.set_secret(first_id, SecretValue("first-provider-key"))
        store.set_secret(second_id, SecretValue("second-provider-key"))
        first_factory = FakeDeepSeekClientFactory((_successful_scenario(),))
        second_factory = FakeDeepSeekClientFactory((_successful_scenario(),))
        first = DeepSeekProvider(
            profile=deepseek_profile(
                "deepseek-v4-flash",
                profile_id=ProfileId.new(),
                credential_id=first_id,
            ),
            secret_store=store,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
            client_factory=first_factory,
        )
        second = DeepSeekProvider(
            profile=deepseek_profile(
                "deepseek-v4-flash",
                profile_id=ProfileId.new(),
                credential_id=second_id,
            ),
            secret_store=store,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
            client_factory=second_factory,
        )
        try:
            first_events = [
                event async for event in first.generate_stream(_request())
            ]
            second_events = [
                event async for event in second.generate_stream(_request())
            ]
        finally:
            await first.aclose()
            await second.aclose()

        assert first_events[-1].type is LLMEventType.COMPLETED
        assert second_events[-1].type is LLMEventType.COMPLETED
        assert first_factory.api_key_fingerprints == [
            hashlib.sha256(b"first-provider-key").digest()
        ]
        assert second_factory.api_key_fingerprints == [
            hashlib.sha256(b"second-provider-key").digest()
        ]
        assert first_factory.network_request_count == 0
        assert second_factory.network_request_count == 0

    asyncio.run(scenario())


def test_openai_and_deepseek_reserved_credentials_do_not_alias() -> None:
    store = InMemorySecretStore()
    store.set_secret(
        OPENAI_DEFAULT_CREDENTIAL_ID,
        SecretValue(_OPENAI_FAKE_KEY),
    )
    store.set_secret(
        DEEPSEEK_DEFAULT_CREDENTIAL_ID,
        SecretValue(_DEEPSEEK_FAKE_KEY),
    )

    openai_secret = store.get_secret(OPENAI_DEFAULT_CREDENTIAL_ID)
    deepseek_secret = store.get_secret(DEEPSEEK_DEFAULT_CREDENTIAL_ID)

    assert openai_secret is not None
    assert deepseek_secret is not None
    assert openai_secret.reveal() == _OPENAI_FAKE_KEY
    assert deepseek_secret.reveal() == _DEEPSEEK_FAKE_KEY


def test_factory_profiles_use_the_correct_provider_and_credential() -> None:
    async def scenario() -> None:
        store = InMemorySecretStore()
        store.set_secret(
            OPENAI_DEFAULT_CREDENTIAL_ID,
            SecretValue(_OPENAI_FAKE_KEY),
        )
        store.set_secret(
            DEEPSEEK_DEFAULT_CREDENTIAL_ID,
            SecretValue(_DEEPSEEK_FAKE_KEY),
        )
        openai_factory = FakeOpenAIClientFactory(
            (
                FakeOpenAIScenario(
                    events=(
                        OpenAIResponseEvent(
                            kind=OpenAIResponseEventKind.TEXT_DELTA,
                            raw_type="response.output_text.delta",
                            text="openai",
                        ),
                        OpenAIResponseEvent(
                            kind=OpenAIResponseEventKind.COMPLETED,
                            raw_type="response.completed",
                        ),
                    )
                ),
            )
        )
        deepseek_factory = FakeDeepSeekClientFactory(
            (_successful_scenario(),)
        )
        provider_factory = ProviderFactory(
            secret_store=store,
            openai_client_factory=openai_factory,
            deepseek_client_factory=deepseek_factory,
        )
        openai_provider = provider_factory.create_profile(
            openai_profile("gpt-5-mini"),
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )
        deepseek_provider = provider_factory.create_profile(
            deepseek_profile("deepseek-v4-flash"),
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )
        try:
            openai_events = [
                event
                async for event in openai_provider.generate_stream(
                    _request()
                )
            ]
            await openai_provider.aclose()
            assert openai_factory.clients[0].closed
            deepseek_events = [
                event
                async for event in deepseek_provider.generate_stream(
                    _request()
                )
            ]
        finally:
            await openai_provider.aclose()
            await deepseek_provider.aclose()

        assert isinstance(openai_provider, OpenAIProvider)
        assert isinstance(deepseek_provider, DeepSeekProvider)
        assert openai_events[-1].type is LLMEventType.COMPLETED
        assert deepseek_events[-1].type is LLMEventType.COMPLETED
        assert openai_factory.api_key_fingerprints == [
            hashlib.sha256(_OPENAI_FAKE_KEY.encode("utf-8")).digest()
        ]
        assert deepseek_factory.api_key_fingerprints == [
            hashlib.sha256(_DEEPSEEK_FAKE_KEY.encode("utf-8")).digest()
        ]
        assert openai_factory.network_request_count == 0
        assert deepseek_factory.network_request_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("profile_factory", "wrong_credential_id"),
    [
        (openai_profile, DEEPSEEK_DEFAULT_CREDENTIAL_ID),
        (deepseek_profile, OPENAI_DEFAULT_CREDENTIAL_ID),
    ],
)
def test_factory_rejects_cross_provider_credential_before_secret_read(
    profile_factory: Callable[..., ProviderProfile],
    wrong_credential_id: CredentialId,
) -> None:
    class _ExplodingStore(InMemorySecretStore):
        read_count = 0

        def get_secret(
            self,
            credential_id: CredentialId,
        ) -> SecretValue | None:
            del credential_id
            self.read_count += 1
            raise AssertionError("credential must not be read")

    profile = profile_factory(
        "test-model",
        credential_id=wrong_credential_id,
    )
    store = _ExplodingStore()
    openai_sdk = FakeOpenAIClientFactory()
    deepseek_sdk = FakeDeepSeekClientFactory()
    factory = ProviderFactory(
        secret_store=store,
        openai_client_factory=openai_sdk,
        deepseek_client_factory=deepseek_sdk,
    )

    with pytest.raises(
        ProviderRegistryError,
        match="credential binding does not match",
    ):
        factory.create_profile(
            profile,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )

    assert store.read_count == 0
    assert openai_sdk.create_count == 0
    assert deepseek_sdk.create_count == 0
    assert openai_sdk.network_request_count == 0
    assert deepseek_sdk.network_request_count == 0


@pytest.mark.parametrize(
    "profile",
    [
        replace(
            openai_profile("gpt-5-mini"),
            capabilities=replace(
                openai_profile("gpt-5-mini").capabilities,
                streaming=False,
            ),
        ),
        replace(
            deepseek_profile("deepseek-v4-flash"),
            capabilities=replace(
                deepseek_profile("deepseek-v4-flash").capabilities,
                streaming=False,
            ),
        ),
    ],
)
def test_profile_cannot_falsify_adapter_streaming_capability(
    profile: ProviderProfile,
) -> None:
    class _CountingStore(InMemorySecretStore):
        read_count = 0

        def get_secret(
            self,
            credential_id: CredentialId,
        ) -> SecretValue | None:
            self.read_count += 1
            return super().get_secret(credential_id)

    store = _CountingStore()
    openai_sdk = FakeOpenAIClientFactory()
    deepseek_sdk = FakeDeepSeekClientFactory()

    with pytest.raises(
        ProviderRegistryError,
        match="cannot change the adapter streaming capability",
    ):
        ProviderFactory(
            secret_store=store,
            openai_client_factory=openai_sdk,
            deepseek_client_factory=deepseek_sdk,
        ).create_profile(
            profile,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )

    assert store.read_count == 0
    assert openai_sdk.create_count == 0
    assert deepseek_sdk.create_count == 0
    assert openai_sdk.network_request_count == 0
    assert deepseek_sdk.network_request_count == 0


def test_runtime_stream_flag_does_not_rewrite_adapter_capabilities() -> None:
    class _CountingStore(InMemorySecretStore):
        read_count = 0

        def get_secret(
            self,
            credential_id: CredentialId,
        ) -> SecretValue | None:
            self.read_count += 1
            return super().get_secret(credential_id)

    async def scenario() -> None:
        store = _CountingStore()
        openai_sdk = FakeOpenAIClientFactory()
        deepseek_sdk = FakeDeepSeekClientFactory()
        factory = ProviderFactory(
            secret_store=store,
            openai_client_factory=openai_sdk,
            deepseek_client_factory=deepseek_sdk,
        )
        openai = factory.create_profile(
            openai_profile("gpt-5-mini"),
            timeout_seconds=30.0,
            max_retries=0,
            stream=False,
        )
        deepseek = factory.create_profile(
            deepseek_profile("deepseek-v4-flash"),
            timeout_seconds=30.0,
            max_retries=0,
            stream=False,
        )
        try:
            events = [
                event
                async for event in deepseek.generate_stream(_request())
            ]
        finally:
            await openai.aclose()
            await deepseek.aclose()

        assert openai.capabilities().streaming is True
        assert deepseek.capabilities().streaming is True
        assert events[-1].error_code == "unsupported_capability"
        assert store.read_count == 0
        assert openai_sdk.create_count == 0
        assert deepseek_sdk.create_count == 0
        assert openai_sdk.network_request_count == 0
        assert deepseek_sdk.network_request_count == 0

    asyncio.run(scenario())


def test_two_deepseek_credential_bindings_remain_isolated() -> None:
    async def scenario() -> None:
        first_id = CredentialId.new()
        second_id = CredentialId.new()
        bindings = CredentialBindingRegistry(
            (
                CredentialBinding(
                    credential_id=first_id,
                    provider_id=ProviderId("deepseek"),
                    allowed_origin=DEEPSEEK_OFFICIAL_ORIGIN,
                    display_name="First DeepSeek credential",
                ),
                CredentialBinding(
                    credential_id=second_id,
                    provider_id=ProviderId("deepseek"),
                    allowed_origin=DEEPSEEK_OFFICIAL_ORIGIN,
                    display_name="Second DeepSeek credential",
                ),
            )
        )
        store = InMemorySecretStore()
        store.set_secret(first_id, SecretValue("first-bound-secret"))
        store.set_secret(second_id, SecretValue("second-bound-secret"))
        sdk = FakeDeepSeekClientFactory(
            (_successful_scenario(), _successful_scenario())
        )
        factory = ProviderFactory(
            secret_store=store,
            deepseek_client_factory=sdk,
            credential_bindings=bindings,
        )
        first = factory.create_profile(
            deepseek_profile(
                "deepseek-v4-flash",
                profile_id=ProfileId.new(),
                credential_id=first_id,
            ),
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )
        second = factory.create_profile(
            deepseek_profile(
                "deepseek-v4-flash",
                profile_id=ProfileId.new(),
                credential_id=second_id,
            ),
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )
        try:
            assert [
                event async for event in first.generate_stream(_request())
            ][-1].type is LLMEventType.COMPLETED
            assert [
                event async for event in second.generate_stream(_request())
            ][-1].type is LLMEventType.COMPLETED
        finally:
            await first.aclose()
            await second.aclose()

        assert sdk.api_key_fingerprints == [
            hashlib.sha256(b"first-bound-secret").digest(),
            hashlib.sha256(b"second-bound-secret").digest(),
        ]

    asyncio.run(scenario())


def test_credential_binding_failure_has_only_fixed_safe_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "credential-content-never-log"
    profile = deepseek_profile(
        "deepseek-v4-flash",
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
    )

    caught: ProviderRegistryError | None = None
    try:
        ProviderFactory().create_profile(
            profile,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )
    except ProviderRegistryError as error:
        caught = error
        rendered = "".join(traceback.format_exception(error))
        with caplog.at_level(logging.ERROR):
            logging.getLogger("test.credential-binding").exception(
                "Credential binding rejected safely."
            )
        visible = rendered + caplog.text + repr(error)
    else:
        raise AssertionError("mismatched binding was accepted")

    assert secret not in visible
    assert "Authorization" not in visible
    assert caught is not None
    assert caught.__cause__ is None
    assert caught.__context__ is None


@pytest.mark.parametrize(
    "capabilities",
    [
        ProviderCapabilities(
            streaming=True,
            tools=True,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_MESSAGES,
            protocol=ApiProtocol.CHAT_COMPLETIONS,
        ),
        ProviderCapabilities(
            streaming=True,
            tools=False,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_PROVIDER_ITEMS,
            protocol=ApiProtocol.CHAT_COMPLETIONS,
        ),
    ],
)
def test_deepseek_profile_cannot_elevate_adapter_capabilities(
    capabilities: ProviderCapabilities,
) -> None:
    profile = replace(
        deepseek_profile("deepseek-v4-flash"),
        capabilities=capabilities,
    )

    with pytest.raises(ProviderRegistryError):
        ProviderFactory().create_profile(
            profile,
            timeout_seconds=30.0,
            max_retries=0,
            stream=True,
        )


def test_profile_rejects_capability_protocol_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match="profile protocol and capabilities must match",
    ):
        replace(
            deepseek_profile("deepseek-v4-flash"),
            capabilities=ProviderCapabilities(
                streaming=True,
                tools=False,
                embeddings=False,
                continuation_mode=ContinuationMode.REPLAY_MESSAGES,
                protocol=ApiProtocol.RESPONSES,
            ),
        )


def test_credential_binding_requires_exact_origin() -> None:
    credential_id = CredentialId.new()
    registry = CredentialBindingRegistry(
        (
            CredentialBinding(
                credential_id=credential_id,
                provider_id=ProviderId("openai"),
                allowed_origin=OPENAI_OFFICIAL_ORIGIN,
                display_name="OpenAI only",
            ),
        )
    )
    profile = deepseek_profile(
        "deepseek-v4-flash",
        credential_id=credential_id,
    )

    with pytest.raises(ProviderRegistryError):
        registry.require_for_profile(profile)


def test_registry_rejects_duplicates_unknown_profiles_and_fallback() -> None:
    class _Builder:
        def build(
            self,
            profile: ProviderProfile,
            options: ProviderBuildOptions,
        ) -> FakeProvider:
            del profile, options
            return FakeProvider()

    registry = ProviderRegistry()
    provider_id = ProviderId("custom")
    registry.register(provider_id, ApiProtocol.INTERNAL, _Builder())
    options = ProviderBuildOptions(
        secret_store=None,
        credential_bindings=CredentialBindingRegistry(),
        timeout_seconds=30.0,
        max_retries=0,
        stream=True,
    )
    credential_free_profile = ProviderProfile(
        profile_id=ProfileId.new(),
        display_name="Credential-free custom provider",
        provider_id=provider_id,
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
    assert isinstance(
        registry.build(credential_free_profile, options),
        FakeProvider,
    )
    with pytest.raises(ProviderRegistryError, match="already registered"):
        registry.register(
            provider_id,
            ApiProtocol.INTERNAL,
            _Builder(),
        )

    with pytest.raises(ProviderRegistryError, match="No provider builder"):
        registry.build(
            replace(
                deepseek_profile("deepseek-v4-flash"),
                credential_id=None,
            ),
            options,
        )


def test_registry_rejects_bad_binding_before_untrusted_builder() -> None:
    class _CountingStore(InMemorySecretStore):
        read_count = 0

        def get_secret(
            self,
            credential_id: CredentialId,
        ) -> SecretValue | None:
            self.read_count += 1
            return super().get_secret(credential_id)

    class _UnsafeBuilder:
        build_count = 0
        client_create_count = 0

        def build(
            self,
            profile: ProviderProfile,
            options: ProviderBuildOptions,
        ) -> FakeProvider:
            self.build_count += 1
            if options.secret_store is not None:
                options.secret_store.get_secret(
                    profile.credential_id
                    or OPENAI_DEFAULT_CREDENTIAL_ID
                )
            self.client_create_count += 1
            return FakeProvider()

    store = _CountingStore()
    builder = _UnsafeBuilder()
    registry = ProviderRegistry()
    registry.register(
        ProviderId("deepseek"),
        ApiProtocol.CHAT_COMPLETIONS,
        builder,
    )
    bindings = CredentialBindingRegistry(
        (
            CredentialBinding(
                credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
                provider_id=ProviderId("openai"),
                allowed_origin=OPENAI_OFFICIAL_ORIGIN,
                display_name="OpenAI only",
            ),
        )
    )
    profile = deepseek_profile(
        "deepseek-v4-flash",
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
    )

    with pytest.raises(
        ProviderRegistryError,
        match="credential binding does not match",
    ):
        registry.build(
            profile,
            ProviderBuildOptions(
                secret_store=store,
                credential_bindings=bindings,
                timeout_seconds=30.0,
                max_retries=0,
                stream=True,
            ),
        )

    assert builder.build_count == 0
    assert builder.client_create_count == 0
    assert store.read_count == 0
