"""Immutable, validated runtime configuration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from sjtuclaw.config.defaults import (
    DEFAULT_DEEPSEEK_MAX_RETRIES,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MAX_TURN_SECONDS,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MAX_RETRIES,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_STREAM,
)
from sjtuclaw.config.errors import ConfigError


class ProviderName(StrEnum):
    """Providers recognized by configuration and ProviderFactory."""

    FAKE = "fake"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """A read-only snapshot of all non-sensitive runtime settings."""

    provider: ProviderName = ProviderName.FAKE
    openai_model: str = DEFAULT_OPENAI_MODEL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    provider_timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS
    openai_max_retries: int = DEFAULT_OPENAI_MAX_RETRIES
    deepseek_max_retries: int = DEFAULT_DEEPSEEK_MAX_RETRIES
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    stream: bool = DEFAULT_STREAM
    max_turn_seconds: float = DEFAULT_MAX_TURN_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderName):
            raise ConfigError("provider", "must be a ProviderName value")
        self._normalize_non_empty("openai_model")
        self._normalize_non_empty("deepseek_model")
        self._normalize_non_empty("ollama_model")

        if isinstance(self.provider_timeout_seconds, bool) or not isinstance(
            self.provider_timeout_seconds, (int, float)
        ):
            raise ConfigError("provider_timeout_seconds", "must be a number")
        if not math.isfinite(self.provider_timeout_seconds) or self.provider_timeout_seconds <= 0:
            raise ConfigError("provider_timeout_seconds", "must be greater than zero")
        if isinstance(self.max_turn_seconds, bool) or not isinstance(
            self.max_turn_seconds, (int, float)
        ):
            raise ConfigError("max_turn_seconds", "must be a number")
        if not math.isfinite(self.max_turn_seconds) or self.max_turn_seconds <= 0:
            raise ConfigError("max_turn_seconds", "must be greater than zero")

        if isinstance(self.openai_max_retries, bool) or not isinstance(
            self.openai_max_retries, int
        ):
            raise ConfigError("openai_max_retries", "must be an integer")
        if self.openai_max_retries < 0:
            raise ConfigError("openai_max_retries", "must not be negative")
        if isinstance(self.deepseek_max_retries, bool) or not isinstance(
            self.deepseek_max_retries, int
        ):
            raise ConfigError(
                "deepseek_max_retries",
                "must be an integer",
            )
        if self.deepseek_max_retries < 0:
            raise ConfigError(
                "deepseek_max_retries",
                "must not be negative",
            )

        if isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int):
            raise ConfigError("max_output_tokens", "must be an integer")
        if self.max_output_tokens <= 0:
            raise ConfigError("max_output_tokens", "must be greater than zero")
        if not isinstance(self.stream, bool):
            raise ConfigError("stream", "must be a boolean")
        if not isinstance(self.ollama_base_url, str):
            raise ConfigError("ollama_base_url", "must be a string")

        normalized_url = self.ollama_base_url.strip().rstrip("/")
        parsed_url = urlsplit(normalized_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ConfigError(
                "ollama_base_url",
                "must be an HTTP/HTTPS URL without embedded credentials",
            )
        object.__setattr__(self, "ollama_base_url", normalized_url)

    def _normalize_non_empty(self, field_name: str) -> None:
        value = getattr(self, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(field_name, "must not be blank")
        object.__setattr__(self, field_name, value.strip())

    def to_dict(self) -> dict[str, Any]:
        """Serialize only non-sensitive settings."""

        return {
            "provider": self.provider.value,
            "openai_model": self.openai_model,
            "deepseek_model": self.deepseek_model,
            "ollama_model": self.ollama_model,
            "provider_timeout_seconds": self.provider_timeout_seconds,
            "openai_max_retries": self.openai_max_retries,
            "deepseek_max_retries": self.deepseek_max_retries,
            "ollama_base_url": self.ollama_base_url,
            "max_output_tokens": self.max_output_tokens,
            "stream": self.stream,
            "max_turn_seconds": self.max_turn_seconds,
        }
