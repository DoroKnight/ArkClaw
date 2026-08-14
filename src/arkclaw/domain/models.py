"""Core data models shared by application services and adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def tool_arguments_digest(arguments: dict[str, Any]) -> str:
    """Return a stable digest for JSON-compatible tool arguments."""

    try:
        normalized = json.dumps(
            arguments,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("tool arguments must be JSON-compatible") from error
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class MessageRole(StrEnum):
    """Roles accepted by the normalized provider request."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentState(StrEnum):
    """Visual/runtime states exposed to the future Qt UI."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    REMINDING = "reminding"


class MemoryKind(StrEnum):
    """Long-term memory categories."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PINNED = "pinned"


class MemoryStatus(StrEnum):
    """Explicit long-term memory lifecycle."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class ToolRisk(StrEnum):
    """Permission levels enforced outside the language model."""

    SAFE = "safe"
    SENSITIVE_READ = "sensitive_read"
    SIDE_EFFECT = "side_effect"
    DESTRUCTIVE = "destructive"


class PolicyOutcome(StrEnum):
    """A tool policy decision."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ApiProtocol(StrEnum):
    """Wire protocols implemented by provider adapters."""

    INTERNAL = "internal"
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"
    OLLAMA_CHAT = "ollama_chat"


class ContinuationMode(StrEnum):
    """How a provider continues a previous turn."""

    NONE = "none"
    REPLAY_MESSAGES = "replay_messages"
    REPLAY_PROVIDER_ITEMS = "replay_provider_items"
    SERVER_REFERENCE = "server_reference"


_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESERVED_PROFILE_IDS = frozenset(
    {
        "builtin-fake-default",
        "builtin-openai-default",
        "builtin-deepseek-default",
        "builtin-ollama-default",
    }
)
_RESERVED_CREDENTIAL_IDS = frozenset(
    {
        "builtin-openai-default",
        "builtin-openai-manual-test",
        "builtin-deepseek-manual-test",
    }
)


@dataclass(frozen=True, slots=True, order=True)
class ProviderId:
    """Validated stable provider registration identifier."""

    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or _PROVIDER_ID_PATTERN.fullmatch(self.value) is None
        ):
            raise ValueError("provider_id has an invalid format")

    def __str__(self) -> str:
        return self.value


