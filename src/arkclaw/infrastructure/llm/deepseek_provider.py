"""DeepSeek provider using an independent Chat Completions boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import AsyncIterator, Sequence

from arkclaw.config.errors import SecretStoreError
from arkclaw.config.provider_profiles import DEEPSEEK_OFFICIAL_BASE_URL
from arkclaw.config.secrets import SecretStore
from arkclaw.domain.errors import ProviderCapabilityError
from arkclaw.domain.events import LLMEvent
from arkclaw.domain.models import (
    ApiProtocol,
    ChatMessage,
    ContinuationMode,
    Embedding,
    LLMRequest,
    MemoryContext,
    MessageRole,
    ProviderCapabilities,
    ProviderContinuation,
    ProviderProfile,
)
from arkclaw.infrastructure.llm.deepseek_sdk import (
    ChatMessageData,
    DeepSeekClient,
    DeepSeekClientFactory,
    DeepSeekEventKind,
    DeepSeekRequest,
    DeepSeekSDKError,
    DeepSeekStream,
    OfficialDeepSeekClientFactory,
)
from arkclaw.infrastructure.llm.provider_registry import (
    restrict_capabilities,
)

_ADAPTER_VERSION = "1"
DEEPSEEK_MAXIMUM_CAPABILITIES = ProviderCapabilities(
    streaming=True,
    tools=False,
    embeddings=False,
    continuation_mode=ContinuationMode.REPLAY_MESSAGES,
    protocol=ApiProtocol.CHAT_COMPLETIONS,
)
_ERROR_MESSAGES = {
    "missing_api_key": "No DeepSeek API key is available.",
    "credential_unavailable": "The DeepSeek credential could not be read safely.",
    "invalid_api_key": "The DeepSeek API key was rejected.",
    "permission_denied": "DeepSeek denied access to the requested operation.",
    "request_timeout": "The DeepSeek request timed out.",
    "network_unavailable": "The DeepSeek service could not be reached.",
    "rate_limited": "DeepSeek rate-limited the request.",
    "model_not_found": "The configured DeepSeek model is unavailable.",
    "invalid_request": "DeepSeek rejected the request parameters.",
    "provider_unavailable": "The DeepSeek service is unavailable.",
    "invalid_response": "DeepSeek returned an invalid response stream.",
    "provider_closed": "The provider has already been closed.",
    "invalid_continuation": "The DeepSeek continuation state is invalid.",
    "unsupported_capability": "The request uses an unsupported DeepSeek capability.",
    "output_budget_exhausted": "The DeepSeek response exhausted its output budget.",
    "content_filtered": "DeepSeek filtered the requested response.",
}


class DeepSeekProvider:
    """Text-only DeepSeek Chat Completions provider."""

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        secret_store: SecretStore | None,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
        client_factory: DeepSeekClientFactory | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        if (
            profile.provider_id.value != "deepseek"
            or profile.protocol is not ApiProtocol.CHAT_COMPLETIONS
            or profile.base_url != DEEPSEEK_OFFICIAL_BASE_URL
            or profile.credential_id is None
        ):
            raise ValueError("invalid built-in DeepSeek profile")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite positive number")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if not isinstance(stream, bool):
            raise ValueError("stream must be a boolean")
        effective_capabilities = restrict_capabilities(
            DEEPSEEK_MAXIMUM_CAPABILITIES,
            capabilities or profile.capabilities,
        )

        self._profile = profile
        self._capabilities = effective_capabilities
        self._secret_store = secret_store
        self._timeout_seconds = float(timeout_seconds)
        self._max_retries = max_retries
        self._stream_enabled = stream
        self._client_factory = (
            client_factory or OfficialDeepSeekClientFactory()
        )
        self._client: DeepSeekClient | None = None
        self._credential_fingerprint: bytes | None = None
        self._active_streams: dict[int, DeepSeekStream] = {}
        self._pending_streams: dict[int, DeepSeekStream] = {}
        self._pending_clients: dict[int, DeepSeekClient] = {}
        self._closing_streams: dict[int, DeepSeekStream] = {}
        self._closing_clients: dict[int, DeepSeekClient] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._closed = False

    @property
    def name(self) -> str:
        return "deepseek"

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def active_stream_count(self) -> int:
        return (
            len(self._active_streams)
            + len(self._pending_streams)
            + len(self._closing_streams)
        )

    def __repr__(self) -> str:
        return (
            "<DeepSeekProvider "
            f"profile_id={self._profile.profile_id.value!r} "
            f"model={self._profile.model!r} closed={self._closed!r} "
            "credential=<redacted>>"
        )

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def generate_stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[LLMEvent]:
        preflight_error = _preflight_error(
            request,
            self._profile,
            self._capabilities,
        )
        if preflight_error is not None:
            yield _failure(preflight_error)
            return
        if not self._stream_enabled:
            yield _failure("unsupported_capability")
            return

        failure_code: str | None = None
        terminal_kind: DeepSeekEventKind | None = None
        text_seen = False
        stream: DeepSeekStream | None = None
        registered = False

        try:
            async with self._lifecycle_lock:
                client, failure_code = await self._client_locked()
                if client is not None and failure_code is None:
                    sdk_request = _prepare_request(
                        request,
                        model=self._profile.model,
                    )
                    stream = await client.create(sdk_request)
                    registration_error = await self._register_stream(
                        client,
                        stream,
                    )
                    if registration_error is not None:
                        failure_code = registration_error
                    else:
                        registered = True

            if stream is not None and failure_code is None:
                async for event in stream:
                    if event.kind is DeepSeekEventKind.METADATA:
                        continue
                    if terminal_kind is not None:
                        failure_code = "invalid_response"
                        break
                    if event.kind is DeepSeekEventKind.TEXT_DELTA:
                        if event.text:
                            text_seen = True
                            yield LLMEvent.text_delta(event.text)
                        continue
                    if event.kind is DeepSeekEventKind.COMPLETED:
                        terminal_kind = event.kind
                        continue
                    if event.kind is DeepSeekEventKind.FAILED:
                        terminal_kind = event.kind
                        failure_code = (
                            event.failure_code
                            or "provider_unavailable"
                        )
                        continue
                    failure_code = "invalid_response"
                    break
        except asyncio.CancelledError:
            raise
        except DeepSeekSDKError as error:
            failure_code = _known_error_code(error.code)
        except Exception:
            failure_code = "provider_unavailable"
        finally:
            if stream is not None and not await self._retire_stream(
                stream,
                registered=registered,
            ):
                failure_code = failure_code or "provider_unavailable"

        if failure_code is not None:
            yield _failure(failure_code)
            return
        if (
            terminal_kind is not DeepSeekEventKind.COMPLETED
            or not text_seen
        ):
            yield _failure("invalid_response")
            return
        continuation = None
        if (
            self._capabilities.continuation_mode
            is ContinuationMode.REPLAY_MESSAGES
        ):
            continuation = _continuation(self._profile)
        yield LLMEvent.completed(continuation)

    async def embed(self, texts: Sequence[str]) -> Sequence[Embedding]:
        del texts
        raise ProviderCapabilityError(
            "unsupported_capability",
            "DeepSeek embeddings are not supported in this milestone."
        )

    async def aclose(self) -> None:
        async with self._lifecycle_lock:
            async with self._state_lock:
                if (
                    self._closed
                    and self._client is None
                    and not self._active_streams
                    and not self._pending_streams
                    and not self._pending_clients
                    and not self._closing_streams
                    and not self._closing_clients
                ):
                    return
                self._closed = True
                self._secret_store = None
                self._isolate_current_resources()
            await self._retry_pending_cleanup_locked()

    async def _client_locked(
        self,
    ) -> tuple[DeepSeekClient | None, str | None]:
        if not await self._retry_pending_cleanup_locked():
            return None, "provider_unavailable"
        if self._secret_store is None:
            await self._invalidate_client_locked()
            return None, "missing_api_key"
        credential_id = self._profile.credential_id
        if credential_id is None:
            return None, "missing_api_key"
        try:
            secret = self._secret_store.get_secret(credential_id)
        except SecretStoreError:
            await self._invalidate_client_locked()
            return None, "credential_unavailable"
        except Exception:
            await self._invalidate_client_locked()
            return None, "credential_unavailable"
        if secret is None:
            await self._invalidate_client_locked()
            return None, "missing_api_key"
        try:
            api_key = secret.reveal()
            fingerprint = hashlib.sha256(
                api_key.encode("utf-8")
            ).digest()
        except Exception:
            await self._invalidate_client_locked()
            return None, "credential_unavailable"

        async with self._state_lock:
            if self._closed:
                return None, "provider_closed"
            if (
                self._client is not None
                and self._credential_fingerprint == fingerprint
            ):
                return self._client, None
            self._isolate_current_resources()
        if not await self._invalidate_client_locked():
            return None, "provider_unavailable"
        try:
            client = self._client_factory.create(
                api_key=api_key,
                timeout_seconds=self._timeout_seconds,
                max_retries=self._max_retries,
            )
        except Exception:
            return None, "provider_unavailable"
        finally:
            api_key = ""
        async with self._state_lock:
            if self._closed:
                self._pending_clients[id(client)] = client
                client = None
            else:
                self._client = client
                self._credential_fingerprint = fingerprint
        if client is None:
            await self._retry_pending_cleanup_locked()
            return None, "provider_closed"
        return client, None

    async def _invalidate_client_locked(self) -> bool:
        async with self._state_lock:
            self._isolate_current_resources()
        return await self._retry_pending_cleanup_locked()

    def _isolate_current_resources(self) -> None:
        if self._client is not None:
            self._pending_clients[id(self._client)] = self._client
        for stream in self._active_streams.values():
            self._pending_streams[id(stream)] = stream
        self._client = None
        self._credential_fingerprint = None
        self._active_streams.clear()

    async def _register_stream(
        self,
        client: DeepSeekClient,
        stream: DeepSeekStream,
    ) -> str | None:
        async with self._state_lock:
            if self._closed:
                return "provider_closed"
            if client is not self._client:
                return "provider_unavailable"
            self._active_streams[id(stream)] = stream
            return None

    async def _retire_stream(
        self,
        stream: DeepSeekStream,
        *,
        registered: bool,
    ) -> bool:
        async with self._state_lock:
            if registered:
                self._active_streams.pop(id(stream), None)
            self._pending_streams[id(stream)] = stream
        async with self._lifecycle_lock:
            return await self._close_pending_stream_locked(stream)

    async def _close_pending_stream_locked(
        self,
        stream: DeepSeekStream,
    ) -> bool:
        async with self._state_lock:
            resource_id = id(stream)
            if (
                resource_id not in self._pending_streams
                and resource_id not in self._closing_streams
            ):
                return True
            self._pending_streams.pop(resource_id, None)
            self._closing_streams[resource_id] = stream
        try:
            await stream.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._state_lock:
                self._closing_streams.pop(resource_id, None)
                self._pending_streams[resource_id] = stream
            return False
        async with self._state_lock:
            self._pending_streams.pop(resource_id, None)
            self._closing_streams.pop(resource_id, None)
        return True

    async def _close_pending_client_locked(
        self,
        client: DeepSeekClient,
    ) -> bool:
        async with self._state_lock:
            resource_id = id(client)
            if (
                resource_id not in self._pending_clients
                and resource_id not in self._closing_clients
            ):
                return True
            self._pending_clients.pop(resource_id, None)
            self._closing_clients[resource_id] = client
        try:
            await client.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._state_lock:
                self._closing_clients.pop(resource_id, None)
                self._pending_clients[resource_id] = client
            return False
        async with self._state_lock:
            self._pending_clients.pop(resource_id, None)
            self._closing_clients.pop(resource_id, None)
        return True

    async def _retry_pending_cleanup_locked(self) -> bool:
        async with self._state_lock:
            streams = {
                **self._closing_streams,
                **self._pending_streams,
            }
            clients = {
                **self._closing_clients,
                **self._pending_clients,
            }
        succeeded = True
        for stream in tuple(streams.values()):
            if not await self._close_pending_stream_locked(stream):
                succeeded = False
        async with self._state_lock:
            streams_remain = bool(
                self._pending_streams or self._closing_streams
            )
        if streams_remain:
            return False
        for client in tuple(clients.values()):
            if not await self._close_pending_client_locked(client):
                succeeded = False
        async with self._state_lock:
            clients_remain = bool(
                self._pending_clients or self._closing_clients
            )
        return succeeded and not clients_remain


def _prepare_request(
    request: LLMRequest,
    *,
    model: str,
) -> DeepSeekRequest:
    messages: list[ChatMessageData] = []
    if request.instructions.strip():
        messages.append(
            {"role": "system", "content": request.instructions}
        )
    messages.extend(_memory_messages(request.memory_context))
    messages.extend(_chat_messages(request.messages))
    return DeepSeekRequest(
        model=model,
        messages=tuple(messages),
        max_tokens=request.max_output_tokens,
        stream=True,
    )


def _chat_messages(
    messages: tuple[ChatMessage, ...],
) -> list[ChatMessageData]:
    return [
        {"role": message.role.value, "content": message.content}
        for message in messages
    ]


def _memory_messages(
    memories: tuple[MemoryContext, ...],
) -> list[ChatMessageData]:
    return [
        {
            "role": "user",
            "content": (
                "[untrusted_memory_data]\n"
                f"source={memory.source_session_id}\n"
                f"content={memory.content}"
            ),
        }
        for memory in memories
    ]


def _preflight_error(
    request: LLMRequest,
    profile: ProviderProfile,
    capabilities: ProviderCapabilities,
) -> str | None:
    if (
        request.tools
        and not capabilities.tools
    ) or any(
        message.role is MessageRole.TOOL for message in request.messages
    ):
        return "unsupported_capability"
    continuation = request.continuation
    if continuation is None:
        return None
    if capabilities.continuation_mode is ContinuationMode.NONE:
        return "unsupported_capability"
    if (
        continuation.provider_name != "deepseek"
        or continuation.version != _ADAPTER_VERSION
    ):
        return "invalid_continuation"
    try:
        raw = json.loads(continuation.state.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_continuation"
    if not isinstance(raw, dict) or set(raw) != {
        "adapter_version",
        "profile_id",
        "protocol",
    }:
        return "invalid_continuation"
    if raw != {
        "adapter_version": _ADAPTER_VERSION,
        "profile_id": profile.profile_id.value,
        "protocol": profile.protocol.value,
    }:
        return "invalid_continuation"
    return None


def _continuation(profile: ProviderProfile) -> ProviderContinuation:
    state = json.dumps(
        {
            "adapter_version": _ADAPTER_VERSION,
            "profile_id": profile.profile_id.value,
            "protocol": profile.protocol.value,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ProviderContinuation(
        provider_name="deepseek",
        state=state,
        version=_ADAPTER_VERSION,
    )


def _known_error_code(code: str) -> str:
    return code if code in _ERROR_MESSAGES else "provider_unavailable"


def _failure(code: str) -> LLMEvent:
    safe_code = _known_error_code(code)
    return LLMEvent.failure(safe_code, _ERROR_MESSAGES[safe_code])
