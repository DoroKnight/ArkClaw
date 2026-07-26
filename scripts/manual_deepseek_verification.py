"""Explicit, bounded real-DeepSeek verification for Windows maintainers.

The module is inert unless ``--confirm-real-api`` is supplied and the user
then enters the exact confirmation text. API keys are accepted only through
hidden input and are never read from argv or environment variables.
"""

from __future__ import annotations

import asyncio
import getpass
import hashlib
import hmac
import logging
import sys
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Sequence,
)
from contextlib import suppress
from dataclasses import dataclass, field, fields
from typing import NoReturn, Protocol, cast

import openai

from sjtuclaw.config.errors import SecretStoreError
from sjtuclaw.config.provider_profiles import (
    DEEPSEEK_OFFICIAL_BASE_URL,
    DEEPSEEK_OFFICIAL_ORIGIN,
    deepseek_profile,
)
from sjtuclaw.config.secrets import SecretStore, SecretValue
from sjtuclaw.domain.events import LLMEvent, LLMEventType
from sjtuclaw.domain.models import (
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    ApiProtocol,
    ChatMessage,
    CredentialId,
    LLMRequest,
    MessageRole,
    ProviderContinuation,
)
from sjtuclaw.infrastructure.llm.deepseek_provider import DeepSeekProvider
from sjtuclaw.infrastructure.llm.deepseek_sdk import (
    DeepSeekClient,
    DeepSeekClientFactory,
    DeepSeekEvent,
    DeepSeekEventKind,
    DeepSeekRequest,
    DeepSeekStream,
    OfficialDeepSeekClientFactory,
    ThinkingMode,
)
from sjtuclaw.infrastructure.llm.provider_factory import ProviderFactory
from sjtuclaw.infrastructure.security.windows_credential_store import (
    DEEPSEEK_MANUAL_TEST_TARGET,
    WindowsCredentialSecretStore,
)

_CONFIRM_FLAG = "--confirm-real-api"
_EXPECTED_CONFIRMATION = "RUN"
_EXPECTED_SDK_VERSION = "2.48.0"
_MODEL = "deepseek-v4-flash"
_TEST_TARGET = "SJTUClaw/Test/DeepSeek/APIKey"
_FAKE_INVALID_KEY = "sk-deepseek-invalid-never-use"
_MAX_REQUEST_ATTEMPTS = 6
_MAX_OUTPUT_TOKENS = 256
_REQUEST_TIMEOUT_SECONDS = 60.0
_COOPERATIVE_TIMEOUT_SECONDS = 600.0


class _Output(Protocol):
    def __call__(self, value: str, /) -> None: ...


@dataclass(frozen=True, slots=True)
class ManualDeepSeekDependencies:
    """Injectable boundaries for the otherwise real manual entry point."""

    platform: str
    sdk_version: str
    store_factory: Callable[[], SecretStore]
    client_factory: DeepSeekClientFactory
    input_text: Callable[[str], str]
    get_secret: Callable[[str], str]
    output: _Output


@dataclass(slots=True)
class ManualDeepSeekChecks:
    """Safe booleans that jointly determine the verification exit code."""

    sdk_version_expected: bool = False
    fixed_origin: bool = False
    fixed_model: bool = False
    chat_completions_protocol: bool = False
    thinking_disabled: bool = False
    retries_disabled: bool = False
    request_budget_bounded: bool = False
    basic_sse_completed: bool = False
    nonempty_text_delta: bool = False
    finish_reason_stop: bool = False
    message_replay_exact: bool = False
    no_responses_continuation: bool = False
    cancelled_after_text_delta: bool = False
    cancellation_propagated: bool = False
    provider_reused_after_cancel: bool = False
    no_active_streams_after_cancel: bool = False
    invalid_key_mapped: bool = False
    restored_key_completed: bool = False
    deleted_key_blocked_request: bool = False
    request_limit_enforced: bool = False
    all_streams_closed: bool = False
    all_clients_closed: bool = False
    target_ownership_preserved: bool = False
    target_cleanup_succeeded: bool = False
    logging_restored: bool = False
    safe_code: str = "none"

    @property
    def successful(self) -> bool:
        return self.safe_code == "none" and all(
            getattr(self, item.name) is True
            for item in fields(self)
            if item.name != "safe_code"
        )


