"""Narrow, sanitizing Chat Completions boundary for DeepSeek."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, TypedDict, cast

import openai
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

from arkclaw.config.provider_profiles import DEEPSEEK_OFFICIAL_BASE_URL

type ChatMessageData = dict[str, str]
type DeepSeekFailureCode = Literal[
    "content_filtered",
    "invalid_response",
    "output_budget_exhausted",
    "provider_unavailable",
    "unsupported_capability",
]


class ThinkingMode(StrEnum):
    """Reviewed DeepSeek thinking modes exposed by this adapter."""

    DISABLED = "disabled"


class _ThinkingParameters(TypedDict):
    type: Literal["disabled"]


class _DeepSeekExtraBody(TypedDict):
    thinking: _ThinkingParameters


@dataclass(frozen=True, slots=True, repr=False)
class DeepSeekRequest:
    """Typed request with all message content redacted from repr."""

    model: str
    messages: tuple[ChatMessageData, ...]
    max_tokens: int
    stream: Literal[True] = True
    thinking_mode: ThinkingMode = ThinkingMode.DISABLED

    def __post_init__(self) -> None:
        if self.thinking_mode is not ThinkingMode.DISABLED:
            raise ValueError("thinking_mode must be disabled")
        if self.stream is not True:
            raise ValueError("DeepSeek requests must be streaming")
        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")

    def __repr__(self) -> str:
        return (
            "<DeepSeekRequest "
            f"model={self.model!r} stream=True messages=<redacted>>"
        )


class DeepSeekEventKind(StrEnum):
    METADATA = "metadata"
    TEXT_DELTA = "text_delta"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, repr=False)
class DeepSeekEvent:
    kind: DeepSeekEventKind
    text: str = ""
    failure_code: DeepSeekFailureCode | None = None
    finish_reason: str = ""

    def __repr__(self) -> str:
        return (
            "<DeepSeekEvent "
            f"kind={self.kind.value!r} payload=<redacted>>"
        )


class DeepSeekSDKError(Exception):
    """Sanitized SDK failure that never retains a raw exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("The DeepSeek SDK operation failed safely.")


class DeepSeekStream(Protocol):
    def __aiter__(self) -> AsyncIterator[DeepSeekEvent]: ...

    async def __anext__(self) -> DeepSeekEvent: ...

    async def close(self) -> None: ...


class DeepSeekClient(Protocol):
    async def create(self, request: DeepSeekRequest) -> DeepSeekStream: ...

    async def close(self) -> None: ...


class DeepSeekClientFactory(Protocol):
    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> DeepSeekClient: ...


class OfficialDeepSeekClientFactory:
    """Create clients only for the reviewed official DeepSeek Origin."""

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> DeepSeekClient:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_OFFICIAL_BASE_URL,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        return OfficialDeepSeekClient(client)


class OfficialDeepSeekClient:
    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client
        self._closed = False

    async def create(self, request: DeepSeekRequest) -> DeepSeekStream:
        safe_error: DeepSeekSDKError | None = None
        extra_body: _DeepSeekExtraBody = {
            "thinking": {"type": "disabled"}
        }
        try:
            stream = await self._client.chat.completions.create(
                model=request.model,
                messages=cast(
                    list[ChatCompletionMessageParam],
                    list(request.messages),
                ),
                max_tokens=request.max_tokens,
                stream=True,
                extra_body=extra_body,
            )
            return OfficialDeepSeekStream(stream)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            safe_error = _map_sdk_error(error)
        raise safe_error from None

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._client.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise DeepSeekSDKError("resource_close_failed") from None
        self._closed = True


class OfficialDeepSeekStream:
    def __init__(
        self,
        stream: AsyncStream[ChatCompletionChunk],
    ) -> None:
        self._stream = stream
        self._pending: deque[DeepSeekEvent] = deque()
        self._closed = False

    def __aiter__(self) -> AsyncIterator[DeepSeekEvent]:
        return self

    async def __anext__(self) -> DeepSeekEvent:
        if self._closed:
            raise StopAsyncIteration
        if self._pending:
            return self._pending.popleft()
        try:
            chunk = await self._stream.__anext__()
            self._pending.extend(_normalize_chunk(chunk))
        except StopAsyncIteration:
            raise
        except asyncio.CancelledError:
            raise
        except DeepSeekSDKError:
            raise
        except Exception as error:
            raise _map_sdk_error(error) from None
        if not self._pending:
            raise DeepSeekSDKError("invalid_response")
        return self._pending.popleft()

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._stream.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise DeepSeekSDKError("resource_close_failed") from None
        self._closed = True


