"""Command-line development entry point for the Agent Runtime."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence

from arkclaw.application.agent_loop import AgentLoop
from arkclaw.application.context_manager import ContextConfig, ContextManager
from arkclaw.config.errors import ConfigError, SecretStoreError
from arkclaw.config.loader import ConfigLoader
from arkclaw.config.models import ProviderName, RuntimeConfig
from arkclaw.domain.events import AgentEventType
from arkclaw.domain.models import (
    ChatMessage,
    MessageRole,
    ProviderContinuation,
    UserMessageCommand,
)
from arkclaw.domain.ports import LLMProvider
from arkclaw.infrastructure.llm.provider_factory import (
    ProviderFactory,
    ProviderNotImplementedError,
)

logger = logging.getLogger(__name__)
_PROVIDER_CLOSE_TIMEOUT_SECONDS = 5.0


async def _close_provider_safely(provider: LLMProvider) -> None:
    """Bound provider cleanup and avoid masking the original exit reason."""

    try:
        async with asyncio.timeout(_PROVIDER_CLOSE_TIMEOUT_SECONDS):
            await provider.aclose()
    except TimeoutError:
        logger.error("Provider close timed out: provider=%s", provider.name)
    except Exception as error:
        logger.error(
            "Provider close failed: provider=%s exception_type=%s",
            provider.name,
            type(error).__name__,
        )


async def _run_demo(config: RuntimeConfig) -> None:
    if config.provider in {
        ProviderName.OPENAI,
        ProviderName.DEEPSEEK,
    }:
        from arkclaw.infrastructure.security.windows_credential_store import (
            WindowsCredentialSecretStore,
        )

        provider_factory = ProviderFactory(
            secret_store=WindowsCredentialSecretStore()
        )
    else:
        provider_factory = ProviderFactory()
    provider = provider_factory.create(config)
    try:
        context_manager = ContextManager(
            ContextConfig(max_output_tokens=config.max_output_tokens)
        )
        agent = AgentLoop(
            provider=provider,
            context_manager=context_manager,
            max_turn_seconds=config.max_turn_seconds,
        )
        history: list[ChatMessage] = []
        continuation: ProviderContinuation | None = None

        print(f"ArkClaw Agent Runtime demo ({provider.name} Provider)")
        print("Type /quit to exit.\n")

        while True:
            try:
                user_text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if user_text.lower() in {"/quit", "/exit"}:
                break
            if not user_text:
                continue

            command = UserMessageCommand.create(content=user_text)
            turn_completed = False
            completed_text = ""
            completed_continuation: ProviderContinuation | None = None
            print("Pet: ", end="", flush=True)

            async for event in agent.run(
                command,
                history=history,
                continuation=continuation,
            ):
                if event.type is AgentEventType.TEXT_DELTA:
                    print(event.text, end="", flush=True)
                elif event.type is AgentEventType.TURN_COMPLETED:
                    turn_completed = True
                    completed_text = event.text
                    completed_continuation = event.continuation
                elif event.type is AgentEventType.TURN_FAILED:
                    turn_completed = False
                    print(f"\n[error: {event.error_code}] {event.error_message}")
                elif event.type is AgentEventType.TURN_CANCELLED:
                    turn_completed = False
                    print("\n[cancelled]")

            print()
            if turn_completed:
                continuation = completed_continuation
                if completed_text:
                    history.extend(
                        (
                            ChatMessage(role=MessageRole.USER, content=user_text),
                            ChatMessage(
                                role=MessageRole.ASSISTANT,
                                content=completed_text,
                            ),
                        )
                    )
    finally:
        await _close_provider_safely(provider)


def main(argv: Sequence[str] | None = None) -> int:
    """Load validated configuration and run the temporary CLI demo."""

    cli_args = list(argv) if argv is not None else sys.argv[1:]
    try:
        config = ConfigLoader().load(cli_args=cli_args)
        asyncio.run(_run_demo(config))
    except (ConfigError, ProviderNotImplementedError, SecretStoreError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
