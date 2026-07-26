"""Merge defaults, application settings, environment, and CLI arguments."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from typing import ClassVar, Never

from sjtuclaw.config.errors import ConfigError
from sjtuclaw.config.models import ProviderName, RuntimeConfig


class _ConfigArgumentParser(argparse.ArgumentParser):
    """Convert argparse failures into testable configuration errors."""

    def error(self, message: str) -> Never:
        raise ConfigError("cli", message)


class ConfigLoader:
    """Build an immutable RuntimeConfig with deterministic precedence."""

    _environment_fields: ClassVar[dict[str, str]] = {
        "SJTUCLAW_PROVIDER": "provider",
        "SJTUCLAW_OPENAI_MODEL": "openai_model",
        "SJTUCLAW_DEEPSEEK_MODEL": "deepseek_model",
        "SJTUCLAW_OLLAMA_MODEL": "ollama_model",
        "SJTUCLAW_PROVIDER_TIMEOUT_SECONDS": "provider_timeout_seconds",
        "SJTUCLAW_MAX_TURN_SECONDS": "max_turn_seconds",
        "SJTUCLAW_OPENAI_MAX_RETRIES": "openai_max_retries",
        "SJTUCLAW_DEEPSEEK_MAX_RETRIES": "deepseek_max_retries",
        "SJTUCLAW_OLLAMA_BASE_URL": "ollama_base_url",
        "SJTUCLAW_MAX_OUTPUT_TOKENS": "max_output_tokens",
        "SJTUCLAW_STREAM": "stream",
    }

    _fields: ClassVar[frozenset[str]] = frozenset(RuntimeConfig().to_dict())

    def load(
        self,
        *,
        app_settings: Mapping[str, object] | None = None,
        environ: Mapping[str, str] | None = None,
        cli_args: Sequence[str] = (),
    ) -> RuntimeConfig:
        """Merge and validate all non-sensitive configuration sources.

        Precedence, from highest to lowest, is CLI, environment, application
        settings, and program defaults.
        """

        merged: dict[str, object] = RuntimeConfig().to_dict()
        merged.update(self._extract_app_settings(app_settings or {}))
        merged.update(self._extract_environment(os.environ if environ is None else environ))
        merged.update(self._parse_cli(cli_args))
        return self._build_config(merged)

    def build_parser(self) -> argparse.ArgumentParser:
        """Create the CLI parser used by both ConfigLoader and the entry point."""

        parser = _ConfigArgumentParser(
            prog="sjtuclaw-agent-demo",
            description="Run the SJTUClaw Agent Runtime development demo.",
        )
        parser.add_argument(
            "--provider",
            metavar="{fake,openai,deepseek,ollama}",
        )
        parser.add_argument("--openai-model")
        parser.add_argument("--deepseek-model")
        parser.add_argument("--ollama-model")
        parser.add_argument("--provider-timeout-seconds")
        parser.add_argument("--max-turn-seconds")
        parser.add_argument("--openai-max-retries")
        parser.add_argument("--deepseek-max-retries")
        parser.add_argument("--ollama-base-url")
        parser.add_argument("--max-output-tokens")
        parser.add_argument(
            "--stream",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Enable or disable provider streaming.",
        )
        return parser

    def _extract_app_settings(self, settings: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in settings.items() if key in self._fields}

    def _extract_environment(self, environ: Mapping[str, str]) -> dict[str, object]:
        return {
            field: environ[variable]
            for variable, field in self._environment_fields.items()
            if variable in environ
        }

    def _parse_cli(self, cli_args: Sequence[str]) -> dict[str, object]:
        namespace = self.build_parser().parse_args(list(cli_args))
        return {
            key: value
            for key, value in vars(namespace).items()
            if key in self._fields and value is not None
        }

    def _build_config(self, values: Mapping[str, object]) -> RuntimeConfig:
        return RuntimeConfig(
            provider=self._provider(values["provider"]),
            openai_model=self._string(values["openai_model"], "openai_model"),
            deepseek_model=self._string(
                values["deepseek_model"],
                "deepseek_model",
            ),
            ollama_model=self._string(values["ollama_model"], "ollama_model"),
            provider_timeout_seconds=self._positive_float(
                values["provider_timeout_seconds"],
                "provider_timeout_seconds",
            ),
            max_turn_seconds=self._positive_float(
                values["max_turn_seconds"],
                "max_turn_seconds",
            ),
            openai_max_retries=self._integer(
                values["openai_max_retries"],
                "openai_max_retries",
            ),
            deepseek_max_retries=self._integer(
                values["deepseek_max_retries"],
                "deepseek_max_retries",
            ),
            ollama_base_url=self._string(values["ollama_base_url"], "ollama_base_url"),
            max_output_tokens=self._integer(
                values["max_output_tokens"],
                "max_output_tokens",
            ),
            stream=self._boolean(values["stream"], "stream"),
        )

    @staticmethod
    def _provider(value: object) -> ProviderName:
        if isinstance(value, ProviderName):
            return value
        try:
            return ProviderName(str(value).strip().lower())
        except ValueError as error:
            supported = ", ".join(provider.value for provider in ProviderName)
            raise ConfigError("provider", f"must be one of: {supported}") from error

    @staticmethod
    def _string(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ConfigError(field, "must be a string")
        return value

    @staticmethod
    def _integer(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ConfigError(field, "must be an integer")
        try:
            return int(value)
        except ValueError as error:
            raise ConfigError(field, "must be an integer") from error

    @staticmethod
    def _positive_float(value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ConfigError(field, "must be a number")
        try:
            return float(value)
        except ValueError as error:
            raise ConfigError(field, "must be a number") from error

    @staticmethod
    def _boolean(value: object, field: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ConfigError(field, "must be a boolean: true/false, yes/no, on/off, or 1/0")