def _validate_opaque_id(
    value: str,
    *,
    reserved: frozenset[str],
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError(f"{field_name} has an invalid format")
    if value in reserved:
        return value
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError(f"{field_name} has an invalid format") from None
    if str(parsed) != value or parsed.version != 4:
        raise ValueError(f"{field_name} has an invalid format")
    return value


@dataclass(frozen=True, slots=True, order=True)
class ProfileId:
    """Opaque built-in or application-generated profile identifier."""

    value: str

    def __post_init__(self) -> None:
        _validate_opaque_id(
            self.value,
            reserved=_RESERVED_PROFILE_IDS,
            field_name="profile_id",
        )

    @classmethod
    def new(cls) -> ProfileId:
        return cls(str(uuid4()))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class CredentialId:
    """Opaque identifier resolved to a credential target by infrastructure."""

    value: str

    def __post_init__(self) -> None:
        _validate_opaque_id(
            self.value,
            reserved=_RESERVED_CREDENTIAL_IDS,
            field_name="credential_id",
        )

    @classmethod
    def new(cls) -> CredentialId:
        return cls(str(uuid4()))

    def __str__(self) -> str:
        return self.value


FAKE_PROVIDER_ID = ProviderId("fake")
OPENAI_PROVIDER_ID = ProviderId("openai")
DEEPSEEK_PROVIDER_ID = ProviderId("deepseek")
OLLAMA_PROVIDER_ID = ProviderId("ollama")

FAKE_DEFAULT_PROFILE_ID = ProfileId("builtin-fake-default")
OPENAI_DEFAULT_PROFILE_ID = ProfileId("builtin-openai-default")
DEEPSEEK_DEFAULT_PROFILE_ID = ProfileId("builtin-deepseek-default")
OLLAMA_DEFAULT_PROFILE_ID = ProfileId("builtin-ollama-default")

OPENAI_DEFAULT_CREDENTIAL_ID = CredentialId("builtin-openai-default")
DEEPSEEK_DEFAULT_CREDENTIAL_ID = CredentialId(
    "00000000-0000-4000-8000-000000000001"
)
OPENAI_MANUAL_TEST_CREDENTIAL_ID = CredentialId(
    "builtin-openai-manual-test"
)
DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID = CredentialId(
    "builtin-deepseek-manual-test"
)


def _normalize_https_origin(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("allowed_origin has an invalid format")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("allowed_origin has an invalid format")
    return f"https://{parsed.netloc.lower()}"


@dataclass(frozen=True, slots=True)
class CredentialBinding:
    """Non-sensitive authorization metadata for one credential identifier."""

    credential_id: CredentialId
    provider_id: ProviderId
    allowed_origin: str
    display_name: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.display_name, str)
            or not self.display_name.strip()
            or len(self.display_name) > 128
        ):
            raise ValueError("display_name must be 1 to 128 characters")
        if self.schema_version != 1:
            raise ValueError(
                "unsupported credential binding schema_version"
            )
        object.__setattr__(
            self,
            "allowed_origin",
            _normalize_https_origin(self.allowed_origin),
        )
        object.__setattr__(
            self,
            "display_name",
            self.display_name.strip(),
        )


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A normalized conversation message."""

    role: MessageRole
    content: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("ChatMessage content must not be blank")


@dataclass(frozen=True, slots=True)
class UserMessageCommand:
    """A typed command sent from the future GUI to the Agent Runtime."""

    turn_id: str
    session_id: str
    content: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ValueError("turn_id must not be blank")
        if not self.session_id:
            raise ValueError("session_id must not be blank")
        if not self.content.strip():
            raise ValueError("content must not be blank")

    @classmethod
    def create(cls, content: str, session_id: str = "local-demo") -> UserMessageCommand:
        """Create a command with a unique turn identifier."""

        return cls(turn_id=str(uuid4()), session_id=session_id, content=content)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Capabilities reported by an LLM provider adapter."""

    streaming: bool = True
    tools: bool = False
    embeddings: bool = False
    continuation_mode: ContinuationMode = ContinuationMode.NONE
    protocol: ApiProtocol = ApiProtocol.INTERNAL


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Non-sensitive configuration that binds an adapter to a credential."""

    profile_id: ProfileId
    display_name: str
    provider_id: ProviderId
    protocol: ApiProtocol
    base_url: str | None
    model: str
    credential_id: CredentialId | None
    capabilities: ProviderCapabilities
    enabled: bool = True
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.display_name, str)
            or not self.display_name.strip()
            or len(self.display_name) > 128
        ):
            raise ValueError("display_name must be 1 to 128 characters")
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > 256
        ):
            raise ValueError("model must be 1 to 256 characters")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        if self.schema_version != 1:
            raise ValueError("unsupported provider profile schema_version")
        if self.capabilities.protocol is not self.protocol:
            raise ValueError("profile protocol and capabilities must match")
        if self.base_url is not None:
            if not isinstance(self.base_url, str) or len(self.base_url) > 2048:
                raise ValueError("base_url has an invalid format")
            normalized_url = self.base_url.strip().rstrip("/")
            parsed = urlsplit(normalized_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("base_url has an invalid format")
            object.__setattr__(self, "base_url", normalized_url)
        object.__setattr__(self, "display_name", self.display_name.strip())
        object.__setattr__(self, "model", self.model.strip())

    @property
    def origin(self) -> str | None:
        """Return the normalized network origin without path information."""

        if self.base_url is None:
            return None
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


@dataclass(frozen=True, slots=True)
class Embedding:
    """A provider-independent embedding vector."""

    values: tuple[float, ...]
    model: str


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool definition visible to the language model."""

    name: str
    description: str
    input_schema: dict[str, Any]
    risk: ToolRisk


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A normalized tool call emitted by a provider."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A bounded observation returned to the Agent Loop."""

    call_id: str
    success: bool
    content: str
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Tool permission result produced outside the language model."""

    outcome: PolicyOutcome
    reason: str
    allow_for_session: bool = False


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Immutable proof that a user approved one exact tool call."""

    turn_id: str
    call_id: str
    tool_name: str
    arguments_digest: str
    expires_at: datetime
    consumed: bool = False

    def __post_init__(self) -> None:
        if not self.turn_id or not self.call_id or not self.tool_name:
            raise ValueError("approval identifiers must not be blank")
        if not self.arguments_digest:
            raise ValueError("arguments_digest must not be blank")
        if self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")

    @classmethod
    def for_call(
        cls,
        *,
        turn_id: str,
        call: ToolCall,
        expires_at: datetime,
    ) -> ApprovalRecord:
        """Create an approval bound to the current normalized call."""

        return cls(
            turn_id=turn_id,
            call_id=call.call_id,
            tool_name=call.name,
            arguments_digest=tool_arguments_digest(call.arguments),
            expires_at=expires_at,
        )

    def matches(
        self,
        *,
        turn_id: str,
        call: ToolCall,
        now: datetime | None = None,
    ) -> bool:
        """Return whether this unconsumed approval authorizes ``call`` now."""

        checked_at = now or utc_now()
        if checked_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if self.consumed or checked_at >= self.expires_at:
            return False
        if (
            self.turn_id != turn_id
            or self.call_id != call.call_id
            or self.tool_name != call.name
        ):
            return False
        try:
            return self.arguments_digest == tool_arguments_digest(call.arguments)
        except ValueError:
            return False

    def consume(self) -> ApprovalRecord:
        """Return a consumed copy that cannot authorize another execution."""

        return replace(self, consumed=True)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Trusted context passed to a tool implementation.

    ``approved`` remains only for constructor compatibility and is never
    authorization evidence. New callers must provide a bound ``approval``.
    """

    turn_id: str
    session_id: str
    approved: bool = False
    approval: ApprovalRecord | None = None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """Low-trust memory data carried separately from system instructions."""

    memory_id: str
    kind: MemoryKind
    content: str
    status: MemoryStatus
    source_session_id: str
    boundary: str = "untrusted_memory_data"

    @classmethod
    def from_record(cls, record: MemoryRecord) -> MemoryContext:
        """Copy provenance and lifecycle data into the provider request."""

        return cls(
            memory_id=record.id,
            kind=record.kind,
            content=record.content,
            status=record.status,
            source_session_id=record.source_session_id,
        )


@dataclass(frozen=True, slots=True)
class ProviderContinuation:
    """Opaque in-memory state that is meaningful only to its provider."""

    provider_name: str
    state: bytes = field(repr=False)
    version: str | None = None
    profile_id: ProfileId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_name, str) or not self.provider_name.strip():
            raise ValueError("provider_name must not be blank")
        if not isinstance(self.state, bytes):
            raise TypeError("state must be bytes")
        if self.version is not None and (
            not isinstance(self.version, str) or not self.version.strip()
        ):
            raise ValueError("version must be None or a non-blank string")
        if self.profile_id is not None and not isinstance(
            self.profile_id,
            ProfileId,
        ):
            raise TypeError("profile_id must be None or a ProfileId")
        object.__setattr__(self, "provider_name", self.provider_name.strip())
        if self.version is not None:
            object.__setattr__(self, "version", self.version.strip())

    def __repr__(self) -> str:
        return "<ProviderContinuation redacted>"


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Provider-independent request consumed by ``LLMProvider``."""

    instructions: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...] = ()
    store: bool = False
    max_output_tokens: int = 1024
    memory_context: tuple[MemoryContext, ...] = ()
    continuation: ProviderContinuation | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A user-controlled long-term memory record."""

    id: str
    kind: MemoryKind
    content: str
    status: MemoryStatus
    source_session_id: str
    pinned: bool = False
    importance: float = 0.5
    confidence: float = 1.0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def is_retrievable(self) -> bool:
        """Return whether this record may enter LLM context."""

        return self.status is MemoryStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class Reminder:
    """A persisted one-shot reminder domain object."""

    id: str
    title: str
    due_at_utc: datetime
    timezone: str
    status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


def immutable_mapping(values: dict[str, Any] | None = None) -> MappingProxyType[str, Any]:
    """Return a read-only mapping for event metadata."""

    return MappingProxyType(dict(values or {}))