def _normalize_chunk(chunk: ChatCompletionChunk) -> tuple[DeepSeekEvent, ...]:
    raw = chunk.model_dump(mode="json", exclude_none=False)
    choices = raw.get("choices")
    if not isinstance(choices, list):
        raise DeepSeekSDKError("invalid_response")
    if not choices:
        return (DeepSeekEvent(kind=DeepSeekEventKind.METADATA),)
    if len(choices) != 1 or not isinstance(choices[0], dict):
        raise DeepSeekSDKError("invalid_response")
    choice = choices[0]
    if choice.get("index") != 0:
        raise DeepSeekSDKError("invalid_response")
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        raise DeepSeekSDKError("invalid_response")
    content = delta.get("content")
    if content is not None and not isinstance(content, str):
        raise DeepSeekSDKError("invalid_response")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise DeepSeekSDKError("invalid_response")

    events: list[DeepSeekEvent] = []
    if content:
        events.append(
            DeepSeekEvent(
                kind=DeepSeekEventKind.TEXT_DELTA,
                text=content,
            )
        )
    if finish_reason is not None:
        events.append(_terminal_event(finish_reason))
    if not events:
        events.append(DeepSeekEvent(kind=DeepSeekEventKind.METADATA))
    return tuple(events)


def _terminal_event(finish_reason: str) -> DeepSeekEvent:
    if finish_reason == "stop":
        return DeepSeekEvent(
            kind=DeepSeekEventKind.COMPLETED,
            finish_reason=finish_reason,
        )
    failure_codes: dict[str, DeepSeekFailureCode] = {
        "length": "output_budget_exhausted",
        "content_filter": "content_filtered",
        "tool_calls": "unsupported_capability",
        "insufficient_system_resource": "provider_unavailable",
    }
    return DeepSeekEvent(
        kind=DeepSeekEventKind.FAILED,
        failure_code=failure_codes.get(
            finish_reason,
            "invalid_response",
        ),
        finish_reason=finish_reason,
    )


def _map_sdk_error(error: Exception) -> DeepSeekSDKError:
    if isinstance(error, DeepSeekSDKError):
        return DeepSeekSDKError(error.code)
    if isinstance(error, openai.AuthenticationError):
        return DeepSeekSDKError("invalid_api_key")
    if isinstance(error, openai.PermissionDeniedError):
        return DeepSeekSDKError("permission_denied")
    if isinstance(error, openai.APITimeoutError):
        return DeepSeekSDKError("request_timeout")
    if isinstance(error, openai.APIConnectionError):
        return DeepSeekSDKError("network_unavailable")
    if isinstance(error, openai.RateLimitError):
        return DeepSeekSDKError("rate_limited")
    if isinstance(error, openai.NotFoundError):
        return DeepSeekSDKError("model_not_found")
    if isinstance(
        error,
        (openai.BadRequestError, openai.UnprocessableEntityError),
    ):
        return DeepSeekSDKError("invalid_request")
    if isinstance(error, openai.APIStatusError):
        if error.status_code == 401:
            return DeepSeekSDKError("invalid_api_key")
        if error.status_code == 403:
            return DeepSeekSDKError("permission_denied")
        if error.status_code == 404:
            return DeepSeekSDKError("model_not_found")
        if error.status_code == 408:
            return DeepSeekSDKError("request_timeout")
        if error.status_code == 429:
            return DeepSeekSDKError("rate_limited")
        if error.status_code >= 500:
            return DeepSeekSDKError("provider_unavailable")
        return DeepSeekSDKError("invalid_request")
    return DeepSeekSDKError("provider_unavailable")
