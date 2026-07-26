import asyncio
import logging
import traceback
from typing import NoReturn, cast

import httpx
import openai
import pytest
from openai import AsyncOpenAI, AsyncStream
from openai.types.responses.response import IncompleteDetails, Response
from openai.types.responses.response_incomplete_event import (
    ResponseIncompleteEvent,
)
from openai.types.responses.response_stream_event import ResponseStreamEvent

import sjtuclaw.infrastructure.llm.openai_sdk as openai_sdk
from sjtuclaw.infrastructure.llm.openai_sdk import (
    OfficialOpenAIClientFactory,
    OfficialOpenAIResponsesClient,
    OfficialOpenAIResponseStream,
    OpenAIRequest,
    OpenAIResponseStream,
    OpenAISDKError,
    _map_sdk_error,
)

_FAKE_API_KEY = "sk-test-never-use-this-value"


def test_openai_sdk_version_is_pinned() -> None:
    assert openai.__version__ == "2.48.0"


def _status_error(
    error_type: type[openai.APIStatusError],
    status_code: int,
) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    return error_type(
        f"Authorization Bearer {_FAKE_API_KEY}",
        response=response,
        body={"sensitive": _FAKE_API_KEY},
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_status_error(openai.AuthenticationError, 401), "invalid_api_key"),
        (
            _status_error(openai.PermissionDeniedError, 403),
            "permission_denied",
        ),
        (
            openai.APITimeoutError(
                httpx.Request("POST", "https://api.openai.com/v1/responses")
            ),
            "request_timeout",
        ),
        (_status_error(openai.APIStatusError, 408), "request_timeout"),
        (
            openai.APIConnectionError(
                message=f"network {_FAKE_API_KEY}",
                request=httpx.Request(
                    "POST",
                    "https://api.openai.com/v1/responses",
                ),
            ),
            "network_unavailable",
        ),
        (_status_error(openai.RateLimitError, 429), "rate_limited"),
        (_status_error(openai.NotFoundError, 404), "model_not_found"),
        (_status_error(openai.BadRequestError, 400), "invalid_request"),
        (
            _status_error(openai.InternalServerError, 500),
            "provider_unavailable",
        ),
    ],
)
def test_official_sdk_errors_map_by_stable_type_or_status(
    error: Exception,
    code: str,
) -> None:
    safe = _map_sdk_error(error)

    assert safe.code == code
    assert _FAKE_API_KEY not in str(safe)
    assert _FAKE_API_KEY not in repr(safe)
    assert safe.__cause__ is None
    assert safe.__context__ is None


class _FailingResponses:
    async def create(self, **kwargs: object) -> NoReturn:
        del kwargs
        raise openai.APIConnectionError(
            message=f"request headers and body {_FAKE_API_KEY}",
            request=httpx.Request(
                "POST",
                "https://api.openai.com/v1/responses",
            ),
        )


class _FailingAsyncOpenAI:
    def __init__(self) -> None:
        self.responses = _FailingResponses()

    async def close(self) -> None:
        return


def test_official_adapter_removes_raw_sdk_exception_chain() -> None:
    async def scenario() -> OpenAISDKError:
        client = OfficialOpenAIResponsesClient(
            cast(AsyncOpenAI, _FailingAsyncOpenAI())
        )
        request = OpenAIRequest(
            model="gpt-5-mini",
            instructions="safe",
            input=({"role": "user", "content": "hello"},),
            tools=(),
            max_output_tokens=10,
            stream=True,
            store=False,
        )
        try:
            await client.create(request)
        except OpenAISDKError as error:
            return error
        raise AssertionError("adapter did not raise a safe SDK error")

    error = asyncio.run(scenario())
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )

    assert error.code == "network_unavailable"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert _FAKE_API_KEY not in str(error)
    assert _FAKE_API_KEY not in repr(error)
    assert _FAKE_API_KEY not in rendered


def test_sdk_request_repr_redacts_input_and_tool_arguments() -> None:
    request = OpenAIRequest(
        model="gpt-5-mini",
        instructions="safe",
        input=({"role": "user", "content": _FAKE_API_KEY},),
        tools=(
            {
                "type": "function",
                "name": "secret_tool",
                "parameters": {
                    "type": "object",
                    "example": _FAKE_API_KEY,
                },
            },
        ),
        max_output_tokens=10,
        stream=True,
        store=False,
    )

    assert _FAKE_API_KEY not in repr(request)
    assert "input=<redacted>" in repr(request)
    assert "tools=<redacted>" in repr(request)


class _FailOnceClose:
    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1
        if self.close_count == 1:
            raise RuntimeError(f"close body {_FAKE_API_KEY}")


class _CloseOnlyAsyncOpenAI(_FailOnceClose):
    def __init__(self) -> None:
        super().__init__()
        self.responses = _FailingResponses()


def _assert_safe_close_failure(error: OpenAISDKError) -> None:
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert error.code == "resource_close_failed"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert _FAKE_API_KEY not in str(error)
    assert _FAKE_API_KEY not in repr(error)
    assert _FAKE_API_KEY not in rendered


