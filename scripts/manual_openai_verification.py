"""Explicit, bounded real-OpenAI verification for Windows maintainers.

This module is inert unless ``--confirm-real-api`` is supplied and the
interactive confirmation succeeds. It never reads an API key from argv or the
environment.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import hmac
import logging
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

import openai

if TYPE_CHECKING or __package__:
    from scripts.manual_credential_targets import (
        OPENAI_MANUAL_TEST_TARGET,
        ManualCredentialTargetResolver,
    )
else:
    from manual_credential_targets import (
        OPENAI_MANUAL_TEST_TARGET,
        ManualCredentialTargetResolver,
    )
from sjtuclaw.config.errors import SecretStoreError
from sjtuclaw.config.secrets import SecretStore, SecretValue
from sjtuclaw.domain.events import LLMEvent, LLMEventType
from sjtuclaw.domain.models import (
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    ChatMessage,
    CredentialId,
    LLMRequest,
    MessageRole,
    ProviderContinuation,
)
from sjtuclaw.infrastructure.llm.openai_provider import OpenAIProvider
from sjtuclaw.infrastructure.llm.openai_sdk import (
    JSONObject,
    OfficialOpenAIClientFactory,
    OpenAIClientFactory,
    OpenAIRequest,
    OpenAIResponseEvent,
    OpenAIResponsesClient,
    OpenAIResponseStream,
)
from sjtuclaw.infrastructure.security.windows_credential_store import (
    WindowsCredentialSecretStore,
)

_CONFIRM_FLAG = "--confirm-real-api"
_EXPECTED_SDK_VERSION = "2.48.0"
_MODEL = "gpt-5-mini"
_TEST_TARGET = OPENAI_MANUAL_TEST_TARGET
_FAKE_INVALID_KEY = "sk-test-never-use-this-value"
_MAX_REQUEST_ATTEMPTS = 7
_MANUAL_MAX_OUTPUT_TOKENS = 25_000
_MANUAL_REQUEST_TIMEOUT_SECONDS = 60.0
_MANUAL_COOPERATIVE_TIMEOUT_SECONDS = 600.0
_EXPECTED_CONFIRMATION = "RUN"
_CREATED_EVENT = "response.created"
_TEXT_DELTA_EVENT = "response.output_text.delta"
_COMPLETED_EVENT = "response.completed"


class _Output(Protocol):
    def __call__(self, value: str, /) -> None:
        """Emit one already-sanitized status line."""


@dataclass(frozen=True, slots=True)
class ManualVerificationDependencies:
    """Injectable boundaries for the otherwise real manual entry point."""

    platform: str
    sdk_version: str
    store_factory: Callable[[], SecretStore]
    client_factory: OpenAIClientFactory
    input_text: Callable[[str], str]
    get_secret: Callable[[str], str]
    output: _Output


@dataclass(slots=True)
class ManualVerificationChecks:
    """Safe booleans that jointly determine the manual verification exit code."""

    first_turn_completed: bool = False
    continuation_completed: bool = False
    continuation_replayed_exactly: bool = False
    first_delta_observed: bool = False
    cancelled_stream_closed: bool = False
    provider_reused_after_cancel: bool = False
    create_cancel_left_no_active_streams: bool = False
    invalid_key_mapped: bool = False
    old_client_closed_after_rotation: bool = False
    restored_key_completed: bool = False
    deleted_key_blocked_request: bool = False
    all_store_false: bool = False
    sdk_retries_disabled: bool = False
    request_limit_respected: bool = False
    all_streams_closed: bool = False
    all_clients_closed: bool = False
    no_close_failures: bool = False
    target_ownership_preserved: bool = False
    target_cleanup_succeeded: bool = False
    safe_code: str = "none"

    @property
    def successful(self) -> bool:
        return self.safe_code == "none" and all(
            getattr(self, check.name) is True
            for check in fields(self)
            if check.name != "safe_code"
        )


@dataclass(frozen=True, slots=True, repr=False)
class _SafeResult:
    assistant_text: str
    continuation: ProviderContinuation | None
    event_types: tuple[str, ...]
    delta_char_count: int
    completed: bool
    safe_code: str


@dataclass(frozen=True, slots=True)
class _CancellationResult:
    first_delta_observed: bool
    stream_closed: bool
    provider_open: bool
    delta_char_count: int
    event_types: tuple[str, ...]
    safe_code: str = ""


@dataclass(frozen=True, slots=True)
class _ObservedRawEvent:
    raw_type: str
    has_nonempty_text: bool = False


class _ManualVerificationFailure(Exception):
    def __init__(self) -> None:
        super().__init__("Manual verification failed safely.")


class _TargetOwnershipLost(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("The test credential ownership was lost safely.")


class OwnedTestSecretStore:
    """Manual-only value-ownership guard around the fixed test Target."""

    def __init__(self, delegate: SecretStore) -> None:
        self._delegate = delegate
        self._expected_fingerprint: bytes | None = None
        self.ownership_lost = False

    @property
    def owns_value(self) -> bool:
        return self._expected_fingerprint is not None

    def __repr__(self) -> str:
        return "<OwnedTestSecretStore>"

    def has_openai_api_key(self) -> bool:
        return self.get_openai_api_key() is not None

    def has_secret(self, credential_id: CredentialId) -> bool:
        return self.get_secret(credential_id) is not None

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
        if credential_id != OPENAI_DEFAULT_CREDENTIAL_ID:
            return
        self.delete_openai_api_key()

    def get_openai_api_key(self) -> SecretValue | None:
        current = self._read_current()
        expected = self._expected_fingerprint
        if expected is None:
            if current is None:
                return None
            self._raise_ownership_lost()
        if current is None:
            self._raise_ownership_lost()

        current_text = current.reveal()
        current_fingerprint = _secret_fingerprint(current_text)
        if (
            current_fingerprint is None
            or not hmac.compare_digest(current_fingerprint, expected)
        ):
            self._raise_ownership_lost()
        return SecretValue(current_text)

    def set_openai_api_key(self, value: SecretValue) -> None:
        self.verify_ownership()
        new_fingerprint = _secret_fingerprint(value.reveal())
        if new_fingerprint is None:
            raise SecretStoreError(
                "The test credential could not be encoded safely."
            )

        write_failed = False
        try:
            self._delegate.set_openai_api_key(value)
        except Exception:
            write_failed = True
        if write_failed:
            raise SecretStoreError(
                "The test credential could not be written safely."
            ) from None

        self._expected_fingerprint = new_fingerprint
        self.verify_ownership()

    def delete_openai_api_key(self) -> None:
        self.verify_ownership()
        if self._expected_fingerprint is None:
            return

        delete_failed = False
        try:
            self._delegate.delete_openai_api_key()
        except Exception:
            delete_failed = True
        if delete_failed:
            raise SecretStoreError(
                "The test credential could not be deleted safely."
            ) from None

        current = self._read_current()
        if current is None:
            self._expected_fingerprint = None
            return
        current_fingerprint = _secret_fingerprint(current.reveal())
        if (
            current_fingerprint is None
            or not hmac.compare_digest(
                current_fingerprint,
                self._expected_fingerprint,
            )
        ):
            self._raise_ownership_lost()
        raise SecretStoreError(
            "The test credential deletion was not confirmed."
        )

    def verify_ownership(self) -> None:
        if self.ownership_lost:
            raise _TargetOwnershipLost() from None
        self.get_openai_api_key()

    def _read_current(self) -> SecretValue | None:
        read_failed = False
        current: SecretValue | None = None
        try:
            current = self._delegate.get_openai_api_key()
        except Exception:
            read_failed = True
        if read_failed:
            self._raise_ownership_lost()
        return current

    def _raise_ownership_lost(self) -> NoReturn:
        self.ownership_lost = True
        raise _TargetOwnershipLost() from None


class _AuditStream:
    def __init__(
        self,
        delegate: OpenAIResponseStream,
        raw_event_types: list[str],
        observed_events: list[_ObservedRawEvent],
        owner: _AuditFactory,
        request_index: int,
    ) -> None:
        self._delegate = delegate
        self._raw_event_types = raw_event_types
        self._observed_events = observed_events
        self._owner = owner
        self._request_index = request_index
        self.closed = False

    def __aiter__(self) -> AsyncIterator[OpenAIResponseEvent]:
        return self

    async def __anext__(self) -> OpenAIResponseEvent:
        event = await self._delegate.__anext__()
        self._raw_event_types.append(event.raw_type)
        self._observed_events.append(
            _ObservedRawEvent(
                raw_type=event.raw_type,
                has_nonempty_text=(
                    event.raw_type == _TEXT_DELTA_EVENT and bool(event.text)
                ),
            )
        )
        if event.raw_type == _COMPLETED_EVENT:
            self._owner.completed_output_items[self._request_index] = (
                event.output_items
            )
        return event

    async def close(self) -> None:
        if self.closed:
            return
        try:
            await self._delegate.close()
        except (Exception, asyncio.CancelledError):
            self._owner.close_failure_observed = True
            raise
        self.closed = True


class _AuditClient:
    def __init__(
        self,
        delegate: OpenAIResponsesClient,
        owner: _AuditFactory,
    ) -> None:
        self._delegate = delegate
        self._owner = owner
        self.streams: list[_AuditStream] = []
        self.request_count = 0
        self.closed = False

    async def create(self, request: OpenAIRequest) -> OpenAIResponseStream:
        if request.store is not False:
            self._owner.all_store_false = False
            raise _ManualVerificationFailure() from None
        if self._owner.request_attempts >= self._owner.max_request_attempts:
            self._owner.request_limit_exceeded = True
            raise _ManualVerificationFailure() from None

        self._owner.request_attempts += 1
        self.request_count += 1
        request_index = len(self._owner.request_inputs)
        self._owner.request_inputs.append(request.input)
        self._owner.completed_output_items.append(None)
        self._owner.store_false_checks.append(True)
        self._owner.assistant_role_counts.append(
            sum(item.get("role") == "assistant" for item in request.input)
        )
        raw_event_types: list[str] = []
        self._owner.raw_event_types.append(raw_event_types)
        observed_events: list[_ObservedRawEvent] = []
        self._owner.observed_raw_events.append(observed_events)
        self._owner.create_in_flight += 1
        if self._owner.create_started is not None:
            self._owner.create_started.set()
        try:
            delegate_stream = await self._delegate.create(request)
        finally:
            self._owner.create_in_flight -= 1

        self._owner.delegate_create_returns += 1
        stream = _AuditStream(
            delegate_stream,
            raw_event_types,
            observed_events,
            self._owner,
            request_index,
        )
        self.streams.append(stream)
        return stream

    async def close(self) -> None:
        if self.closed:
            return
        try:
            await self._delegate.close()
        except (Exception, asyncio.CancelledError):
            self._owner.close_failure_observed = True
            raise
        self.closed = True


class _AuditFactory:
    def __init__(
        self,
        delegate: OpenAIClientFactory,
        *,
        max_request_attempts: int = _MAX_REQUEST_ATTEMPTS,
    ) -> None:
        self._delegate = delegate
        self.max_request_attempts = max_request_attempts
        self.clients: list[_AuditClient] = []
        self.request_attempts = 0
        self.request_limit_exceeded = False
        self.all_store_false = True
        self.retries_disabled = True
        self.store_false_checks: list[bool] = []
        self.assistant_role_counts: list[int] = []
        self.request_inputs: list[tuple[JSONObject, ...]] = []
        self.completed_output_items: list[
            tuple[JSONObject, ...] | None
        ] = []
        self.raw_event_types: list[list[str]] = []
        self.observed_raw_events: list[list[_ObservedRawEvent]] = []
        self.close_failure_observed = False
        self.create_started: asyncio.Event | None = None
        self.create_in_flight = 0
        self.delegate_create_returns = 0

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> OpenAIResponsesClient:
        if max_retries != 0:
            self.retries_disabled = False
            raise _ManualVerificationFailure() from None
        delegate = self._delegate.create(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        client = _AuditClient(delegate, self)
        self.clients.append(client)
        return client


def _request(
    content: str,
    *,
    messages: tuple[ChatMessage, ...] | None = None,
    continuation: ProviderContinuation | None = None,
) -> LLMRequest:
    return LLMRequest(
        instructions="Reply briefly and safely.",
        messages=messages
        or (ChatMessage(role=MessageRole.USER, content=content),),
        store=False,
        max_output_tokens=_MANUAL_MAX_OUTPUT_TOKENS,
        continuation=continuation,
    )


async def _collect(
    provider: OpenAIProvider,
    request: LLMRequest,
    audit: _AuditFactory,
) -> _SafeResult:
    assistant_parts: list[str] = []
    event_types: list[str] = []
    continuation: ProviderContinuation | None = None
    safe_code = ""
    completed = False
    raw_event_count_before = len(audit.raw_event_types)
    async for event in provider.generate_stream(request):
        event_types.append(event.type.value)
        if event.type is LLMEventType.TEXT_DELTA:
            assistant_parts.append(event.text)
        elif event.type is LLMEventType.COMPLETED:
            continuation = event.continuation
            completed = True
        elif event.type is LLMEventType.ERROR:
            safe_code = event.error_code
    assistant_text = "".join(assistant_parts)
    if len(audit.raw_event_types) > raw_event_count_before:
        event_types = audit.raw_event_types[-1]
    return _SafeResult(
        assistant_text=assistant_text,
        continuation=continuation,
        event_types=tuple(event_types),
        delta_char_count=len(assistant_text),
        completed=completed,
        safe_code=safe_code,
    )


def _raise_for_bounded_failure(
    safe_code: str,
    checks: ManualVerificationChecks,
) -> None:
    if safe_code == "output_budget_exhausted":
        checks.safe_code = "verification_output_budget_exhausted"
        raise _ManualVerificationFailure()
    if safe_code == "request_timeout":
        checks.safe_code = "verification_request_timeout"
        raise _ManualVerificationFailure()


def _emit_result(
    output: _Output,
    number: int,
    result: _SafeResult,
) -> None:
    event_types = ",".join(result.event_types)
    continuation_size = (
        len(result.continuation.state)
        if result.continuation is not None
        else 0
    )
    output(
        f"request_number={number} event_types={event_types} "
        f"delta_char_count={result.delta_char_count} "
        f"completion={result.completed} safe_code={result.safe_code or 'none'} "
        f"continuation_size={continuation_size}"
    )


async def _cancel_after_first_event(
    provider: OpenAIProvider,
    audit: _AuditFactory,
) -> _CancellationResult:
    stream_count_before = _audit_stream_count(audit)
    iterator = cast(
        AsyncGenerator[LLMEvent, None],
        provider.generate_stream(_request("Reply with one word.")),
    )
    event: LLMEvent | None = None
    try:
        event = await anext(iterator)
    finally:
        await iterator.aclose()

    new_streams = _audit_streams(audit)[stream_count_before:]
    raw_types = (
        tuple(audit.raw_event_types[-1])
        if audit.raw_event_types
        else ()
    )
    return _CancellationResult(
        first_delta_observed=(
            event is not None and event.type is LLMEventType.TEXT_DELTA
        ),
        stream_closed=(
            bool(new_streams)
            and all(stream.closed for stream in new_streams)
            and provider.active_stream_count == 0
        ),
        provider_open=not provider.closed,
        delta_char_count=len(event.text) if event is not None else 0,
        event_types=raw_types,
        safe_code=(
            event.error_code
            if event is not None and event.type is LLMEventType.ERROR
            else ""
        ),
    )


async def _cancel_during_create(
    provider: OpenAIProvider,
    audit: _AuditFactory,
) -> bool:
    started = asyncio.Event()
    audit.create_started = started
    audit_stream_count_before = _audit_stream_count(audit)
    iterator = cast(
        AsyncGenerator[LLMEvent, None],
        provider.generate_stream(_request("Reply with one word.")),
    )
    task: asyncio.Task[LLMEvent] = asyncio.create_task(_next_event(iterator))
    cancelled = False
    create_was_in_flight = False
    try:
        await asyncio.wait_for(started.wait(), timeout=5.0)
        create_was_in_flight = audit.create_in_flight > 0
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            cancelled = True
    finally:
        audit.create_started = None
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                cancelled = True
        await iterator.aclose()

    return (
        create_was_in_flight
        and cancelled
        and audit.create_in_flight == 0
        and _audit_stream_count(audit) == audit_stream_count_before
        and provider.active_stream_count == 0
        and not provider.closed
    )


async def _next_event(iterator: AsyncIterator[LLMEvent]) -> LLMEvent:
    return await anext(iterator)


def _sse_lifecycle_is_valid(
    events: Sequence[_ObservedRawEvent],
) -> bool:
    raw_types = tuple(event.raw_type for event in events)
    if raw_types.count(_CREATED_EVENT) != 1:
        return False
    if raw_types.count(_COMPLETED_EVENT) != 1:
        return False
    if any(
        raw_type == "error"
        or raw_type.endswith(".error")
        or raw_type.endswith(".failed")
        or raw_type.endswith(".incomplete")
        or raw_type.endswith(".cancelled")
        for raw_type in raw_types
    ):
        return False

    created_index = raw_types.index(_CREATED_EVENT)
    completed_index = raw_types.index(_COMPLETED_EVENT)
    nonempty_delta_indices = tuple(
        index
        for index, event in enumerate(events)
        if (
            event.raw_type == _TEXT_DELTA_EVENT
            and event.has_nonempty_text
        )
    )
    if not nonempty_delta_indices:
        return False
    return (
        created_index < nonempty_delta_indices[0] < completed_index
        and completed_index == len(events) - 1
    )


def _continuation_replay_is_exact(
    first_input: tuple[JSONObject, ...],
    first_output_items: tuple[JSONObject, ...] | None,
    second_input: tuple[JSONObject, ...],
) -> bool:
    if not first_output_items:
        return False
    expected_new_user: JSONObject = {
        "role": "user",
        "content": "One more word.",
    }
    expected = first_input + first_output_items + (expected_new_user,)
    return second_input == expected


def _secret_fingerprint(value: str) -> bytes | None:
    try:
        return hashlib.sha256(value.encode("utf-8")).digest()
    except UnicodeEncodeError:
        return None


async def _run_real_verification(
    api_key: str,
    *,
    store: SecretStore,
    client_factory: OpenAIClientFactory,
    output: _Output,
) -> ManualVerificationChecks:
    checks = ManualVerificationChecks()
    audit = _AuditFactory(client_factory)
    provider: OpenAIProvider | None = None
    owned_store = OwnedTestSecretStore(store)
    try:
        owned_store.set_openai_api_key(SecretValue(api_key))
        checks.target_ownership_preserved = True
        provider = OpenAIProvider(
            secret_store=owned_store,
            model=_MODEL,
            timeout_seconds=_MANUAL_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
            stream=True,
            client_factory=audit,
        )

        first_messages = (
            ChatMessage(role=MessageRole.USER, content="Reply with one word."),
        )
        first = await _collect(
            provider,
            _request("unused", messages=first_messages),
            audit,
        )
        _emit_result(output, 1, first)
        _raise_for_bounded_failure(first.safe_code, checks)
        checks.first_turn_completed = (
            first.completed
            and first.continuation is not None
            and first.delta_char_count > 0
            and bool(audit.observed_raw_events)
            and _sse_lifecycle_is_valid(audit.observed_raw_events[-1])
        )
        if not checks.first_turn_completed:
            raise _ManualVerificationFailure()

        second_messages = (
            first_messages[0],
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=first.assistant_text,
            ),
            ChatMessage(role=MessageRole.USER, content="One more word."),
        )
        second = await _collect(
            provider,
            _request(
                "unused",
                messages=second_messages,
                continuation=first.continuation,
            ),
            audit,
        )
        _emit_result(output, 2, second)
        _raise_for_bounded_failure(second.safe_code, checks)
        checks.continuation_completed = (
            second.completed
            and bool(audit.observed_raw_events)
            and _sse_lifecycle_is_valid(audit.observed_raw_events[-1])
        )
        checks.continuation_replayed_exactly = (
            audit.assistant_role_counts[-1] == 1
            and len(audit.request_inputs) >= 2
            and _continuation_replay_is_exact(
                audit.request_inputs[0],
                audit.completed_output_items[0],
                audit.request_inputs[1],
            )
        )
        if not (
            checks.continuation_completed
            and checks.continuation_replayed_exactly
        ):
            raise _ManualVerificationFailure()

        initial_client = audit.clients[0]
        cancellation = await _cancel_after_first_event(provider, audit)
        _raise_for_bounded_failure(cancellation.safe_code, checks)
        checks.first_delta_observed = cancellation.first_delta_observed
        checks.cancelled_stream_closed = (
            cancellation.stream_closed and cancellation.provider_open
        )
        output(
            "request_number=3 "
            f"event_types={','.join(cancellation.event_types)} "
            f"delta_char_count={cancellation.delta_char_count} "
            f"cancel={checks.first_delta_observed} "
            f"stream_closed={checks.cancelled_stream_closed}"
        )
        if not (
            checks.first_delta_observed
            and checks.cancelled_stream_closed
        ):
            raise _ManualVerificationFailure()

        reused = await _collect(
            provider,
            _request("Reply with one word."),
            audit,
        )
        _emit_result(output, 4, reused)
        _raise_for_bounded_failure(reused.safe_code, checks)
        checks.provider_reused_after_cancel = (
            reused.completed
            and len(audit.clients) == 1
            and audit.clients[0] is initial_client
            and not provider.closed
        )
        if not checks.provider_reused_after_cancel:
            raise _ManualVerificationFailure()

        checks.create_cancel_left_no_active_streams = (
            await _cancel_during_create(provider, audit)
        )
        output(
            "request_number=5 event_types=cancelled delta_char_count=0 "
            "cancel=True "
            f"stream_closed={checks.create_cancel_left_no_active_streams}"
        )
        if not checks.create_cancel_left_no_active_streams:
            raise _ManualVerificationFailure()

        initial_request_count = initial_client.request_count
        owned_store.set_openai_api_key(SecretValue(_FAKE_INVALID_KEY))
        invalid = await _collect(
            provider,
            _request("Reply with one word."),
            audit,
        )
        _emit_result(output, 6, invalid)
        _raise_for_bounded_failure(invalid.safe_code, checks)
        checks.invalid_key_mapped = invalid.safe_code == "invalid_api_key"
        checks.old_client_closed_after_rotation = (
            initial_client.closed
            and initial_client.request_count == initial_request_count
            and len(audit.clients) >= 2
            and audit.clients[-1] is not initial_client
        )
        output(
            "client_closed_after_rotation="
            f"{checks.old_client_closed_after_rotation}"
        )
        if not (
            checks.invalid_key_mapped
            and checks.old_client_closed_after_rotation
        ):
            raise _ManualVerificationFailure()

        invalid_client = audit.clients[-1]
        owned_store.set_openai_api_key(SecretValue(api_key))
        restored = await _collect(
            provider,
            _request("Reply with one word."),
            audit,
        )
        _emit_result(output, 7, restored)
        _raise_for_bounded_failure(restored.safe_code, checks)
        checks.restored_key_completed = (
            restored.completed
            and invalid_client.closed
            and audit.clients[-1] is not invalid_client
        )
        if not checks.restored_key_completed:
            raise _ManualVerificationFailure()

        current_client = audit.clients[-1]
        request_attempts_before_delete = audit.request_attempts
        owned_store.delete_openai_api_key()
        target_absent = owned_store.get_openai_api_key() is None
        if not target_absent:
            raise _ManualVerificationFailure()
        missing = await _collect(
            provider,
            _request("Reply with one word."),
            audit,
        )
        _raise_for_bounded_failure(missing.safe_code, checks)
        checks.deleted_key_blocked_request = (
            target_absent
            and missing.safe_code == "missing_api_key"
            and audit.request_attempts == request_attempts_before_delete
            and current_client.closed
        )
        checks.target_cleanup_succeeded = target_absent
        output(f"safe_code_after_deletion={missing.safe_code or 'none'}")
        if not checks.deleted_key_blocked_request:
            raise _ManualVerificationFailure()
    except _TargetOwnershipLost:
        checks.target_ownership_preserved = False
        checks.safe_code = "test_target_ownership_lost"
    except asyncio.CancelledError:
        raise
    except Exception:
        if owned_store.ownership_lost:
            checks.target_ownership_preserved = False
            checks.safe_code = "test_target_ownership_lost"
    finally:
        if provider is not None:
            try:
                await provider.aclose()
                await provider.aclose()
            except Exception:
                pass
            streams = _audit_streams(audit)
            checks.all_streams_closed = (
                bool(streams)
                and all(stream.closed for stream in streams)
                and provider.active_stream_count == 0
            )
            checks.all_clients_closed = (
                bool(audit.clients)
                and all(client.closed for client in audit.clients)
                and provider.active_stream_count == 0
            )
        checks.no_close_failures = not audit.close_failure_observed

        checks.all_store_false = (
            bool(audit.store_false_checks)
            and audit.all_store_false
            and all(audit.store_false_checks)
        )
        checks.sdk_retries_disabled = audit.retries_disabled
        checks.request_limit_respected = (
            audit.request_attempts == _MAX_REQUEST_ATTEMPTS
            and not audit.request_limit_exceeded
        )

        if owned_store.ownership_lost:
            checks.target_ownership_preserved = False
            checks.target_cleanup_succeeded = False
            checks.safe_code = "test_target_ownership_lost"
        elif owned_store.owns_value:
            try:
                owned_store.delete_openai_api_key()
                checks.target_cleanup_succeeded = (
                    owned_store.get_openai_api_key() is None
                )
            except _TargetOwnershipLost:
                checks.target_ownership_preserved = False
                checks.target_cleanup_succeeded = False
                checks.safe_code = "test_target_ownership_lost"
            except Exception:
                checks.target_cleanup_succeeded = False
        output(f"request_attempts={audit.request_attempts}")
        output(f"clients_closed={checks.all_clients_closed}")
        output(f"streams_closed={checks.all_streams_closed}")
        output(f"target_cleanup={checks.target_cleanup_succeeded}")

    return checks


async def _run_with_cooperative_timeout(
    api_key: str,
    *,
    store: SecretStore,
    client_factory: OpenAIClientFactory,
    output: _Output,
) -> ManualVerificationChecks:
    """Request cancellation on timeout, then wait for cleanup to finish."""
    return await asyncio.wait_for(
        _run_real_verification(
            api_key,
            store=store,
            client_factory=client_factory,
            output=output,
        ),
        timeout=_MANUAL_COOPERATIVE_TIMEOUT_SECONDS,
    )


def _audit_streams(audit: _AuditFactory) -> list[_AuditStream]:
    return [
        stream
        for client in audit.clients
        for stream in client.streams
    ]


def _audit_stream_count(audit: _AuditFactory) -> int:
    return len(_audit_streams(audit))


def _windows_store_factory() -> SecretStore:
    return WindowsCredentialSecretStore(
        openai_credential_id=OPENAI_MANUAL_TEST_CREDENTIAL_ID,
        target_resolver=ManualCredentialTargetResolver(),
    )


def _default_dependencies() -> ManualVerificationDependencies:
    return ManualVerificationDependencies(
        platform=sys.platform,
        sdk_version=openai.__version__,
        store_factory=_windows_store_factory,
        client_factory=OfficialOpenAIClientFactory(),
        input_text=input,
        get_secret=getpass.getpass,
        output=print,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded, explicit real OpenAI verification.",
    )
    parser.add_argument(
        _CONFIRM_FLAG,
        action="store_true",
        help="Allow real API requests and use the fixed test credential Target.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: ManualVerificationDependencies | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_real_api:
        output = dependencies.output if dependencies is not None else print
        output("safe_code=manual_verification_disabled")
        return 0

    active = dependencies or _default_dependencies()
    if active.platform != "win32":
        active.output("safe_code=windows_required")
        return 2
    if active.sdk_version != _EXPECTED_SDK_VERSION:
        active.output(
            f"sdk_version={active.sdk_version} "
            "safe_code=sdk_version_mismatch"
        )
        return 2

    active.output(f"sdk_version={active.sdk_version} model={_MODEL}")
    active.output(f"expected_request_attempts={_MAX_REQUEST_ATTEMPTS}")
    active.output(
        f"max_output_tokens={_MANUAL_MAX_OUTPUT_TOKENS} "
        f"request_timeout_seconds={_MANUAL_REQUEST_TIMEOUT_SECONDS:g} "
        "cooperative_timeout_action=cancel_then_wait_for_cleanup "
        "cooperative_timeout_seconds="
        f"{_MANUAL_COOPERATIVE_TIMEOUT_SECONDS:g}"
    )
    try:
        confirmation = active.input_text("Type RUN to continue: ")
    except Exception:
        active.output("safe_code=confirmation_failed")
        return 2
    if confirmation != _EXPECTED_CONFIRMATION:
        active.output("safe_code=not_confirmed")
        return 2

    try:
        store = active.store_factory()
        if store.get_openai_api_key() is not None:
            active.output("safe_code=test_target_occupied")
            return 2
    except Exception:
        active.output("safe_code=test_target_check_failed")
        return 2

    try:
        api_key = active.get_secret(
            "OpenAI API key (hidden input): "
        ).strip()
    except Exception:
        active.output("safe_code=secret_input_failed")
        return 2
    if not api_key:
        active.output("safe_code=empty_key")
        return 2

    try:
        if store.get_openai_api_key() is not None:
            api_key = ""
            active.output("safe_code=test_target_occupied")
            return 2
    except Exception:
        api_key = ""
        active.output("safe_code=test_target_check_failed")
        return 2

    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        checks = asyncio.run(
            _run_with_cooperative_timeout(
                api_key,
                store=store,
                client_factory=active.client_factory,
                output=active.output,
            )
        )
        if checks.successful:
            active.output("verification_complete=True safe_code=none")
            return 0
        if checks.safe_code != "none":
            active.output(
                "verification_complete=False "
                f"safe_code={checks.safe_code}"
            )
            return 2
        active.output(
            "verification_complete=False "
            "safe_code=manual_verification_failed"
        )
        return 2
    except TimeoutError:
        active.output(
            "verification_complete=False "
            "safe_code=verification_runtime_timeout"
        )
        return 2
    except Exception:
        active.output(
            "verification_complete=False "
            "safe_code=manual_verification_failed"
        )
        return 2
    finally:
        logging.disable(previous_logging_disable)
        api_key = ""


if __name__ == "__main__":
    raise SystemExit(main())
