"""Build small, deterministic provider requests for the Agent Loop."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arkclaw.config.defaults import DEFAULT_SYSTEM_PROMPT
from arkclaw.domain.errors import ContextBudgetError
from arkclaw.domain.models import (
    ChatMessage,
    LLMRequest,
    MemoryContext,
    MemoryRecord,
    MessageRole,
    ProviderContinuation,
    ToolSpec,
    UserMessageCommand,
)


@dataclass(frozen=True, slots=True)
class ContextConfig:
    """Simple character-based limits used before provider tokenizers exist."""

    max_recent_messages: int = 12
    max_memories: int = 5
    max_context_chars: int = 24_000
    max_output_tokens: int = 1024

    def __post_init__(self) -> None:
        if self.max_recent_messages < 0:
            raise ValueError("max_recent_messages must not be negative")
        if self.max_memories < 0:
            raise ValueError("max_memories must not be negative")
        if self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")


class ContextManager:
    """Select recent conversation and confirmed memory without token coupling."""

    def __init__(
        self,
        config: ContextConfig | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self._config = config or ContextConfig()
        self._system_prompt = system_prompt.strip()

    def build_request(
        self,
        command: UserMessageCommand,
        *,
        history: Sequence[ChatMessage] = (),
        memories: Sequence[MemoryRecord] = (),
        tools: Sequence[ToolSpec] = (),
        continuation: ProviderContinuation | None = None,
    ) -> LLMRequest:
        """Build a bounded request.

        Candidate, superseded, and deleted memory is deliberately excluded.
        The latest user message and system safety rules are never silently
        truncated. If those mandatory fields alone exceed the budget, the turn
        fails with ``ContextBudgetError``.
        """

        selected_history = (
            list(history[-self._config.max_recent_messages :])
            if self._config.max_recent_messages
            else []
        )
        selected_memories = sorted(
            (memory for memory in memories if memory.is_retrievable),
            key=lambda memory: (memory.pinned, memory.updated_at),
            reverse=True,
        )[: self._config.max_memories]
        user_message = ChatMessage(role=MessageRole.USER, content=command.content)

        instructions = self._render_instructions()
        messages = [*selected_history, user_message]

        while selected_history and self._context_size(
            instructions, messages, selected_memories
        ) > self._config.max_context_chars:
            selected_history.pop(0)
            messages = [*selected_history, user_message]

        while selected_memories and self._context_size(
            instructions, messages, selected_memories
        ) > self._config.max_context_chars:
            selected_memories.pop()

        if (
            self._context_size(instructions, messages, selected_memories)
            > self._config.max_context_chars
        ):
            raise ContextBudgetError(
                "The system instructions and current user message exceed the context budget."
            )

        return LLMRequest(
            instructions=instructions,
            messages=tuple(messages),
            memory_context=tuple(
                MemoryContext.from_record(memory) for memory in selected_memories
            ),
            tools=tuple(tools),
            store=False,
            max_output_tokens=self._config.max_output_tokens,
            continuation=continuation,
        )

    def _render_instructions(self) -> str:
        return self._system_prompt

    @staticmethod
    def _context_size(
        instructions: str,
        messages: Sequence[ChatMessage],
        memories: Sequence[MemoryRecord],
    ) -> int:
        return (
            len(instructions)
            + sum(len(message.content) for message in messages)
            + sum(len(memory.content) for memory in memories)
        )
