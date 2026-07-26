import asyncio

import pytest
from tests.fakes.openai_sdk import (
    FakeOpenAIClientFactory,
    FakeOpenAIScenario,
)

from sjtuclaw.application.context_manager import ContextManager
from sjtuclaw.config.models import ProviderName, RuntimeConfig
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.events import LLMEvent, LLMEventType
from sjtuclaw.domain.models import CredentialId, UserMessageCommand
from sjtuclaw.infrastructure.llm.openai_provider import OpenAIProvider
from sjtuclaw.infrastructure.llm.openai_sdk import (
    JSONObject,
    OpenAIResponseEvent,
    OpenAIResponseEventKind,
)
from sjtuclaw.infrastructure.llm.provider_factory import (
    ProviderFactory,
    ProviderNotImplementedError,
)


def _collect_provider_events(config: RuntimeConfig) -> list[LLMEvent]:
    async def collect() -> list[LLMEvent]:
        request = ContextManager().build_request(UserMessageCommand.create("hello"))
        provider = ProviderFactory().create(config)
        try:
            return [event async for event in provider.generate_stream(request)]
        finally:
            await provider.aclose()

    return asyncio.run(collect())


def test_factory_creates_fake_provider_by_default() -> None:
    async def scenario() -> None:
        provider = ProviderFactory().create(RuntimeConfig())
        try:
            assert provider.name == "fake"
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_non_streaming_fake_provider_keeps_unified_event_protocol() -> None:
    events = _collect_provider_events(RuntimeConfig(stream=False))

    assert [event.type for event in events] == [
        LLMEventType.TEXT_DELTA,
        LLMEventType.COMPLETED,
    ]
    assert events[0].text == "FakeProvider 已收到: hello"


def test_factory_creates_openai_provider_without_reading_credential() -> None:
    class ExplodingStore:
        def has_secret(self, credential_id: CredentialId) -> bool:
            del credential_id
            raise AssertionError("credential was read while constructing provider")

        def get_secret(self, credential_id: CredentialId) -> None:
            del credential_id
            raise AssertionError("credential was read while constructing provider")

        def set_secret(
            self,
            credential_id: CredentialId,
            value: SecretValue,
        ) -> None:
            del credential_id, value
            raise AssertionError("credential was written")

        def delete_secret(self, credential_id: CredentialId) -> None:
            del credential_id
            raise AssertionError("credential was deleted")

        def has_openai_api_key(self) -> bool:
            raise AssertionError("credential was read while constructing provider")

        def get_openai_api_key(self) -> None:
            raise AssertionError("credential was read while constructing provider")

        def set_openai_api_key(self, value: SecretValue) -> None:
            del value
            raise AssertionError("credential was written")

        def delete_openai_api_key(self) -> None:
            raise AssertionError("credential was deleted")

    provider = ProviderFactory(secret_store=ExplodingStore()).create(
        RuntimeConfig(provider=ProviderName.OPENAI)
    )
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"
    asyncio.run(provider.aclose())


def test_factory_openai_provider_uses_injected_store_and_fake_sdk() -> None:
    async def scenario() -> None:
        output: JSONObject = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [],
        }
        fake_sdk = FakeOpenAIClientFactory(
            (
                FakeOpenAIScenario(
                    events=(
                        OpenAIResponseEvent(
                            kind=OpenAIResponseEventKind.TEXT_DELTA,
                            raw_type="response.output_text.delta",
                            text="ok",
                        ),
                        OpenAIResponseEvent(
                            kind=OpenAIResponseEventKind.COMPLETED,
                            raw_type="response.completed",
                            output_items=(output,),
                        ),
                    )
                ),
            )
        )
        store = InMemorySecretStore()
        store.set_openai_api_key(SecretValue("sk-test-never-use-this-value"))
        provider = ProviderFactory(
            secret_store=store,
            openai_client_factory=fake_sdk,
        ).create(RuntimeConfig(provider=ProviderName.OPENAI))
        try:
            request = ContextManager().build_request(
                UserMessageCommand.create("hello")
            )
            events = [event async for event in provider.generate_stream(request)]
        finally:
            await provider.aclose()
        assert events[-1].type is LLMEventType.COMPLETED
        assert fake_sdk.network_request_count == 0

    asyncio.run(scenario())


def test_factory_fake_provider_never_reads_injected_secret_store() -> None:
    class CountingStore(InMemorySecretStore):
        read_count = 0

        def get_openai_api_key(self) -> SecretValue | None:
            self.read_count += 1
            return super().get_openai_api_key()

    store = CountingStore()
    provider = ProviderFactory(secret_store=store).create(RuntimeConfig())
    assert provider.name == "fake"
    assert store.read_count == 0
    asyncio.run(provider.aclose())


def test_ollama_provider_remains_explicitly_unimplemented() -> None:
    with pytest.raises(
        ProviderNotImplementedError,
        match=r"Provider 'ollama'.*not implemented",
    ):
        ProviderFactory().create(RuntimeConfig(provider=ProviderName.OLLAMA))
