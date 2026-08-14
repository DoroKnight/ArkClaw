"""Safe, user-facing configuration and secret-store errors."""

from __future__ import annotations

from arkclaw.domain.errors import ArkClawError


class ConfigError(ArkClawError):
    """Raised when a non-sensitive configuration value is invalid."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message

    def __str__(self) -> str:
        return f"Invalid configuration for '{self.field}': {self.message}"


class SecretStoreError(ArkClawError):
    """Base exception for credential-store operations."""


class SecretStoreReadOnlyError(SecretStoreError):
    """Raised when a read-only secret source is asked to persist a value."""


class SecretStoreUnavailableError(SecretStoreError):
    """Raised when the selected credential backend is unavailable."""


class SecretStoreAccessDeniedError(SecretStoreError):
    """Raised when the operating system denies credential access."""


class SecretStoreCorruptedError(SecretStoreError):
    """Raised when persisted credential data cannot be decoded safely."""
