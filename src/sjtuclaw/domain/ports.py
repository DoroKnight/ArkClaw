"""Ports that keep the Agent core independent from concrete frameworks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Protocol

from sjtuclaw.domain.events import LLMEvent
from sjtuclaw.domain.models import (
    Embedding,
    ExecutionContext,
    LLMRequest,
    MemoryRecord,
    PolicyDecision,
    ProviderCapabilities,
    Reminder,
    ToolCall,
    ToolResult,
    ToolSpec,
)


class LLMProvider(Protocol):
    """Normalize cloud, local, and fake model providers."""

    @property
    def name(self) -> str:
        """Return a stable provider identifier."""

    def capabilities(self) -> ProviderCapabilities:
        """Describe provider features."""

    def generate_stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Generate a normalized stream."""

    async def embed(self, texts: Sequence[str]) -> Sequence[Embedding]:
        """Embed text when supported."""

    async def aclose(self) -> None:
        """Release resources idempotently and respond promptly to cancellation."""


class MemoryRepository(Protocol):
    """Persistence boundary for user-controlled long-term memory."""

    async def save(self, record: MemoryRecord) -> None:
        """Persist a memory record."""

    async def search(self, query: str, limit: int = 5) -> Sequence[MemoryRecord]:
        """Search retrievable memory records."""

    async def update(self, record: MemoryRecord) -> None:
        """Update or supersede a memory record."""

    async def delete(self, memory_id: str) -> None:
        """Permanently remove memory content and derived indexes."""


class Tool(Protocol):
    """A registered local capability."""

    def spec(self) -> ToolSpec:
        """Return the model-visible definition and risk level."""

    async def execute(
        self,
        arguments: dict[str, object],
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute after ToolPolicy approval."""


class ToolPolicy(Protocol):
    """Permission enforcement that is independent from LLM output."""

    def evaluate(
        self,
        spec: ToolSpec,
        call: ToolCall,
        context: ExecutionContext,
    ) -> PolicyDecision:
        """Allow, require approval, or deny a tool call."""


class SchedulerService(Protocol):
    """One-shot reminder scheduling boundary."""

    async def create(self, reminder: Reminder) -> None:
        """Persist and schedule a reminder."""

    async def cancel(self, reminder_id: str) -> None:
        """Cancel a pending reminder."""

    async def reschedule(self, reminder: Reminder) -> None:
        """Replace a reminder's due time."""

    async def recover_pending(self, now: datetime) -> Sequence[Reminder]:
        """Recover reminders after startup or system resume."""