def test_official_client_close_failure_is_safe_and_retryable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> tuple[OpenAISDKError, int]:
        delegate = _CloseOnlyAsyncOpenAI()
        client = OfficialOpenAIResponsesClient(
            cast(AsyncOpenAI, delegate)
        )
        safe_error: OpenAISDKError | None = None
        try:
            await client.close()
        except OpenAISDKError as caught:
            safe_error = caught
            logging.getLogger("sjtuclaw.test").exception(
                "safe close failure"
            )
        else:
            raise AssertionError("close failure was not reported safely")
        await client.close()
        await client.close()
        return safe_error, delegate.close_count

    with caplog.at_level(logging.ERROR):
        error, close_count = asyncio.run(scenario())

    _assert_safe_close_failure(error)
    assert close_count == 2
    assert _FAKE_API_KEY not in caplog.text


def test_official_stream_close_failure_is_safe_and_retryable() -> None:
    async def scenario() -> tuple[OpenAISDKError, int]:
        delegate = _FailOnceClose()
        stream = OfficialOpenAIResponseStream(
            cast(AsyncStream[ResponseStreamEvent], delegate)
        )
        with pytest.raises(OpenAISDKError) as captured:
            await stream.close()
        await stream.close()
        await stream.close()
        return captured.value, delegate.close_count

    error, close_count = asyncio.run(scenario())

    _assert_safe_close_failure(error)
    assert close_count == 2


class _CapturingResponses:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None
        self.stream = _FailOnceClose()

    async def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return self.stream


class _CapturingAsyncOpenAI:
    def __init__(self) -> None:
        self.responses = _CapturingResponses()

    async def close(self) -> None:
        return


def test_official_adapter_passes_exact_streaming_request_kwargs() -> None:
    async def scenario() -> tuple[
        dict[str, object],
        OpenAIResponseStream,
    ]:
        delegate = _CapturingAsyncOpenAI()
        client = OfficialOpenAIResponsesClient(
            cast(AsyncOpenAI, delegate)
        )
        request = OpenAIRequest(
            model="gpt-5-mini",
            instructions="safe instructions",
            input=({"role": "user", "content": "hello"},),
            tools=(
                {
                    "type": "function",
                    "name": "safe_tool",
                    "parameters": {"type": "object"},
                },
            ),
            max_output_tokens=23,
            stream=True,
            store=False,
        )
        stream = await client.create(request)
        assert delegate.responses.kwargs is not None
        return delegate.responses.kwargs, stream

    kwargs, stream = asyncio.run(scenario())

    assert isinstance(stream, OfficialOpenAIResponseStream)
    assert kwargs == {
        "model": "gpt-5-mini",
        "instructions": "safe instructions",
        "input": [{"role": "user", "content": "hello"}],
        "tools": [
            {
                "type": "function",
                "name": "safe_tool",
                "parameters": {"type": "object"},
            }
        ],
        "max_output_tokens": 23,
        "store": False,
        "stream": True,
    }
    assert "previous_response_id" not in kwargs
    assert "reasoning" not in kwargs
    assert kwargs["store"] is False
    assert kwargs["stream"] is True


def _incomplete_response(reason: str) -> Response:
    return Response.model_construct(
        status="incomplete",
        incomplete_details=IncompleteDetails.model_construct(reason=reason),
        output=[],
    )


def test_streaming_incomplete_max_tokens_has_controlled_failure_code() -> None:
    event = ResponseIncompleteEvent.model_construct(
        response=_incomplete_response("max_output_tokens"),
        sequence_number=1,
        type="response.incomplete",
    )

    normalized = openai_sdk._normalize_stream_event(event)

    assert normalized.kind is openai_sdk.OpenAIResponseEventKind.FAILED
    assert normalized.raw_type == "response.incomplete"
    assert normalized.failure_code == "output_budget_exhausted"


def test_buffered_incomplete_max_tokens_has_controlled_failure_code() -> None:
    normalized = openai_sdk._normalize_response(
        _incomplete_response("max_output_tokens")
    )

    assert len(normalized) == 1
    assert normalized[0].kind is openai_sdk.OpenAIResponseEventKind.FAILED
    assert normalized[0].failure_code == "output_budget_exhausted"


def test_other_incomplete_reason_is_not_copied_to_public_event() -> None:
    event = ResponseIncompleteEvent.model_construct(
        response=_incomplete_response("future-sensitive-reason"),
        sequence_number=1,
        type="response.incomplete",
    )

    normalized = openai_sdk._normalize_stream_event(event)

    assert normalized.kind is openai_sdk.OpenAIResponseEventKind.FAILED
    assert normalized.failure_code is None
    assert "future-sensitive-reason" not in repr(normalized)


def test_official_factory_passes_zero_retries_to_async_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    delegate = _CapturingAsyncOpenAI()

    def fake_async_openai(**kwargs: object) -> _CapturingAsyncOpenAI:
        captured.update(kwargs)
        return delegate

    monkeypatch.setattr(openai_sdk, "AsyncOpenAI", fake_async_openai)

    client = OfficialOpenAIClientFactory().create(
        api_key=_FAKE_API_KEY,
        timeout_seconds=15.0,
        max_retries=0,
    )

    assert isinstance(client, OfficialOpenAIResponsesClient)
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 15.0