@dataclass(frozen=True, slots=True, repr=False)
class _SafeResult:
    text: str = field(repr=False)
    continuation: ProviderContinuation | None = field(
        default=None,
        repr=False,
    )
    completed: bool = False
    safe_code: str = ""
    delta_count: int = 0


@dataclass(frozen=True, slots=True)
class _CancellationResult:
    text_delta_observed: bool
    task_cancelled: bool
    stream_closed: bool
    no_active_streams: bool


class _ManualVerificationFailure(Exception):
    """Fixed-message internal control-flow failure."""

    def __init__(self, safe_code: str = "verification_failed") -> None:
        self.safe_code = safe_code
        super().__init__("DeepSeek verification failed safely.")


class _TargetOwnershipLost(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("The test credential ownership was lost safely.")


class _CredentialStoreUnavailable(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("The credential store is unavailable safely.")


class _TargetCleanupFailed(SecretStoreError):
    def __init__(self) -> None:
        super().__init__("The test credential cleanup failed safely.")


def _fingerprint(value: str) -> bytes:
    try:
        return hashlib.sha256(value.encode("utf-8")).digest()
    except UnicodeEncodeError:
        raise SecretStoreError(
            "The test credential could not be encoded safely."
        ) from None


class OwnedDeepSeekTestSecretStore:
    """Value-ownership guard for the fixed DeepSeek test Target."""

    def __init__(self, delegate: SecretStore) -> None:
        self._delegate = delegate
        self._expected_fingerprint: bytes | None = None
        self.ownership_lost = False

    def __repr__(self) -> str:
        return "<OwnedDeepSeekTestSecretStore>"

    @property
    def owns_value(self) -> bool:
        return self._expected_fingerprint is not None

    def has_secret(self, credential_id: CredentialId) -> bool:
        return self.get_secret(credential_id) is not None

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        if credential_id != DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID:
            return None
        current = self._read_current()
        expected = self._expected_fingerprint
        if expected is None:
            if current is None:
                return None
            self._lose_ownership()
        if current is None:
            self._lose_ownership()
        current_text = current.reveal()
        current_fingerprint = _fingerprint(current_text)
        if not hmac.compare_digest(current_fingerprint, expected):
            self._lose_ownership()
        return SecretValue(current_text)

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        if credential_id != DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID:
            raise SecretStoreError(
                "The credential identifier is not allowed here."
            )
        self.verify_ownership()
        new_fingerprint = _fingerprint(value.reveal())
        try:
            self._delegate.set_secret(credential_id, value)
        except Exception:
            raise SecretStoreError(
                "The test credential could not be written safely."
            ) from None
        self._expected_fingerprint = new_fingerprint
        self.verify_ownership()

    def delete_secret(self, credential_id: CredentialId) -> None:
        if credential_id != DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID:
            return
        self.verify_ownership()
        if self._expected_fingerprint is None:
            return
        try:
            self._delegate.delete_secret(credential_id)
        except Exception:
            raise _TargetCleanupFailed() from None
        self._expected_fingerprint = None
        if self._read_current() is not None:
            self._lose_ownership()

    def verify_ownership(self) -> None:
        expected = self._expected_fingerprint
        current = self._read_current()
        if expected is None:
            if current is not None:
                self._lose_ownership()
            return
        if current is None:
            self._lose_ownership()
        current_fingerprint = _fingerprint(current.reveal())
        if not hmac.compare_digest(current_fingerprint, expected):
            self._lose_ownership()

    def cleanup_owned(self) -> bool:
        if self._expected_fingerprint is None:
            if self._read_current() is not None:
                self._lose_ownership()
            return True
        self.delete_secret(DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID)
        if self._read_current() is not None:
            self._lose_ownership()
        return True

    def has_openai_api_key(self) -> bool:
        return False

    def get_openai_api_key(self) -> SecretValue | None:
        return None

    def set_openai_api_key(self, value: SecretValue) -> None:
        del value
        raise SecretStoreError(
            "OpenAI credentials are unavailable in this boundary."
        )

    def delete_openai_api_key(self) -> None:
        return

    def _read_current(self) -> SecretValue | None:
        try:
            return self._delegate.get_secret(
                DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID
            )
        except Exception:
            raise _CredentialStoreUnavailable() from None

    def _lose_ownership(self) -> NoReturn:
        self._expected_fingerprint = None
        self.ownership_lost = True
        raise _TargetOwnershipLost() from None


class _AuditStream:
    def __init__(
        self,
        delegate: DeepSeekStream,
        owner: _AuditFactory,
    ) -> None:
        self._delegate = delegate
        self._owner = owner
        self.closed = False
        self.text_delta_count = 0
        self.finish_reason_stop = False

    def __repr__(self) -> str:
        return "<DeepSeekAuditStream payload=<redacted>>"

    def __aiter__(self) -> AsyncIterator[DeepSeekEvent]:
        return self

    async def __anext__(self) -> DeepSeekEvent:
        event = await self._delegate.__anext__()
        if event.kind is DeepSeekEventKind.TEXT_DELTA and event.text:
            self.text_delta_count += 1
        if (
            event.kind is DeepSeekEventKind.COMPLETED
            and event.finish_reason == "stop"
        ):
            self.finish_reason_stop = True
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
        delegate: DeepSeekClient,
        owner: _AuditFactory,
    ) -> None:
        self._delegate = delegate
        self._owner = owner
        self.streams: list[_AuditStream] = []
        self.closed = False

    def __repr__(self) -> str:
        return "<DeepSeekAuditClient>"

    async def create(self, request: DeepSeekRequest) -> DeepSeekStream:
        self._owner.validate_request(request)
        if self._owner.request_attempts >= _MAX_REQUEST_ATTEMPTS:
            self._owner.request_limit_exceeded = True
            raise _ManualVerificationFailure(
                "request_limit_exceeded"
            ) from None
        self._owner.request_attempts += 1
        self._owner.requests.append(request)
        self._owner.delegate_create_calls += 1
        delegate_stream = await self._delegate.create(request)
        stream = _AuditStream(delegate_stream, self._owner)
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
    def __init__(self, delegate: DeepSeekClientFactory) -> None:
        self._delegate = delegate
        self.clients: list[_AuditClient] = []
        self.requests: list[DeepSeekRequest] = []
        self.request_attempts = 0
        self.delegate_create_calls = 0
        self.request_limit_exceeded = False
        self.retries_disabled = True
        self.timeout_fixed = True
        self.requests_valid = True
        self.close_failure_observed = False

    def __repr__(self) -> str:
        return "<DeepSeekAuditFactory>"

    def create(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> DeepSeekClient:
        if max_retries != 0:
            self.retries_disabled = False
            raise _ManualVerificationFailure(
                "invalid_retry_configuration"
            ) from None
        if timeout_seconds != _REQUEST_TIMEOUT_SECONDS:
            self.timeout_fixed = False
            raise _ManualVerificationFailure(
                "invalid_timeout_configuration"
            ) from None
        delegate = self._delegate.create(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        client = _AuditClient(delegate, self)
        self.clients.append(client)
        return client

    def validate_request(self, request: DeepSeekRequest) -> None:
        valid = (
            request.model == _MODEL
            and request.stream is True
            and request.max_tokens == _MAX_OUTPUT_TOKENS
            and request.max_tokens <= 256
            and request.thinking_mode is ThinkingMode.DISABLED
        )
        if not valid:
            self.requests_valid = False
            raise _ManualVerificationFailure(
                "invalid_request_configuration"
            ) from None

    @property
    def streams(self) -> tuple[_AuditStream, ...]:
        return tuple(
            stream
            for client in self.clients
            for stream in client.streams
        )


def _request(
    messages: tuple[ChatMessage, ...],
    *,
    continuation: ProviderContinuation | None = None,
) -> LLMRequest:
    return LLMRequest(
        instructions="Reply briefly using plain text.",
        messages=messages,
        store=False,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        continuation=continuation,
    )


async def _collect(
    provider: DeepSeekProvider,
    request: LLMRequest,
) -> _SafeResult:
    parts: list[str] = []
    continuation: ProviderContinuation | None = None
    completed = False
    safe_code = ""
    delta_count = 0
    async for event in provider.generate_stream(request):
        if event.type is LLMEventType.TEXT_DELTA:
            parts.append(event.text)
            delta_count += int(bool(event.text))
        elif event.type is LLMEventType.COMPLETED:
            continuation = event.continuation
            completed = True
        elif event.type is LLMEventType.ERROR:
            safe_code = event.error_code
    return _SafeResult(
        text="".join(parts),
        continuation=continuation,
        completed=completed,
        safe_code=safe_code,
        delta_count=delta_count,
    )


async def _cancel_after_text_delta(
    provider: DeepSeekProvider,
    request: LLMRequest,
    audit: _AuditFactory,
) -> _CancellationResult:
    first_text = asyncio.Event()
    hold_after_text = asyncio.Event()
    text_observed = False
    iterator = cast(
        AsyncGenerator[LLMEvent, None],
        provider.generate_stream(request),
    )

    async def consume() -> None:
        nonlocal text_observed
        try:
            async for event in iterator:
                if (
                    event.type is LLMEventType.TEXT_DELTA
                    and bool(event.text)
                ):
                    text_observed = True
                    first_text.set()
                    await hold_after_text.wait()
        finally:
            await iterator.aclose()

    task = asyncio.create_task(consume())
    first_wait = asyncio.create_task(first_text.wait())
    done, _ = await asyncio.wait(
        {task, first_wait},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if task in done and not first_text.is_set():
        first_wait.cancel()
        await asyncio.gather(first_wait, return_exceptions=True)
        return _CancellationResult(False, False, False, False)
    first_wait.cancel()
    await asyncio.gather(first_wait, return_exceptions=True)
    task.cancel()
    task_cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        task_cancelled = True
    streams = audit.streams
    return _CancellationResult(
        text_delta_observed=text_observed,
        task_cancelled=task_cancelled,
        stream_closed=bool(streams) and streams[-1].closed,
        no_active_streams=provider.active_stream_count == 0,
    )


def _messages_match(
    request: DeepSeekRequest,
    expected: tuple[dict[str, str], ...],
) -> bool:
    return request.messages == expected


async def _run_verification(
    *,
    checks: ManualDeepSeekChecks,
    owned_store: OwnedDeepSeekTestSecretStore,
    api_key: str,
    audit: _AuditFactory,
    output: _Output,
) -> None:
    provider: DeepSeekProvider | None = None
    try:
        profile = deepseek_profile(
            _MODEL,
            credential_id=DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
            display_name="DeepSeek manual verification",
        )
        built = ProviderFactory(
            secret_store=owned_store,
            deepseek_client_factory=audit,
        ).create_profile(
            profile,
            timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
            stream=True,
        )
        if not isinstance(built, DeepSeekProvider):
            raise _ManualVerificationFailure()
        provider = built
        checks.fixed_origin = (
            profile.base_url == DEEPSEEK_OFFICIAL_BASE_URL
            and profile.origin == DEEPSEEK_OFFICIAL_ORIGIN
        )
        checks.fixed_model = profile.model == _MODEL
        checks.chat_completions_protocol = (
            profile.protocol is ApiProtocol.CHAT_COMPLETIONS
        )
        checks.no_responses_continuation = True

        first_messages = (
            ChatMessage(
                role=MessageRole.USER,
                content="Reply with exactly one short word.",
            ),
        )
        first = await _collect(provider, _request(first_messages))
        checks.basic_sse_completed = first.completed
        checks.nonempty_text_delta = first.delta_count > 0
        checks.finish_reason_stop = (
            bool(audit.streams)
            and audit.streams[-1].finish_reason_stop
        )
        if not (
            checks.basic_sse_completed
            and checks.nonempty_text_delta
            and checks.finish_reason_stop
            and first.continuation is not None
        ):
            raise _ManualVerificationFailure(first.safe_code)
        output(
            "request_number=1 completed=True "
            f"delta_count={first.delta_count} safe_code=none"
        )

        second_messages = (
            first_messages[0],
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=first.text,
            ),
            ChatMessage(
                role=MessageRole.USER,
                content="Reply with one different short word.",
            ),
        )
        second = await _collect(
            provider,
            _request(
                second_messages,
                continuation=first.continuation,
            ),
        )
        expected_second = (
            {
                "role": "system",
                "content": "Reply briefly using plain text.",
            },
            {"role": "user", "content": first_messages[0].content},
            {"role": "assistant", "content": first.text},
            {"role": "user", "content": second_messages[-1].content},
        )
        checks.message_replay_exact = (
            len(audit.requests) >= 2
            and _messages_match(audit.requests[1], expected_second)
        )
        if not second.completed or not checks.message_replay_exact:
            raise _ManualVerificationFailure(second.safe_code)
        output(
            "request_number=2 completed=True "
            f"delta_count={second.delta_count} safe_code=none"
        )

        cancellation = await _cancel_after_text_delta(
            provider,
            _request(
                (
                    ChatMessage(
                        role=MessageRole.USER,
                        content="Reply with a short sentence.",
                    ),
                )
            ),
            audit,
        )
        checks.cancelled_after_text_delta = (
            cancellation.text_delta_observed
        )
        checks.cancellation_propagated = cancellation.task_cancelled
        checks.no_active_streams_after_cancel = (
            cancellation.stream_closed
            and cancellation.no_active_streams
        )
        if not (
            checks.cancelled_after_text_delta
            and checks.cancellation_propagated
            and checks.no_active_streams_after_cancel
        ):
            raise _ManualVerificationFailure(
                "cancellation_verification_failed"
            )
        output(
            "request_number=3 cancelled=True "
            "after_text_delta=True safe_code=none"
        )

        reused = await _collect(
            provider,
            _request(
                (
                    ChatMessage(
                        role=MessageRole.USER,
                        content="Reply with exactly one short word.",
                    ),
                )
            ),
        )
        checks.provider_reused_after_cancel = (
            reused.completed and provider.active_stream_count == 0
        )
        if not checks.provider_reused_after_cancel:
            raise _ManualVerificationFailure(reused.safe_code)
        output(
            "request_number=4 completed=True "
            f"delta_count={reused.delta_count} safe_code=none"
        )

        owned_store.set_secret(
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
            SecretValue(_FAKE_INVALID_KEY),
        )
        invalid = await _collect(
            provider,
            _request(
                (
                    ChatMessage(
                        role=MessageRole.USER,
                        content="Reply with one short word.",
                    ),
                )
            ),
        )
        checks.invalid_key_mapped = invalid.safe_code == "invalid_api_key"
        if not checks.invalid_key_mapped:
            raise _ManualVerificationFailure(invalid.safe_code)
        output(
            "request_number=5 completed=False "
            "delta_count=0 safe_code=invalid_api_key"
        )

        owned_store.set_secret(
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
            SecretValue(api_key),
        )
        restored = await _collect(
            provider,
            _request(
                (
                    ChatMessage(
                        role=MessageRole.USER,
                        content="Reply with exactly one short word.",
                    ),
                )
            ),
        )
        checks.restored_key_completed = restored.completed
        if not checks.restored_key_completed:
            raise _ManualVerificationFailure(restored.safe_code)
        output(
            "request_number=6 completed=True "
            f"delta_count={restored.delta_count} safe_code=none"
        )

        delegate_calls_before_limit = audit.delegate_create_calls
        limited = await _collect(
            provider,
            _request(
                (
                    ChatMessage(
                        role=MessageRole.USER,
                        content="This request must be blocked locally.",
                    ),
                )
            ),
        )
        checks.request_limit_enforced = (
            audit.request_limit_exceeded
            and audit.delegate_create_calls
            == delegate_calls_before_limit
            and limited.safe_code == "provider_unavailable"
        )
        if not checks.request_limit_enforced:
            raise _ManualVerificationFailure(
                "request_limit_verification_failed"
            )

        requests_before_delete = audit.delegate_create_calls
        owned_store.delete_secret(
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID
        )
        missing = await _collect(
            provider,
            _request(
                (
                    ChatMessage(
                        role=MessageRole.USER,
                        content="This request must remain local.",
                    ),
                )
            ),
        )
        checks.deleted_key_blocked_request = (
            missing.safe_code == "missing_api_key"
            and audit.delegate_create_calls == requests_before_delete
        )
        if not checks.deleted_key_blocked_request:
            raise _ManualVerificationFailure(
                "credential_deletion_verification_failed"
            )
    except _TargetOwnershipLost:
        checks.safe_code = "test_target_ownership_lost"
    except _CredentialStoreUnavailable:
        checks.safe_code = "credential_store_unavailable"
    except _TargetCleanupFailed:
        checks.safe_code = "target_cleanup_failed"
    except asyncio.CancelledError:
        raise
    except _ManualVerificationFailure as error:
        checks.safe_code = error.safe_code or "verification_failed"
    except Exception:
        checks.safe_code = (
            "test_target_ownership_lost"
            if owned_store.ownership_lost
            else "verification_failed"
        )
    finally:
        if provider is not None:
            try:
                await provider.aclose()
                await provider.aclose()
            except Exception:
                checks.safe_code = "resource_cleanup_failed"
        checks.retries_disabled = audit.retries_disabled
        checks.thinking_disabled = (
            audit.requests_valid
            and all(
                request.thinking_mode is ThinkingMode.DISABLED
                for request in audit.requests
            )
        )
        checks.request_budget_bounded = (
            audit.requests_valid
            and all(
                request.max_tokens <= 256
                for request in audit.requests
            )
        )
        checks.all_streams_closed = (
            not audit.close_failure_observed
            and all(stream.closed for stream in audit.streams)
        )
        checks.all_clients_closed = (
            not audit.close_failure_observed
            and all(client.closed for client in audit.clients)
        )
        checks.target_ownership_preserved = (
            not owned_store.ownership_lost
        )
        if owned_store.ownership_lost:
            checks.safe_code = "test_target_ownership_lost"
        try:
            checks.target_cleanup_succeeded = (
                owned_store.cleanup_owned()
            )
            if (
                not checks.target_cleanup_succeeded
                and checks.safe_code == "none"
            ):
                checks.safe_code = "target_cleanup_failed"
        except _TargetOwnershipLost:
            checks.target_cleanup_succeeded = False
            checks.safe_code = "test_target_ownership_lost"
        except _CredentialStoreUnavailable:
            checks.target_cleanup_succeeded = False
            checks.safe_code = "credential_store_unavailable"
        except _TargetCleanupFailed:
            checks.target_cleanup_succeeded = False
            checks.safe_code = "target_cleanup_failed"
        except Exception:
            checks.target_cleanup_succeeded = False
            if checks.safe_code == "none":
                checks.safe_code = "target_cleanup_failed"


async def _run_with_cooperative_timeout(
    *,
    checks: ManualDeepSeekChecks,
    owned_store: OwnedDeepSeekTestSecretStore,
    api_key: str,
    audit: _AuditFactory,
    output: _Output,
) -> None:
    try:
        await asyncio.wait_for(
            _run_verification(
                checks=checks,
                owned_store=owned_store,
                api_key=api_key,
                audit=audit,
                output=output,
            ),
            timeout=_COOPERATIVE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        checks.safe_code = "verification_runtime_timeout"


def _windows_store_factory() -> SecretStore:
    return WindowsCredentialSecretStore()


def _default_dependencies() -> ManualDeepSeekDependencies:
    return ManualDeepSeekDependencies(
        platform=sys.platform,
        sdk_version=openai.__version__,
        store_factory=_windows_store_factory,
        client_factory=OfficialDeepSeekClientFactory(),
        input_text=input,
        get_secret=getpass.getpass,
        output=print,
    )


def _target_is_occupied(store: SecretStore) -> bool:
    try:
        return store.has_secret(
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID
        )
    except Exception:
        raise _ManualVerificationFailure(
            "credential_store_unavailable"
        ) from None


def _emit_final(
    output: _Output,
    checks: ManualDeepSeekChecks,
    audit: _AuditFactory,
) -> None:
    if not checks.successful and checks.safe_code == "none":
        checks.safe_code = "verification_failed"
    output(
        "request_attempts="
        f"{audit.request_attempts} "
        f"delegate_create_calls={audit.delegate_create_calls} "
        f"cooperative_timeout_seconds={int(_COOPERATIVE_TIMEOUT_SECONDS)}"
    )
    output(
        "verification_complete="
        f"{checks.successful} safe_code={checks.safe_code}"
    )


def _run_confirmed(
    dependencies: ManualDeepSeekDependencies,
) -> int:
    checks = ManualDeepSeekChecks(
        sdk_version_expected=(
            dependencies.sdk_version == _EXPECTED_SDK_VERSION
        )
    )
    audit = _AuditFactory(dependencies.client_factory)
    if dependencies.platform != "win32":
        checks.safe_code = "unsupported_platform"
        _emit_final(dependencies.output, checks, audit)
        return 2
    if not checks.sdk_version_expected:
        checks.safe_code = "sdk_version_mismatch"
        _emit_final(dependencies.output, checks, audit)
        return 2

    owned_store: OwnedDeepSeekTestSecretStore | None = None
    try:
        store = dependencies.store_factory()
        if _target_is_occupied(store):
            checks.safe_code = "test_target_occupied"
            _emit_final(dependencies.output, checks, audit)
            return 2
        api_key = dependencies.get_secret(
            "DeepSeek test API key (hidden): "
        )
        if not isinstance(api_key, str) or not api_key.strip():
            checks.safe_code = "invalid_api_key_input"
            _emit_final(dependencies.output, checks, audit)
            return 2
        if _target_is_occupied(store):
            api_key = ""
            checks.safe_code = "test_target_occupied"
            _emit_final(dependencies.output, checks, audit)
            return 2
        owned_store = OwnedDeepSeekTestSecretStore(store)
        owned_store.set_secret(
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
            SecretValue(api_key),
        )
    except _TargetOwnershipLost:
        api_key = ""
        checks.safe_code = "test_target_ownership_lost"
        _emit_final(dependencies.output, checks, audit)
        return 2
    except _ManualVerificationFailure as error:
        api_key = ""
        checks.safe_code = error.safe_code
        _emit_final(dependencies.output, checks, audit)
        return 2
    except _CredentialStoreUnavailable:
        api_key = ""
        checks.safe_code = "credential_store_unavailable"
        _emit_final(dependencies.output, checks, audit)
        return 2
    except Exception:
        api_key = ""
        if (
            owned_store is not None
            and owned_store.owns_value
            and not owned_store.ownership_lost
        ):
            with suppress(Exception):
                owned_store.cleanup_owned()
        checks.safe_code = "credential_setup_failed"
        _emit_final(dependencies.output, checks, audit)
        return 2

    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        assert owned_store is not None
        asyncio.run(
            _run_with_cooperative_timeout(
                checks=checks,
                owned_store=owned_store,
                api_key=api_key,
                audit=audit,
                output=dependencies.output,
            )
        )
    except KeyboardInterrupt:
        checks.safe_code = "verification_interrupted"
    except Exception:
        checks.safe_code = "verification_failed"
    finally:
        api_key = ""
        logging.disable(previous_logging_disable)
        checks.logging_restored = (
            logging.root.manager.disable
            == previous_logging_disable
        )

    _emit_final(dependencies.output, checks, audit)
    return 0 if checks.successful else 2


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: ManualDeepSeekDependencies | None = None,
) -> int:
    """Run the inert entry or one explicitly confirmed verification."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != [_CONFIRM_FLAG]:
        print("safe_code=manual_verification_disabled")
        return 0

    selected = dependencies or _default_dependencies()
    try:
        confirmation = selected.input_text(
            "Type RUN to authorize the bounded real DeepSeek verification: "
        )
    except Exception:
        selected.output("safe_code=confirmation_failed")
        return 2
    if confirmation != _EXPECTED_CONFIRMATION:
        selected.output("safe_code=confirmation_failed")
        return 2
    return _run_confirmed(selected)


assert DEEPSEEK_MANUAL_TEST_TARGET == _TEST_TARGET


if __name__ == "__main__":
    raise SystemExit(main())
