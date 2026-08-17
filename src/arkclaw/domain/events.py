"""Normalized provider and Agent Runtime events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from arkclaw.domain.models import (
    AgentState,
    ProviderContinuation,
    ToolCall,
    immutable_mapping,
)


class LLMEventType(StrEnum):
    """Events emitted by an ``LLMProvider``."""

    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LLMEvent:
    """One normalized event in a provider stream."""

    type: LLMEventType
    text: str = ""
    tool_call: ToolCall | None = None
    error_code: str = ""
    error_message: str = ""
    continuation: ProviderContinuation | None = field(default=None, repr=False)

    @classmethod
    def text_delta(cls, text: str) -> LLMEvent:
        if not text:
            raise ValueError("text delta must not be empty")
        return cls(type=LLMEventType.TEXT_DELTA, text=text)

    @classmethod
    def call_tool(cls, tool_call: ToolCall) -> LLMEvent:
        return cls(type=LLMEventType.TOOL_CALL, tool_call=tool_call)

    @classmethod
    def completed(cls, continuation: ProviderContinuation | None = None) -> LLMEvent:
        return cls(type=LLMEventType.COMPLETED, continuation=continuation)

    @classmethod
    def failure(cls, code: str, message: str) -> LLMEvent:
        if not code or not message:
            raise ValueError("provider failure requires code and message")
        return cls(type=LLMEventType.ERROR, error_code=code, error_message=message)


class AgentEventType(StrEnum):
    """Events sent from the Agent Runtime to the future GUI."""

    TURN_STARTED = "turn_started"
    STATE_CHANGED = "state_changed"
    TEXT_DELTA = "text_delta"
    APPROVAL_REQUIRED = "approval_required"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    TURN_COMPLETED = "turn_completed"
    TURN_CANCELLED = "turn_cancelled"
    TURN_FAILED = "turn_failed"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """A typed event emitted by ``AgentLoop``."""

    type: AgentEventType
    turn_id: str
    state: AgentState | None = None
    text: str = ""
    tool_call: ToolCall | None = None
    error_code: str = ""
    error_message: str = ""
    metadata: MappingProxyType[str, Any] = field(default_factory=immutable_mapping)
    continuation: ProviderContinuation | None = field(default=None, repr=False)

    @classmethod
    def started(cls, turn_id: str) -> AgentEvent:
        return cls(type=AgentEventType.TURN_STARTED, turn_id=turn_id)

    @classmethod
    def state_changed(cls, turn_id: str, state: AgentState) -> AgentEvent:
        return cls(type=AgentEventType.STATE_CHANGED, turn_id=turn_id, state=state)

    @classmethod
    def delta(cls, turn_id: str, text: str) -> AgentEvent:
        return cls(type=AgentEventType.TEXT_DELTA, turn_id=turn_id, text=text)

    @classmethod
    def completed(
        cls,
        turn_id: str,
        text: str,
        continuation: ProviderContinuation | None = None,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TURN_COMPLETED,
            turn_id=turn_id,
            text=text,
            continuation=continuation,
        )

    @classmethod
    def cancelled(cls, turn_id: str) -> AgentEvent:
        return cls(type=AgentEventType.TURN_CANCELLED, turn_id=turn_id)

    @classmethod
    def tool_started(cls, turn_id: str, tool_call: ToolCall) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_STARTED,
            turn_id=turn_id,
            tool_call=tool_call,
        )

    @classmethod
    def tool_finished(
        cls,
        turn_id: str,
        tool_call: ToolCall,
        text: str = "",
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_FINISHED,
            turn_id=turn_id,
            tool_call=tool_call,
            text=text,
        )

    @classmethod
    def approval_required(cls, turn_id: str, tool_call: ToolCall) -> AgentEvent:
        return cls(
            type=AgentEventType.APPROVAL_REQUIRED,
            turn_id=turn_id,
            tool_call=tool_call,
        )

    @classmethod
    def failed(cls, turn_id: str, code: str, message: str) -> AgentEvent:
        return cls(
            type=AgentEventType.TURN_FAILED,
            turn_id=turn_id,
            error_code=code,
            error_message=message,
        )
