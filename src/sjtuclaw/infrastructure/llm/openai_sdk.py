"""Narrow, sanitizing boundary around the official OpenAI Python SDK."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, cast

import openai
from openai import AsyncOpenAI, AsyncStream
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseInputParam,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ToolParam,
)
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_error_event import ResponseErrorEvent
from openai.types.responses.response_failed_event import ResponseFailedEvent
from openai.types.responses.response_function_call_arguments_delta_event import (
    ResponseFunctionCallArgumentsDeltaEvent,
)
from openai.types.responses.response_function_call_arguments_done_event import (
    ResponseFunctionCallArgumentsDoneEvent,
)
from openai.types.responses.response_incomplete_event import ResponseIncompleteEvent
from openai.types.responses.response_output_item_added_event import (
    ResponseOutputItemAddedEvent,
)
from openai.types.responses.response_refusal_delta_event import (
    ResponseRefusalDeltaEvent,
)
from openai.types.responses.response_stream_event import ResponseStreamEvent
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

type JSONScalar = bool | int | float | str | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]
type OpenAIResponseFailureCode = Literal["output_budget_exhausted"]


@dataclass(frozen=True, slots=True, repr=False)
class OpenAIRequest:
    """A typed request whose sensitive payload is excluded from repr."""

    model: str
    instructions: str
    input: tuple[JSONObject, ...]
    tools: tuple[JSONObject, ...]
    max_output_tokens: int
    stream: bool
    store: Literal[False] = False

    def __repr__(self) -> str:
        return (
            "<OpenAIRequest "
            f"model={self.model!r} stream={self.stream!r} store=False "
            "input=<redacted> tools=<redacted>>"
        )


class OpenAIResponseEventKind(StrEnum):
    """Small event vocabulary consumed by OpenAIProvider."""

    METADATA = "metadata"
    TEXT_DELTA = "text_delta"
    TOOL_ADDED = "tool_added"
    TOOL_ARGUMENTS_DELTA = "tool_arguments_delta"
    TOOL_ARGUMENTS_DONE = "tool_arguments_done"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, repr=False)
class OpenAIResponseEvent:
    """SDK-independent event with only fields needed by the provider."""

    kind: OpenAIResponseEventKind
    raw_type: str
    text: str = ""
    output_index: int | None = None
    item_id: str = ""
    call_id: str = ""
    name: str = ""
    arguments: str = ""
    output_items: tuple[JSONObject, ...] = ()
    failure_code: OpenAIResponseFailureCode | None = None

    def __repr__(self) -> str:
        return (
            "<OpenAIResponseEvent "
            f"kind={self.kind.value!r} raw_type={self.raw_type!r} payload=<redacted>>"
        )


class OpenAISDKError(Exception):
    """Sanitized SDK failure that never retains a raw SDK exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("The OpenAI SDK operation failed safely.")


class OpenAIResponseStream(Protocol):
    """Minimal async response-stream interface used by the provider."""

    def __aiter__(self) -> AsyncIterator[OpenAIResponseEvent]:
        """Return the event iterator."""

    async def __anext__(self) -> OpenAIResponseEvent:
        """Return one normalized event."""

    async def close(self) -> None:
        """Close the response body idempotently."""


class OpenAIResponsesClient(Protocol):
    """Minimal client interface used by OpenAIProvider."""

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        """Create a streaming or buffered response."""

    async def close(self) -> None:
        """Close the SDK client idempotently."""


class OpenAIClientFactory(Protocol):
    """Construct a client for one credential fingerprint generation."""

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> OpenAIResponsesClient:
        """Create a client without retaining the credential in the factory."""


class OfficialOpenAIClientFactory:
    """Production factory backed by ``openai.AsyncOpenAI``."""

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> OpenAIResponsesClient:
        client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        return OfficialOpenAIResponsesClient(client)


