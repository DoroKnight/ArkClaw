"""Domain and application error types."""


class ArkClawError(Exception):
    """Base exception for expected ArkClaw failures."""


class ContextBudgetError(ArkClawError):
    """Raised when mandatory context cannot fit in the configured budget."""


class ProviderError(ArkClawError):
    """Raised when an LLM provider cannot complete a request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderCapabilityError(ProviderError):
    """Raised when a provider does not support a requested capability."""


class InvalidProviderEventError(ProviderError):
    """Raised when a provider emits an invalid event sequence."""
