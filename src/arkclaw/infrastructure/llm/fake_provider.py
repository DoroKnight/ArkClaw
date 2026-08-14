"""Deterministic provider for development and automated tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence

from arkclaw.domain.errors import ProviderCapabilityError, ProviderError
from arkclaw.domain.events import LLMEvent
from arkclaw.domain.models import (
    ApiProtocol,
    ContinuationMode,
    Embedding,
    LLMRequest,
    MessageRole,
    ProviderCapabilities,
    ProviderContinuation,
)


class FakeProvider:
    """Emit deterministic events without network or credentials."""

    def __init__(
        self,
        *,
        response_text: str = "你好, 我是 ArkClaw 的 Fake Agent.",
        echo_user_message: bool = False,
        chunk_size: int = 6,
        delay_seconds: float = 0.0,
        stream: bool = True,
        script: Sequence[LLMEvent] | None = None,
        responder: Callable[[LLMRequest], str] | None = None,
        continuation: ProviderContinuation | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")
        self._response_text = response_text
        self._echo_user_message = echo_user_message
        self._chunk_size = chunk_size
        self._delay_seconds = delay_seconds
        self._stream = stream
        self._script = tuple(script) if script is not None else None
        self._responder = responder
        self._continuation = continuation
        self._closed = False
        self._active_stream_count = 0

    @property
    def name(self) -> str:
        return "fake"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tools=True,
            embeddings=False,
            continuation_mode=ContinuationMode.REPLAY_MESSAGES,
            protocol=ApiProtocol.INTERNAL,
        )

    @property
    def closed(self) -> bool:
        """Return whether provider-wide resources have been closed."""

        return self._closed

    @property
    def active_stream_count(self) -> int:
        """Expose active stream count for deterministic lifecycle tests."""

        return self._active_stream_count

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self._ensure_open()
        self._active_stream_count += 1
        try:
            if self._script is not None:
                for event in self._script:
                    await self._delay()
                    yield event
                return

            response = self._resolve_response(request)
            if not self._stream:
                await self._delay()
                yield LLMEvent.text_delta(response)
                yield LLMEvent.completed(self._continuation)
                return

            for start in range(0, len(response), self._chunk_size):
                await self._delay()
                yield LLMEvent.text_delta(response[start : start + self._chunk_size])
            yield LLMEvent.completed(self._continuation)
        finally:
            self._active_stream_count -= 1

    async def embed(self, texts: Sequence[str]) -> Sequence[Embedding]:
        del texts
        self._ensure_open()
        raise ProviderCapabilityError(
            code="embeddings_not_supported",
            message="FakeProvider does not implement embeddings.",
        )

    async def aclose(self) -> None:
        """Idempotently close this no-resource provider."""

        self._closed = True

    def _resolve_response(self, request: LLMRequest) -> str:
        if self._responder is not None:
            return self._responder(request)
        if self._echo_user_message:
            last_user = next(
                (
                    message.content
                    for message in reversed(request.messages)
                    if message.role is MessageRole.USER
                ),
                "",
            )
            return f"FakeProvider 已收到: {last_user}"
        return self._response_text

    async def _delay(self) -> None:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError(
                code="provider_closed",
                message="The provider has already been closed.",
            )
