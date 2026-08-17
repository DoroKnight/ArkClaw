"""Ollama local AI provider using an independent local endpoint boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk

from arkclaw.domain.errors import ProviderCapabilityError
from arkclaw.domain.events import LLMEvent
from arkclaw.domain.models import (
    ApiProtocol,
    ContinuationMode,
    Embedding,
    LLMRequest,
    ProviderCapabilities,
    ProviderProfile,
)

_ADAPTER_VERSION = "1"
OLLAMA_MAXIMUM_CAPABILITIES = ProviderCapabilities(
    streaming=True,
    tools=False,
    embeddings=False,
    continuation_mode=ContinuationMode.REPLAY_MESSAGES,
    protocol=ApiProtocol.OLLAMA_CHAT,
)


class OllamaProvider:
    """Local Ollama LLM provider."""

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        stream: bool = True,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._profile = profile
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._stream = stream
        self._capabilities = capabilities or OLLAMA_MAXIMUM_CAPABILITIES
        self._closed = False
        base_url = (profile.base_url or "http://localhost:11434").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama",
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def name(self) -> str:
        return f"ollama-{self._profile.model}"

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def generate_stream(
        self, request: LLMRequest
    ) -> AsyncIterator[LLMEvent]:
        if self._closed:
            yield LLMEvent.failure(
                code="provider_closed",
                message="The provider has already been closed.",
            )
            return

        messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in request.messages
        ]
        if request.instructions:
            messages.insert(0, {"role": "system", "content": request.instructions})

        try:
            raw_response = await self._client.chat.completions.create(
                model=self._profile.model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
            stream = cast(AsyncStream[ChatCompletionChunk], raw_response)
            async for chunk in stream:
                if self._closed:
                    break
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield LLMEvent.text_delta(delta.content)

            yield LLMEvent.completed()
        except Exception as exc:
            yield LLMEvent.failure(
                code="network_unavailable"
                if "ConnectError" in str(type(exc))
                else "provider_unavailable",
                message=f"Ollama local service error: {exc}",
            )

    async def embed(self, texts: Sequence[str]) -> Sequence[Embedding]:
        raise ProviderCapabilityError(
            "unsupported_capability",
            "Ollama embeddings not configured in this profile",
        )

    async def aclose(self) -> None:
        self._closed = True
        await self._client.close()