class OfficialOpenAIResponsesClient:
    """Translate public SDK objects into the narrow provider boundary."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client
        self._closed = False

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        safe_error: OpenAISDKError | None = None
        try:
            if request.stream:
                stream = await self._client.responses.create(
                    model=request.model,
                    instructions=request.instructions,
                    input=cast(ResponseInputParam, list(request.input)),
                    tools=cast(list[ToolParam], list(request.tools)),
                    max_output_tokens=request.max_output_tokens,
                    store=False,
                    stream=True,
                )
                return OfficialOpenAIResponseStream(stream)

            response = await self._client.responses.create(
                model=request.model,
                instructions=request.instructions,
                input=cast(ResponseInputParam, list(request.input)),
                tools=cast(list[ToolParam], list(request.tools)),
                max_output_tokens=request.max_output_tokens,
                store=False,
                stream=False,
            )
            return BufferedOpenAIResponseStream(_normalize_response(response))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            safe_error = _map_sdk_error(error)

        raise safe_error from None

    async def close(self) -> None:
        if self._closed:
            return
        close_failed = False
        try:
            await self._client.close()
        except Exception:
            close_failed = True
        if close_failed:
            raise OpenAISDKError("resource_close_failed") from None
        self._closed = True


class OfficialOpenAIResponseStream:
    """Normalize and explicitly close an official SDK async stream."""

    def __init__(self, stream: AsyncStream[ResponseStreamEvent]) -> None:
        self._stream = stream
        self._closed = False

    def __aiter__(self) -> AsyncIterator[OpenAIResponseEvent]:
        return self

    async def __anext__(self) -> OpenAIResponseEvent:
        safe_error: OpenAISDKError | None = None
        try:
            event = await self._stream.__anext__()
            return _normalize_stream_event(event)
        except StopAsyncIteration:
            raise
        except asyncio.CancelledError:
            raise
        except OpenAISDKError:
            raise
        except Exception as error:
            safe_error = _map_sdk_error(error)

        raise safe_error from None

    async def close(self) -> None:
        if self._closed:
            return
        close_failed = False
        try:
            await self._stream.close()
        except Exception:
            close_failed = True
        if close_failed:
            raise OpenAISDKError("resource_close_failed") from None
        self._closed = True


class BufferedOpenAIResponseStream:
    """Present a non-streaming response through the same stream protocol."""

    def __init__(self, events: tuple[OpenAIResponseEvent, ...]) -> None:
        self._events = events
        self._index = 0
        self._closed = False

    def __aiter__(self) -> AsyncIterator[OpenAIResponseEvent]:
        return self

    async def __anext__(self) -> OpenAIResponseEvent:
        if self._closed or self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def close(self) -> None:
        self._closed = True


def _normalize_stream_event(event: ResponseStreamEvent) -> OpenAIResponseEvent:
    if isinstance(event, ResponseTextDeltaEvent):
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.TEXT_DELTA,
            raw_type=event.type,
            text=event.delta,
        )
    if isinstance(event, ResponseRefusalDeltaEvent):
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.TEXT_DELTA,
            raw_type=event.type,
            text=event.delta,
        )
    if isinstance(event, ResponseOutputItemAddedEvent):
        item = event.item
        if isinstance(item, ResponseFunctionToolCall):
            return OpenAIResponseEvent(
                kind=OpenAIResponseEventKind.TOOL_ADDED,
                raw_type=event.type,
                output_index=event.output_index,
                item_id=item.id or "",
                call_id=item.call_id,
                name=item.name,
            )
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.METADATA,
            raw_type=event.type,
            output_index=event.output_index,
            item_id=item.id or "",
        )
    if isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.TOOL_ARGUMENTS_DELTA,
            raw_type=event.type,
            output_index=event.output_index,
            item_id=event.item_id,
            arguments=event.delta,
        )
    if isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.TOOL_ARGUMENTS_DONE,
            raw_type=event.type,
            output_index=event.output_index,
            item_id=event.item_id,
            name=event.name,
            arguments=event.arguments,
        )
    if isinstance(event, ResponseCompletedEvent):
        if event.response.status != "completed":
            return OpenAIResponseEvent(
                kind=OpenAIResponseEventKind.FAILED,
                raw_type=event.type,
                failure_code=_response_failure_code(event.response),
            )
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.COMPLETED,
            raw_type=event.type,
            output_items=_dump_output_items(event.response),
        )
    if isinstance(event, ResponseIncompleteEvent):
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.FAILED,
            raw_type=event.type,
            failure_code=_response_failure_code(event.response),
        )
    if isinstance(event, (ResponseFailedEvent, ResponseErrorEvent)):
        return OpenAIResponseEvent(
            kind=OpenAIResponseEventKind.FAILED,
            raw_type=event.type,
        )
    return OpenAIResponseEvent(
        kind=OpenAIResponseEventKind.METADATA,
        raw_type=event.type,
    )


def _normalize_response(response: Response) -> tuple[OpenAIResponseEvent, ...]:
    events: list[OpenAIResponseEvent] = []
    for output_index, item in enumerate(response.output):
        if isinstance(item, ResponseOutputMessage):
            for content in item.content:
                if isinstance(content, ResponseOutputText) and content.text:
                    events.append(
                        OpenAIResponseEvent(
                            kind=OpenAIResponseEventKind.TEXT_DELTA,
                            raw_type="response.output_text.done",
                            text=content.text,
                        )
                    )
                elif isinstance(content, ResponseOutputRefusal) and content.refusal:
                    events.append(
                        OpenAIResponseEvent(
                            kind=OpenAIResponseEventKind.TEXT_DELTA,
                            raw_type="response.refusal.done",
                            text=content.refusal,
                        )
                    )
        elif isinstance(item, ResponseFunctionToolCall):
            events.extend(
                (
                    OpenAIResponseEvent(
                        kind=OpenAIResponseEventKind.TOOL_ADDED,
                        raw_type="response.output_item.added",
                        output_index=output_index,
                        item_id=item.id or "",
                        call_id=item.call_id,
                        name=item.name,
                    ),
                    OpenAIResponseEvent(
                        kind=OpenAIResponseEventKind.TOOL_ARGUMENTS_DONE,
                        raw_type="response.function_call_arguments.done",
                        output_index=output_index,
                        item_id=item.id or "",
                        name=item.name,
                        arguments=item.arguments,
                    ),
                )
            )

    output_items = _dump_output_items(response)
    kind = (
        OpenAIResponseEventKind.COMPLETED
        if response.status == "completed"
        else OpenAIResponseEventKind.FAILED
    )
    events.append(
        OpenAIResponseEvent(
            kind=kind,
            raw_type=f"response.{response.status or 'failed'}",
            output_items=output_items,
            failure_code=_response_failure_code(response),
        )
    )
    return tuple(events)


def _response_failure_code(
    response: Response,
) -> OpenAIResponseFailureCode | None:
    details = response.incomplete_details
    if (
        response.status == "incomplete"
        and details is not None
        and details.reason == "max_output_tokens"
    ):
        return "output_budget_exhausted"
    return None


def _dump_output_items(response: Response) -> tuple[JSONObject, ...]:
    output: list[JSONObject] = []
    for item in response.output:
        raw_item: object = item.model_dump(mode="json", exclude_none=True)
        normalized = _normalize_json(raw_item)
        if not isinstance(normalized, dict):
            raise OpenAISDKError("invalid_response")
        output.append(normalized)
    return tuple(output)


def _normalize_json(value: object, *, depth: int = 0) -> JSONValue:
    if depth > 32:
        raise OpenAISDKError("invalid_response")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OpenAISDKError("invalid_response")
        return value
    if isinstance(value, list):
        return [_normalize_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        result: JSONObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise OpenAISDKError("invalid_response")
            result[key] = _normalize_json(item, depth=depth + 1)
        return result
    raise OpenAISDKError("invalid_response")


def _map_sdk_error(error: Exception) -> OpenAISDKError:
    if isinstance(error, OpenAISDKError):
        return OpenAISDKError(error.code)
    if isinstance(error, openai.AuthenticationError):
        return OpenAISDKError("invalid_api_key")
    if isinstance(error, openai.PermissionDeniedError):
        return OpenAISDKError("permission_denied")
    if isinstance(error, openai.APITimeoutError):
        return OpenAISDKError("request_timeout")
    if isinstance(error, openai.APIConnectionError):
        return OpenAISDKError("network_unavailable")
    if isinstance(error, openai.RateLimitError):
        return OpenAISDKError("rate_limited")
    if isinstance(error, openai.NotFoundError):
        return OpenAISDKError("model_not_found")
    if isinstance(
        error,
        (openai.BadRequestError, openai.UnprocessableEntityError),
    ):
        return OpenAISDKError("invalid_request")
    if isinstance(error, openai.APIStatusError):
        if error.status_code == 401:
            return OpenAISDKError("invalid_api_key")
        if error.status_code == 403:
            return OpenAISDKError("permission_denied")
        if error.status_code == 404:
            return OpenAISDKError("model_not_found")
        if error.status_code == 408:
            return OpenAISDKError("request_timeout")
        if error.status_code == 429:
            return OpenAISDKError("rate_limited")
        if error.status_code >= 500:
            return OpenAISDKError("provider_unavailable")
        return OpenAISDKError("invalid_request")
    return OpenAISDKError("provider_unavailable")
