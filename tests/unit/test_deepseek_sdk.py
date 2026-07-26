from __future__ import annotations

import asyncio
import logging
import traceback
from typing import cast

import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk

import sjtuclaw.infrastructure.llm.deepseek_sdk as deepseek_sdk
from sjtuclaw.config.provider_profiles import DEEPSEEK_OFFICIAL_BASE_URL
from sjtuclaw.infrastructure.llm.deepseek_sdk import (
    DeepSeekEventKind,
    DeepSeekRequest,
    OfficialDeepSeekClient,
    OfficialDeepSeekClientFactory,
    ThinkingMode,
    _map_sdk_error,
    _normalize_chunk,
    _terminal_event,
)

_REASONING_SECRET = "reasoning-content-must-not-escape"


def _chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    finish_reason: str | None = None,
    choices: bool = True,
) -> ChatCompletionChunk:
    choice_data: list[dict[str, object]] = []
    if choices:
        choice_data.append(
            {
                "index": 0,
                "delta": {
                    "content": content,
                    "reasoning_content": reasoning_content,
                    "role": "assistant",
                },
                "finish_reason": finish_reason,
                "logprobs": None,
            }
        )
    return ChatCompletionChunk.model_validate(
        {
            "id": "safe-id",
            "choices": choice_data,
            "created": 0,
            "model": "deepseek-v4-flash",
            "object": "chat.completion.chunk",
            "usage": None,
        }
    )


def test_normalize_text_empty_and_usage_only_chunks() -> None:
    text = _normalize_chunk(_chunk(content="hello"))
    empty = _normalize_chunk(_chunk(content=""))
    usage_only = _normalize_chunk(_chunk(choices=False))

    assert text[0].kind is DeepSeekEventKind.TEXT_DELTA
    assert text[0].text == "hello"
    assert empty[0].kind is DeepSeekEventKind.METADATA
    assert usage_only[0].kind is DeepSeekEventKind.METADATA


def test_reasoning_content_is_discarded_at_sdk_boundary() -> None:
    events = _normalize_chunk(
        _chunk(
            reasoning_content=_REASONING_SECRET,
            content=None,
        )
    )

    assert events == (
        deepseek_sdk.DeepSeekEvent(
            kind=DeepSeekEventKind.METADATA,
        ),
    )
    assert _REASONING_SECRET not in repr(events)


def test_content_and_stop_in_same_chunk_preserve_order() -> None:
    events = _normalize_chunk(
        _chunk(content="done", finish_reason="stop")
    )

    assert [event.kind for event in events] == [
        DeepSeekEventKind.TEXT_DELTA,
        DeepSeekEventKind.COMPLETED,
    ]


def test_all_documented_finish_reasons_have_fixed_mapping() -> None:
    expected = {
        "stop": (DeepSeekEventKind.COMPLETED, None),
        "length": (
            DeepSeekEventKind.FAILED,
            "output_budget_exhausted",
        ),
        "content_filter": (
            DeepSeekEventKind.FAILED,
            "content_filtered",
        ),
        "tool_calls": (
            DeepSeekEventKind.FAILED,
            "unsupported_capability",
        ),
        "insufficient_system_resource": (
            DeepSeekEventKind.FAILED,
            "provider_unavailable",
        ),
        "future_reason": (
            DeepSeekEventKind.FAILED,
            "invalid_response",
        ),
    }

    for finish_reason, result in expected.items():
        event = _terminal_event(finish_reason)
        assert (event.kind, event.failure_code) == result


class _FakeAsyncOpenAI:
    def __init__(self) -> None:
        self.chat = object()


def test_official_factory_uses_only_fixed_deepseek_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_async_openai(**kwargs: object) -> _FakeAsyncOpenAI:
        captured.update(kwargs)
        return _FakeAsyncOpenAI()

    monkeypatch.setattr(
        deepseek_sdk,
        "AsyncOpenAI",
        fake_async_openai,
    )
    factory = OfficialDeepSeekClientFactory()
    factory.create(
        api_key="sk-deepseek-fake-never-use",
        timeout_seconds=30.0,
        max_retries=0,
    )

    assert captured["base_url"] == DEEPSEEK_OFFICIAL_BASE_URL
    assert captured["timeout"] == 30.0
    assert captured["max_retries"] == 0


def test_unknown_sdk_error_does_not_expose_authorization_or_reasoning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive = (
        "Authorization sk-deepseek-test-never-use "
        f"{_REASONING_SECRET}"
    )
    safe_error = _map_sdk_error(RuntimeError(sensitive))

    try:
        raise safe_error from None
    except deepseek_sdk.DeepSeekSDKError as error:
        rendered = "".join(traceback.format_exception(error))
        with caplog.at_level(logging.ERROR):
            logging.getLogger("test.deepseek-sdk").exception(
                "DeepSeek SDK operation failed safely."
            )

    visible = rendered + caplog.text + repr(safe_error)
    assert sensitive not in visible
    assert "sk-deepseek-test-never-use" not in visible
    assert _REASONING_SECRET not in visible
    assert safe_error.__cause__ is None
    assert safe_error.__context__ is None


class _RawStream:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _CapturingCompletions:
    def __init__(self, captured: dict[str, object]) -> None:
        self._captured = captured
        self.stream = _RawStream()

    async def create(self, **kwargs: object) -> object:
        self._captured.update(kwargs)
        return self.stream


class _CapturingChat:
    def __init__(self, captured: dict[str, object]) -> None:
        self.completions = _CapturingCompletions(captured)


class _CapturingAsyncOpenAI:
    def __init__(self, captured: dict[str, object]) -> None:
        self.chat = _CapturingChat(captured)


def test_actual_chat_completions_kwargs_disable_thinking() -> None:
    async def scenario() -> dict[str, object]:
        captured: dict[str, object] = {}
        raw_client = _CapturingAsyncOpenAI(captured)
        client = OfficialDeepSeekClient(
            cast(AsyncOpenAI, raw_client)
        )
        stream = await client.create(
            DeepSeekRequest(
                model="deepseek-v4-flash",
                messages=(
                    {"role": "user", "content": "offline test"},
                ),
                max_tokens=128,
                thinking_mode=ThinkingMode.DISABLED,
            )
        )
        await stream.close()
        return captured

    captured = asyncio.run(scenario())

    assert captured["stream"] is True
    assert captured["max_tokens"] == 128
    assert captured["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert "reasoning_effort" not in captured


def test_deepseek_request_rejects_any_non_disabled_thinking_mode() -> None:
    with pytest.raises(ValueError, match="thinking_mode"):
        DeepSeekRequest(
            model="deepseek-v4-flash",
            messages=(
                {"role": "user", "content": "offline test"},
            ),
            max_tokens=128,
            thinking_mode=cast(ThinkingMode, "enabled"),
        )
