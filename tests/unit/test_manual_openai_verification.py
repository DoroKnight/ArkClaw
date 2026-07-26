from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from collections.abc import Callable
from typing import cast

import pytest
import scripts.manual_openai_verification as manual
from tests.fakes.openai_sdk import (
    FakeOpenAIClientFactory,
    FakeOpenAIResponsesClient,
    FakeOpenAIResponseStream,
    FakeOpenAIScenario,
)

from sjtuclaw.config.secrets import SecretValue
from sjtuclaw.domain.models import (
    OPENAI_DEFAULT_CREDENTIAL_ID,
    CredentialId,
)
from sjtuclaw.infrastructure.llm.openai_provider import OpenAIProvider
from sjtuclaw.infrastructure.llm.openai_sdk import (
    JSONObject,
    OpenAIClientFactory,
    OpenAIRequest,
    OpenAIResponseEvent,
    OpenAIResponseEventKind,
    OpenAIResponsesClient,
    OpenAIResponseStream,
    OpenAISDKError,
)

_FAKE_API_KEY = "sk-test-valid-never-use-this-value"
_ASSISTANT_BODY = "assistant-body-must-not-be-printed"
_CONTINUATION_BODY = "continuation-body-must-not-be-printed"
_REASONING_BODY = "reasoning-body-must-not-be-printed"


class _RecordingStore:
    def __init__(
        self,
        initial: str | None = None,
        *,
        fail_write: bool = False,
        fail_delete: bool = False,
        retain_on_delete: bool = False,
    ) -> None:
        self.value = initial
        self.fail_write = fail_write
        self.fail_delete = fail_delete
        self.retain_on_delete = retain_on_delete
        self.read_count = 0
        self.write_count = 0
        self.delete_count = 0

    def has_openai_api_key(self) -> bool:
        return self.value is not None

    def has_secret(self, credential_id: CredentialId) -> bool:
        return (
            credential_id == OPENAI_DEFAULT_CREDENTIAL_ID
            and self.has_openai_api_key()
        )

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        if credential_id != OPENAI_DEFAULT_CREDENTIAL_ID:
            return None
        return self.get_openai_api_key()

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        if credential_id != OPENAI_DEFAULT_CREDENTIAL_ID:
            raise ValueError("unsupported credential identifier")
        self.set_openai_api_key(value)

    def delete_secret(self, credential_id: CredentialId) -> None:
        if credential_id == OPENAI_DEFAULT_CREDENTIAL_ID:
            self.delete_openai_api_key()

    def get_openai_api_key(self) -> SecretValue | None:
        self.read_count += 1
        return SecretValue(self.value) if self.value is not None else None

    def set_openai_api_key(self, value: SecretValue) -> None:
        self.write_count += 1
        if self.fail_write:
            raise RuntimeError(f"write failed {_FAKE_API_KEY}")
        self.value = value.reveal()

    def delete_openai_api_key(self) -> None:
        self.delete_count += 1
        if self.fail_delete:
            raise RuntimeError(f"delete failed {_FAKE_API_KEY}")
        if not self.retain_on_delete:
            self.value = None


class _StoreFactory:
    def __init__(self, store: _RecordingStore) -> None:
        self.store = store
        self.calls = 0

    def __call__(self) -> _RecordingStore:
        self.calls += 1
        return self.store


class _Prompt:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        del prompt
        self.calls += 1
        return self.value


class _ClientCloseFailure:
    def __init__(self, delegate: OpenAIResponsesClient) -> None:
        self._delegate = delegate

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        return await self._delegate.create(request)

    async def close(self) -> None:
        raise RuntimeError(f"client close {_FAKE_API_KEY}")


