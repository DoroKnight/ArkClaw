"""Unit tests for OllamaProvider and Ollama provider factory integration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from arkclaw.config.models import ProviderName, RuntimeConfig
from arkclaw.config.provider_profiles import ollama_profile
from arkclaw.domain.events import LLMEventType
from arkclaw.domain.models import (
    ChatMessage,
    LLMRequest,
    MessageRole,
)
from arkclaw.infrastructure.llm.ollama_provider import (
    OLLAMA_MAXIMUM_CAPABILITIES,
    OllamaProvider,
)
from arkclaw.infrastructure.llm.provider_factory import ProviderFactory


def test_ollama_profile_properties() -> None:
    profile = ollama_profile("llama3", "http://localhost:11434")
    assert profile.provider_id.value == "ollama"
    assert profile.model == "llama3"
    assert profile.base_url == "http://localhost:11434"
    assert profile.credential_id is None
    assert profile.capabilities.streaming is True
    assert profile.capabilities.tools is False


def test_factory_creates_ollama_provider() -> None:
    config = RuntimeConfig(
        provider=ProviderName.OLLAMA,
        ollama_model="qwen2.5",
        ollama_base_url="http://127.0.0.1:11434",
    )
    provider = ProviderFactory().create(config)
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama-qwen2.5"
    assert provider.capabilities() == OLLAMA_MAXIMUM_CAPABILITIES
    asyncio.run(provider.aclose())


def test_ollama_provider_streaming_mock() -> None:
    async def scenario() -> None:
        profile = ollama_profile("llama3", "http://localhost:11434")
        provider = OllamaProvider(profile=profile)

        mock_chunk_1 = MagicMock()
        mock_chunk_1.choices = [MagicMock(delta=MagicMock(content="Hello"))]
        mock_chunk_2 = MagicMock()
        mock_chunk_2.choices = [MagicMock(delta=MagicMock(content=" world!"))]

        async def fake_stream():
            yield mock_chunk_1
            yield mock_chunk_2

        provider._client.chat.completions.create = AsyncMock(
            return_value=fake_stream()
        )

        request = LLMRequest(
            instructions="You are ArkClaw.",
            messages=(ChatMessage(role=MessageRole.USER, content="hi"),),
        )

        events = [event async for event in provider.generate_stream(request)]
        assert len(events) == 3
        assert events[0].type is LLMEventType.TEXT_DELTA
        assert events[0].text == "Hello"
        assert events[1].type is LLMEventType.TEXT_DELTA
        assert events[1].text == " world!"
        assert events[2].type is LLMEventType.COMPLETED

        await provider.aclose()

    asyncio.run(scenario())


def test_ollama_provider_handles_connection_error() -> None:
    async def scenario() -> None:
        profile = ollama_profile("llama3", "http://localhost:11434")
        provider = OllamaProvider(profile=profile)

        provider._client.chat.completions.create = AsyncMock(
            side_effect=ConnectionError("Could not connect to Ollama daemon")
        )

        request = LLMRequest(
            instructions="",
            messages=(ChatMessage(role=MessageRole.USER, content="test"),),
        )

        events = [event async for event in provider.generate_stream(request)]
        assert len(events) == 1
        assert events[0].type is LLMEventType.ERROR

        await provider.aclose()

    asyncio.run(scenario())