class _ClientCloseFailureFactory:
    def __init__(self, delegate: FakeOpenAIClientFactory) -> None:
        self._delegate = delegate

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> OpenAIResponsesClient:
        return _ClientCloseFailure(
            self._delegate.create(
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )


class _StreamCloseFailure:
    def __init__(self, delegate: OpenAIResponseStream) -> None:
        self._delegate = delegate

    def __aiter__(self) -> _StreamCloseFailure:
        return self

    async def __anext__(self) -> OpenAIResponseEvent:
        return await self._delegate.__anext__()

    async def close(self) -> None:
        raise RuntimeError(f"stream close {_FAKE_API_KEY}")


class _StreamCloseFailureClient:
    def __init__(self, delegate: OpenAIResponsesClient) -> None:
        self._delegate = delegate

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        return _StreamCloseFailure(await self._delegate.create(request))

    async def close(self) -> None:
        await self._delegate.close()


class _StreamCloseFailureFactory:
    def __init__(self, delegate: FakeOpenAIClientFactory) -> None:
        self._delegate = delegate

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> OpenAIResponsesClient:
        return _StreamCloseFailureClient(
            self._delegate.create(
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )


class _FailOnceStreamClose:
    def __init__(self, delegate: OpenAIResponseStream) -> None:
        self._delegate = delegate
        self.close_count = 0

    def __aiter__(self) -> _FailOnceStreamClose:
        return self

    async def __anext__(self) -> OpenAIResponseEvent:
        return await self._delegate.__anext__()

    async def close(self) -> None:
        self.close_count += 1
        if self.close_count == 1:
            raise RuntimeError(f"stream close {_FAKE_API_KEY}")
        await self._delegate.close()


class _FailOnceStreamCloseClient:
    def __init__(self, delegate: OpenAIResponsesClient) -> None:
        self._delegate = delegate

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        return _FailOnceStreamClose(
            await self._delegate.create(request)
        )

    async def close(self) -> None:
        await self._delegate.close()


class _FailOnceStreamCloseFactory:
    def __init__(self, delegate: FakeOpenAIClientFactory) -> None:
        self._delegate = delegate

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> OpenAIResponsesClient:
        return _FailOnceStreamCloseClient(
            self._delegate.create(
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )


class _ReplacingStore(_RecordingStore):
    def __init__(self, *, replace_on_read: int) -> None:
        super().__init__()
        self._replace_on_read = replace_on_read

    def get_openai_api_key(self) -> SecretValue | None:
        value = super().get_openai_api_key()
        if self.read_count == self._replace_on_read:
            self.value = "sk-test-external-owner"
            return SecretValue(self.value)
        return value


def _created() -> OpenAIResponseEvent:
    return OpenAIResponseEvent(
        kind=OpenAIResponseEventKind.METADATA,
        raw_type="response.created",
    )


def _text(value: str = _ASSISTANT_BODY) -> OpenAIResponseEvent:
    return OpenAIResponseEvent(
        kind=OpenAIResponseEventKind.TEXT_DELTA,
        raw_type="response.output_text.delta",
        text=value,
    )


def _message_output(index: int) -> JSONObject:
    return {
        "id": f"msg_{index}",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [
            {
                "type": "output_text",
                "text": _CONTINUATION_BODY,
                "annotations": [],
            }
        ],
    }


def _completed(
    index: int,
    output_items: tuple[JSONObject, ...] | None = None,
) -> OpenAIResponseEvent:
    output = _message_output(index)
    return OpenAIResponseEvent(
        kind=OpenAIResponseEventKind.COMPLETED,
        raw_type="response.completed",
        output_items=output_items or (output,),
    )


def _output_budget_exhausted() -> OpenAIResponseEvent:
    return OpenAIResponseEvent(
        kind=OpenAIResponseEventKind.FAILED,
        raw_type="response.incomplete",
        failure_code="output_budget_exhausted",
    )


def _reasoning_metadata() -> OpenAIResponseEvent:
    return OpenAIResponseEvent(
        kind=OpenAIResponseEventKind.METADATA,
        raw_type="response.reasoning_text.delta",
        text=_REASONING_BODY,
    )


def _success_events(index: int) -> tuple[OpenAIResponseEvent, ...]:
    return (_created(), _text(), _completed(index))


def _full_factory(
    *,
    first_output_items: tuple[JSONObject, ...] | None = None,
) -> FakeOpenAIClientFactory:
    create_gate = asyncio.Event()
    return FakeOpenAIClientFactory(
        (
            FakeOpenAIScenario(
                events=(
                    _created(),
                    _text(),
                    _completed(1, first_output_items),
                )
            ),
            FakeOpenAIScenario(events=_success_events(2)),
            FakeOpenAIScenario(events=_success_events(3)),
            FakeOpenAIScenario(events=_success_events(4)),
            FakeOpenAIScenario(
                events=_success_events(5),
                create_gate=create_gate,
                allocate_before_create_gate=True,
            ),
            FakeOpenAIScenario(
                create_error=OpenAISDKError("invalid_api_key")
            ),
            FakeOpenAIScenario(events=_success_events(7)),
        )
    )


def _dependencies(
    *,
    store_factory: Callable[[], _RecordingStore],
    client_factory: OpenAIClientFactory,
    input_value: str = "RUN",
    secret_value: str = _FAKE_API_KEY,
    sdk_version: str = "2.48.0",
    platform: str = "win32",
    output: Callable[[str], None],
) -> tuple[
    manual.ManualVerificationDependencies,
    _Prompt,
    _Prompt,
]:
    input_prompt = _Prompt(input_value)
    secret_prompt = _Prompt(secret_value)
    return (
        manual.ManualVerificationDependencies(
            platform=platform,
            sdk_version=sdk_version,
            store_factory=store_factory,
            client_factory=client_factory,
            input_text=input_prompt,
            get_secret=secret_prompt,
            output=output,
        ),
        input_prompt,
        secret_prompt,
    )


def _sdk_request() -> OpenAIRequest:
    return OpenAIRequest(
        model="gpt-5-mini",
        instructions="safe",
        input=({"role": "user", "content": "test"},),
        tools=(),
        max_output_tokens=16,
        stream=True,
        store=False,
    )


def _observed(
    *events: tuple[str, bool],
) -> tuple[manual._ObservedRawEvent, ...]:
    return tuple(
        manual._ObservedRawEvent(
            raw_type=raw_type,
            has_nonempty_text=has_nonempty_text,
        )
        for raw_type, has_nonempty_text in events
    )


def test_sse_lifecycle_accepts_only_ordered_complete_sequence() -> None:
    events = _observed(
        ("response.created", False),
        ("response.output_text.delta", True),
        ("response.output_text.delta", True),
        ("response.completed", False),
    )

    assert manual._sse_lifecycle_is_valid(events)


@pytest.mark.parametrize(
    "events",
    [
        _observed(
            ("response.output_text.delta", True),
            ("response.created", False),
            ("response.completed", False),
        ),
        _observed(
            ("response.created", False),
            ("response.created", False),
            ("response.output_text.delta", True),
            ("response.completed", False),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", True),
            ("response.completed", False),
            ("response.completed", False),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", True),
            ("response.completed", False),
            ("response.output_text.delta", True),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", False),
            ("response.completed", False),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", True),
            ("response.failed", False),
        ),
        _observed(
            ("response.output_text.delta", True),
            ("response.completed", False),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", True),
            ("response.incomplete", False),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", True),
            ("response.cancelled", False),
        ),
        _observed(
            ("response.created", False),
            ("response.output_text.delta", True),
            ("error", False),
            ("response.completed", False),
        ),
    ],
    ids=[
        "out-of-order",
        "duplicate-created",
        "duplicate-completed",
        "output-after-completed",
        "missing-nonempty-delta",
        "missing-completed",
        "missing-created",
        "incomplete-event",
        "cancelled-event",
        "error-event",
    ],
)
def test_sse_lifecycle_rejects_illegal_sequences(
    events: tuple[manual._ObservedRawEvent, ...],
) -> None:
    assert not manual._sse_lifecycle_is_valid(events)


def _continuation_outputs() -> tuple[JSONObject, ...]:
    reasoning: JSONObject = {
        "id": "rs_1",
        "type": "reasoning",
        "status": "completed",
        "summary": [
            {"type": "summary_text", "text": "safe summary"}
        ],
        "content": [
            {"type": "reasoning_text", "text": "safe reasoning"}
        ],
        "encrypted_content": "encrypted-test-payload",
    }
    function_call: JSONObject = {
        "id": "fc_1",
        "type": "function_call",
        "call_id": "call_1",
        "name": "safe_tool",
        "arguments": "{}",
        "status": "completed",
    }
    return reasoning, _message_output(1), function_call


def test_continuation_replay_accepts_message_only_output() -> None:
    first_input: tuple[JSONObject, ...] = (
        {"role": "user", "content": "first"},
    )
    output_items = (_message_output(1),)
    second_input = first_input + output_items + (
        {"role": "user", "content": "One more word."},
    )

    assert manual._continuation_replay_is_exact(
        first_input,
        output_items,
        second_input,
    )


def test_continuation_replay_accepts_reasoning_encrypted_and_function_call(
) -> None:
    first_input: tuple[JSONObject, ...] = (
        {"role": "user", "content": "first"},
    )
    output_items = _continuation_outputs()
    second_input = first_input + output_items + (
        {"role": "user", "content": "One more word."},
    )

    assert manual._continuation_replay_is_exact(
        first_input,
        output_items,
        second_input,
    )


@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate"])
def test_continuation_replay_rejects_inexact_output_items(
    mutation: str,
) -> None:
    first_input: tuple[JSONObject, ...] = (
        {"role": "user", "content": "first"},
    )
    output_items = _continuation_outputs()
    if mutation == "missing":
        replayed = output_items[:-1]
    elif mutation == "reordered":
        replayed = (
            output_items[1],
            output_items[0],
            output_items[2],
        )
    else:
        replayed = (*output_items, output_items[1])
    second_input = first_input + replayed + (
        {"role": "user", "content": "One more word."},
    )

    assert not manual._continuation_replay_is_exact(
        first_input,
        output_items,
        second_input,
    )


def test_default_mode_is_fully_inert() -> None:
    output: list[str] = []
    store = _RecordingStore()
    store_factory = _StoreFactory(store)
    fake_sdk = FakeOpenAIClientFactory()
    dependencies, input_prompt, secret_prompt = _dependencies(
        store_factory=store_factory,
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main([], dependencies=dependencies)

    assert result == 0
    assert output == ["safe_code=manual_verification_disabled"]
    assert store_factory.calls == 0
    assert input_prompt.calls == 0
    assert secret_prompt.calls == 0
    assert fake_sdk.create_count == 0
    assert fake_sdk.network_request_count == 0


def test_manual_request_uses_fixed_documented_output_budget() -> None:
    request = manual._request("safe")

    assert manual._MANUAL_MAX_OUTPUT_TOKENS == 25_000
    assert request.max_output_tokens == manual._MANUAL_MAX_OUTPUT_TOKENS
    assert request.max_output_tokens != 16
    assert request.store is False


def test_missing_exact_confirmation_does_not_access_store_or_getpass() -> None:
    output: list[str] = []
    store_factory = _StoreFactory(_RecordingStore())
    fake_sdk = FakeOpenAIClientFactory()
    dependencies, input_prompt, secret_prompt = _dependencies(
        store_factory=store_factory,
        client_factory=fake_sdk,
        input_value="run",
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert input_prompt.calls == 1
    assert secret_prompt.calls == 0
    assert store_factory.calls == 0
    assert fake_sdk.create_count == 0
    assert output[-1] == "safe_code=not_confirmed"


def test_sdk_version_mismatch_does_not_access_store() -> None:
    output: list[str] = []
    store_factory = _StoreFactory(_RecordingStore())
    dependencies, input_prompt, secret_prompt = _dependencies(
        store_factory=store_factory,
        client_factory=FakeOpenAIClientFactory(),
        sdk_version="2.49.0",
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store_factory.calls == 0
    assert input_prompt.calls == 0
    assert secret_prompt.calls == 0
    assert output[-1].endswith("safe_code=sdk_version_mismatch")


def test_occupied_target_is_not_revealed_overwritten_or_deleted() -> None:
    output: list[str] = []
    occupied = "sk-test-existing-do-not-touch"
    store = _RecordingStore(occupied)
    store_factory = _StoreFactory(store)
    fake_sdk = FakeOpenAIClientFactory()
    dependencies, _, secret_prompt = _dependencies(
        store_factory=store_factory,
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert output[-1] == "safe_code=test_target_occupied"
    assert store.value == occupied
    assert store.read_count == 1
    assert store.write_count == 0
    assert store.delete_count == 0
    assert secret_prompt.calls == 0
    assert fake_sdk.create_count == 0


def test_blank_key_fails_without_write_delete_or_client() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory()
    dependencies, _, secret_prompt = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        secret_value="   ",
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert secret_prompt.calls == 1
    assert store.write_count == 0
    assert store.delete_count == 0
    assert fake_sdk.create_count == 0
    assert output[-1] == "safe_code=empty_key"


def test_secret_input_failure_does_not_write_or_delete() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory()

    def fail_secret_input(prompt: str) -> str:
        del prompt
        raise RuntimeError(f"input failed {_FAKE_API_KEY}")

    dependencies = manual.ManualVerificationDependencies(
        platform="win32",
        sdk_version="2.48.0",
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        input_text=_Prompt("RUN"),
        get_secret=fail_secret_input,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.write_count == 0
    assert store.delete_count == 0
    assert fake_sdk.create_count == 0
    assert _FAKE_API_KEY not in "".join(output)
    assert output[-1] == "safe_code=secret_input_failed"


def test_target_occupied_during_secret_entry_is_not_overwritten() -> None:
    output: list[str] = []
    store = _RecordingStore()
    store_factory = _StoreFactory(store)
    fake_sdk = FakeOpenAIClientFactory()

    def occupy_target(prompt: str) -> str:
        del prompt
        store.value = "sk-test-concurrent-owner"
        return _FAKE_API_KEY

    dependencies = manual.ManualVerificationDependencies(
        platform="win32",
        sdk_version="2.48.0",
        store_factory=store_factory,
        client_factory=fake_sdk,
        input_text=_Prompt("RUN"),
        get_secret=occupy_target,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value == "sk-test-concurrent-owner"
    assert store.write_count == 0
    assert store.delete_count == 0
    assert fake_sdk.create_count == 0
    assert output[-1] == "safe_code=test_target_occupied"


def test_write_failure_does_not_delete_without_ownership() -> None:
    output: list[str] = []
    store = _RecordingStore(fail_write=True)
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=FakeOpenAIClientFactory(),
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.write_count == 1
    assert store.delete_count == 0
    assert output[-1].endswith("safe_code=manual_verification_failed")


def test_success_path_owns_then_deletes_only_its_credential() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = _full_factory()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 0
    assert store.value is None
    assert store.write_count == 3
    assert store.delete_count == 1
    assert fake_sdk.create_count == 3
    assert fake_sdk.network_request_count == 0
    assert all(max_retries == 0 for _, max_retries in fake_sdk.settings)
    assert all(
        timeout == manual._MANUAL_REQUEST_TIMEOUT_SECONDS
        for timeout, _ in fake_sdk.settings
    )
    assert {
        request.max_output_tokens
        for client in fake_sdk.clients
        for request in client.requests
    } == {manual._MANUAL_MAX_OUTPUT_TOKENS}
    assert all(
        request.store is False
        for client in fake_sdk.clients
        for request in client.requests
    )
    assert output[-1] == "verification_complete=True safe_code=none"


@pytest.mark.parametrize(
    "events",
    [
        (_created(), _output_budget_exhausted()),
        (
            _created(),
            _reasoning_metadata(),
            _text("partial-response-body"),
            _output_budget_exhausted(),
        ),
    ],
    ids=["before-first-delta", "after-partial-delta"],
)
def test_output_budget_exhaustion_stops_after_one_safe_request(
    events: tuple[OpenAIResponseEvent, ...],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (FakeOpenAIScenario(events=events),)
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=print,
    )

    with caplog.at_level(logging.DEBUG):
        result = manual.main(
            ["--confirm-real-api"],
            dependencies=dependencies,
        )

    captured = capsys.readouterr()
    visible = captured.out + captured.err + caplog.text
    assert result == 2
    assert (
        "verification_complete=False "
        "safe_code=verification_output_budget_exhausted"
    ) in captured.out
    assert "request_attempts=1" in captured.out
    assert fake_sdk.clients[0].request_count == 1
    assert fake_sdk.network_request_count == 0
    assert store.value is None
    assert all(client.closed for client in fake_sdk.clients)
    assert all(
        stream.closed
        for client in fake_sdk.clients
        for stream in client.streams
    )
    assert _FAKE_API_KEY not in visible
    assert _ASSISTANT_BODY not in visible
    assert "partial-response-body" not in visible
    assert _REASONING_BODY not in visible
    assert _CONTINUATION_BODY not in visible
    assert "Traceback" not in visible


def test_budget_failure_repr_traceback_and_logging_are_payload_free(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = manual._SafeResult(
        assistant_text=_ASSISTANT_BODY,
        continuation=None,
        event_types=("response.incomplete",),
        delta_char_count=len(_ASSISTANT_BODY),
        completed=False,
        safe_code="output_budget_exhausted",
    )
    checks = manual.ManualVerificationChecks()

    with caplog.at_level(logging.ERROR):
        try:
            manual._raise_for_bounded_failure(result.safe_code, checks)
        except manual._ManualVerificationFailure as error:
            rendered = (
                str(error)
                + repr(error)
                + repr(result)
                + "".join(
                    traceback.format_exception(
                        type(error),
                        error,
                        error.__traceback__,
                    )
                )
            )
            logging.getLogger("sjtuclaw.test").exception(
                "safe budget failure"
            )
        else:
            raise AssertionError("budget failure was not raised")

    visible = rendered + caplog.text
    assert checks.safe_code == "verification_output_budget_exhausted"
    assert _FAKE_API_KEY not in visible
    assert _ASSISTANT_BODY not in visible
    assert _CONTINUATION_BODY not in visible
    assert _REASONING_BODY not in visible


def test_request_timeout_is_distinct_from_output_budget_exhaustion() -> None:
    output: list[str] = []
    fake_sdk = FakeOpenAIClientFactory(
        (
            FakeOpenAIScenario(
                create_error=OpenAISDKError("request_timeout")
            ),
        )
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(_RecordingStore()),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert output[-1].endswith("safe_code=verification_request_timeout")
    assert "output_budget_exhausted" not in output[-1]
    assert fake_sdk.clients[0].request_count == 1


def test_cooperative_timeout_immediately_cancels_runner_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output: list[str] = []
    cancelled = False
    previous_logging_disable = logging.root.manager.disable

    async def never_finishes(
        api_key: str,
        *,
        store: object,
        client_factory: object,
        output: object,
    ) -> manual.ManualVerificationChecks:
        del api_key, store, client_factory, output
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        raise AssertionError("unreachable without cancellation")

    monkeypatch.setattr(manual, "_run_real_verification", never_finishes)
    monkeypatch.setattr(
        manual,
        "_MANUAL_COOPERATIVE_TIMEOUT_SECONDS",
        0.01,
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(_RecordingStore()),
        client_factory=FakeOpenAIClientFactory(),
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert cancelled
    assert logging.root.manager.disable == previous_logging_disable
    assert any(
        "cooperative_timeout_action=cancel_then_wait_for_cleanup" in line
        and "cooperative_timeout_seconds=0.01" in line
        for line in output
    )
    assert output[-1].endswith("safe_code=verification_runtime_timeout")
    assert "output_budget_exhausted" not in output[-1]


def test_main_waits_for_delayed_cancellation_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output: list[str] = []
    cleanup_started = threading.Event()
    allow_cleanup = threading.Event()
    cleanup_finished = threading.Event()
    result: list[int] = []

    async def delayed_cleanup(
        api_key: str,
        *,
        store: object,
        client_factory: object,
        output: object,
    ) -> manual.ManualVerificationChecks:
        del api_key, store, client_factory, output
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            while not allow_cleanup.is_set():
                await asyncio.sleep(0.001)
            cleanup_finished.set()
            raise
        raise AssertionError("unreachable without cancellation")

    monkeypatch.setattr(manual, "_run_real_verification", delayed_cleanup)
    monkeypatch.setattr(
        manual,
        "_MANUAL_COOPERATIVE_TIMEOUT_SECONDS",
        0.01,
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(_RecordingStore()),
        client_factory=FakeOpenAIClientFactory(),
        output=output.append,
    )
    worker = threading.Thread(
        target=lambda: result.append(
            manual.main(
                ["--confirm-real-api"],
                dependencies=dependencies,
            )
        ),
    )

    worker.start()
    cleanup_was_started = cleanup_started.wait(timeout=1.0)
    worker_was_alive_during_cleanup = worker.is_alive()
    cleanup_was_pending = not cleanup_finished.is_set()
    main_had_not_returned = not result
    try:
        assert cleanup_was_started
        assert worker_was_alive_during_cleanup
        assert cleanup_was_pending
        assert main_had_not_returned
    finally:
        allow_cleanup.set()
        worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert cleanup_finished.is_set()
    assert result == [2]
    assert output[-1].endswith("safe_code=verification_runtime_timeout")


def test_external_cancellation_preserves_cancelled_error_and_no_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cleanup_finished = False
        current = asyncio.current_task()
        before = {
            task for task in asyncio.all_tasks() if task is not current
        }

        async def waits_for_cancellation(
            api_key: str,
            *,
            store: object,
            client_factory: object,
            output: object,
        ) -> manual.ManualVerificationChecks:
            del api_key, store, client_factory, output
            nonlocal cleanup_finished
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise
            finally:
                cleanup_finished = True
            raise AssertionError("unreachable without cancellation")

        monkeypatch.setattr(
            manual,
            "_run_real_verification",
            waits_for_cancellation,
        )
        task = asyncio.create_task(
            manual._run_with_cooperative_timeout(
                _FAKE_API_KEY,
                store=_RecordingStore(),
                client_factory=FakeOpenAIClientFactory(),
                output=lambda value: None,
            )
        )
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert cleanup_finished
        assert {
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task()
        } == before

    asyncio.run(scenario())


def test_cooperative_timeout_still_cleans_target_client_and_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        current = asyncio.current_task()
        before = {
            task for task in asyncio.all_tasks() if task is not current
        }
        iteration_started = asyncio.Event()
        iteration_gate = asyncio.Event()
        store = _RecordingStore()
        fake_sdk = FakeOpenAIClientFactory(
            (
                FakeOpenAIScenario(
                    events=_success_events(1),
                    iteration_started=iteration_started,
                    iteration_gate=iteration_gate,
                ),
            )
        )
        output: list[str] = []
        monkeypatch.setattr(
            manual,
            "_MANUAL_COOPERATIVE_TIMEOUT_SECONDS",
            0.05,
        )

        with pytest.raises(TimeoutError):
            await manual._run_with_cooperative_timeout(
                _FAKE_API_KEY,
                store=store,
                client_factory=fake_sdk,
                output=output.append,
            )

        assert iteration_started.is_set()
        assert store.value is None
        assert store.write_count == 1
        assert store.delete_count == 1
        assert fake_sdk.network_request_count == 0
        assert len(fake_sdk.clients) == 1
        assert fake_sdk.clients[0].closed
        assert all(
            stream.closed for stream in fake_sdk.clients[0].streams
        )
        assert {
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task()
        } == before

    asyncio.run(scenario())


def test_fake_sdk_replays_all_first_completion_output_items_exactly() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = _full_factory(
        first_output_items=_continuation_outputs()
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 0
    second_request = fake_sdk.clients[0].requests[1]
    first_request = fake_sdk.clients[0].requests[0]
    assert manual._continuation_replay_is_exact(
        first_request.input,
        _continuation_outputs(),
        second_request.input,
    )
    assert output[-1] == "verification_complete=True safe_code=none"


@pytest.mark.parametrize(
    (
        "replace_on_read",
        "expected_requests",
        "expected_writes",
        "expected_clients",
    ),
    [
        (5, 0, 1, 0),
        (8, 3, 1, 1),
        (10, 5, 1, 1),
        (13, 6, 2, 2),
        (16, 7, 3, 3),
    ],
    ids=[
        "first-provider-read",
        "nth-provider-read",
        "before-invalid-rotation",
        "before-real-key-restore",
        "before-delete",
    ],
)
def test_target_replacement_stops_requests_overwrite_and_delete(
    replace_on_read: int,
    expected_requests: int,
    expected_writes: int,
    expected_clients: int,
) -> None:
    output: list[str] = []
    store = _ReplacingStore(replace_on_read=replace_on_read)
    fake_sdk = _full_factory()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value == "sk-test-external-owner"
    assert store.write_count == expected_writes
    assert store.delete_count == 0
    assert (
        sum(client.request_count for client in fake_sdk.clients)
        == expected_requests
    )
    assert fake_sdk.create_count == expected_clients
    assert all(client.closed for client in fake_sdk.clients)
    assert output[-1] == (
        "verification_complete=False "
        "safe_code=test_target_ownership_lost"
    )
    assert _FAKE_API_KEY not in "".join(output)
    assert "sk-test-external-owner" not in "".join(output)


def test_owned_store_never_returns_replaced_value_to_provider() -> None:
    async def scenario() -> None:
        raw_store = _RecordingStore()
        owned_store = manual.OwnedTestSecretStore(raw_store)
        owned_store.set_openai_api_key(SecretValue(_FAKE_API_KEY))
        raw_store.value = "sk-test-external-owner"
        fake_sdk = FakeOpenAIClientFactory()
        provider = OpenAIProvider(
            secret_store=owned_store,
            model="gpt-5-mini",
            timeout_seconds=1.0,
            max_retries=0,
            stream=True,
            client_factory=fake_sdk,
        )

        events = [
            event
            async for event in provider.generate_stream(manual._request("x"))
        ]
        assert events[-1].error_code == "credential_unavailable"
        assert owned_store.ownership_lost
        assert fake_sdk.create_count == 0
        assert fake_sdk.clients == []
        assert raw_store.value == "sk-test-external-owner"

        await provider.aclose()
        assert raw_store.delete_count == 0

    asyncio.run(scenario())


def test_owned_store_ownership_error_is_fully_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_store = _RecordingStore()
    owned_store = manual.OwnedTestSecretStore(raw_store)
    owned_store.set_openai_api_key(SecretValue(_FAKE_API_KEY))
    external = "sk-test-external-owner-never-log"
    raw_store.value = external
    safe_error: manual._TargetOwnershipLost | None = None

    with caplog.at_level(logging.ERROR):
        try:
            owned_store.get_openai_api_key()
        except manual._TargetOwnershipLost as caught:
            safe_error = caught
            logging.getLogger("sjtuclaw.test").exception(
                "safe ownership failure"
            )

    assert safe_error is not None
    rendered = "".join(
        traceback.format_exception(
            type(safe_error),
            safe_error,
            safe_error.__traceback__,
        )
    )
    visible = (
        str(safe_error)
        + repr(safe_error)
        + repr(owned_store)
        + rendered
        + caplog.text
    )
    assert safe_error.__cause__ is None
    assert safe_error.__context__ is None
    assert external not in visible
    assert _FAKE_API_KEY not in visible


def test_mid_run_failure_deletes_owned_credential() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (
            FakeOpenAIScenario(
                create_error=RuntimeError(
                    f"request failed {_FAKE_API_KEY}"
                )
            ),
        )
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.write_count == 1
    assert store.delete_count == 1
    assert store.value is None


def test_cleanup_failure_forces_nonzero_exit() -> None:
    output: list[str] = []
    store = _RecordingStore(fail_delete=True)
    fake_sdk = _full_factory()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.delete_count == 2
    assert store.value == _FAKE_API_KEY
    assert "target_cleanup=False" in output


def test_request_budget_blocks_eighth_call_before_delegate() -> None:
    async def scenario() -> None:
        fake_sdk = FakeOpenAIClientFactory(
            tuple(FakeOpenAIScenario() for _ in range(7))
        )
        audit = manual._AuditFactory(fake_sdk)
        client = cast(
            manual._AuditClient,
            audit.create(
                api_key=_FAKE_API_KEY,
                timeout_seconds=1.0,
                max_retries=0,
            ),
        )
        for _ in range(7):
            stream = await client.create(_sdk_request())
            await stream.close()

        with pytest.raises(manual._ManualVerificationFailure):
            await client.create(_sdk_request())

        assert audit.request_attempts == 7
        assert audit.request_limit_exceeded
        assert fake_sdk.clients[0].request_count == 7

    asyncio.run(scenario())


def test_store_true_is_rejected_before_delegate() -> None:
    async def scenario() -> None:
        fake_sdk = FakeOpenAIClientFactory((FakeOpenAIScenario(),))
        audit = manual._AuditFactory(fake_sdk)
        client = cast(
            manual._AuditClient,
            audit.create(
                api_key=_FAKE_API_KEY,
                timeout_seconds=1.0,
                max_retries=0,
            ),
        )
        request = _sdk_request()
        object.__setattr__(request, "store", True)

        with pytest.raises(manual._ManualVerificationFailure):
            await client.create(request)

        assert not audit.all_store_false
        assert audit.request_attempts == 0
        assert fake_sdk.clients[0].request_count == 0

    asyncio.run(scenario())


def test_nonzero_sdk_retries_are_rejected_before_factory_delegate() -> None:
    fake_sdk = FakeOpenAIClientFactory()
    audit = manual._AuditFactory(fake_sdk)

    with pytest.raises(manual._ManualVerificationFailure):
        audit.create(
            api_key=_FAKE_API_KEY,
            timeout_seconds=1.0,
            max_retries=1,
        )

    assert not audit.retries_disabled
    assert fake_sdk.create_count == 0


def test_stream_close_failure_forces_nonzero_exit_and_cleanup() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (FakeOpenAIScenario(events=_success_events(1)),)
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=_StreamCloseFailureFactory(fake_sdk),
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value is None
    assert "streams_closed=False" in output


def test_first_close_failure_then_success_still_fails_manual_verification(
) -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (FakeOpenAIScenario(events=_success_events(1)),)
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=_FailOnceStreamCloseFactory(fake_sdk),
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value is None
    assert all(
        stream.closed
        for client in fake_sdk.clients
        for stream in client.streams
    )
    assert "streams_closed=True" in output
    assert output[-1].endswith("safe_code=manual_verification_failed")
    assert _FAKE_API_KEY not in "".join(output)


def test_client_close_failure_or_rotation_failure_forces_nonzero_exit() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = _full_factory()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=_ClientCloseFailureFactory(fake_sdk),
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value is None
    assert "clients_closed=False" in output


def test_provider_reuse_failure_after_cancel_forces_nonzero_exit() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (
            FakeOpenAIScenario(events=_success_events(1)),
            FakeOpenAIScenario(events=_success_events(2)),
            FakeOpenAIScenario(events=_success_events(3)),
            FakeOpenAIScenario(
                create_error=OpenAISDKError("network_unavailable")
            ),
        )
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value is None
    assert output[-1].endswith("safe_code=manual_verification_failed")


def test_non_delta_first_event_cannot_be_reported_as_successful_cancel() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (
            FakeOpenAIScenario(events=_success_events(1)),
            FakeOpenAIScenario(events=_success_events(2)),
            FakeOpenAIScenario(events=(_created(), _completed(3))),
        )
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value is None
    assert any("request_number=3" in line and "cancel=False" in line for line in output)


def test_failed_delete_cannot_trigger_an_unbudgeted_request() -> None:
    output: list[str] = []
    store = _RecordingStore(retain_on_delete=True)
    fake_sdk = _full_factory()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 2
    assert store.value == _FAKE_API_KEY
    assert sum(client.request_count for client in fake_sdk.clients) == 7
    assert fake_sdk.network_request_count == 0
    assert "target_cleanup=False" in output


def test_logging_state_is_restored_after_success_and_failure() -> None:
    previous = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        successful_dependencies, _, _ = _dependencies(
            store_factory=_StoreFactory(_RecordingStore()),
            client_factory=_full_factory(),
            output=lambda value: None,
        )
        assert manual.main(
            ["--confirm-real-api"],
            dependencies=successful_dependencies,
        ) == 0
        assert logging.root.manager.disable == logging.WARNING

        failing_dependencies, _, _ = _dependencies(
            store_factory=_StoreFactory(
                _RecordingStore(fail_write=True)
            ),
            client_factory=FakeOpenAIClientFactory(),
            output=lambda value: None,
        )
        assert manual.main(
            ["--confirm-real-api"],
            dependencies=failing_dependencies,
        ) == 2
        assert logging.root.manager.disable == logging.WARNING
    finally:
        logging.disable(previous)


def test_stdout_stderr_traceback_and_logs_never_expose_sensitive_values(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _RecordingStore()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=_full_factory(),
        output=print,
    )

    with caplog.at_level(logging.DEBUG):
        result = manual.main(
            ["--confirm-real-api"],
            dependencies=dependencies,
        )

    captured = capsys.readouterr()
    visible = captured.out + captured.err + caplog.text
    assert result == 0
    assert _FAKE_API_KEY not in visible
    assert _ASSISTANT_BODY not in visible
    assert _CONTINUATION_BODY not in visible
    assert "Authorization" not in visible
    assert "Traceback" not in visible


def test_sensitive_failure_does_not_enter_output_traceback_or_logs(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _RecordingStore()
    fake_sdk = FakeOpenAIClientFactory(
        (
            FakeOpenAIScenario(
                create_error=RuntimeError(
                    f"Authorization Bearer {_FAKE_API_KEY}"
                )
            ),
        )
    )
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=print,
    )

    with caplog.at_level(logging.DEBUG):
        result = manual.main(
            ["--confirm-real-api"],
            dependencies=dependencies,
        )

    captured = capsys.readouterr()
    visible = captured.out + captured.err + caplog.text
    assert result == 2
    assert _FAKE_API_KEY not in visible
    assert "Authorization" not in visible
    assert "Traceback" not in visible


def test_fake_run_uses_no_network_and_closes_underlying_resources() -> None:
    output: list[str] = []
    store = _RecordingStore()
    fake_sdk = _full_factory()
    dependencies, _, _ = _dependencies(
        store_factory=_StoreFactory(store),
        client_factory=fake_sdk,
        output=output.append,
    )

    result = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert result == 0
    assert fake_sdk.network_request_count == 0
    assert all(client.closed for client in fake_sdk.clients)
    assert all(
        stream.closed
        for client in fake_sdk.clients
        for stream in client.streams
    )
    assert all(
        isinstance(stream, FakeOpenAIResponseStream)
        for client in fake_sdk.clients
        for stream in client.streams
    )
    assert all(
        isinstance(client, FakeOpenAIResponsesClient)
        for client in fake_sdk.clients
    )
