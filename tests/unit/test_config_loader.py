from dataclasses import FrozenInstanceError

import pytest

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
from sjtuclaw.config.loader import ConfigLoader
from sjtuclaw.config.models import ProviderName, RuntimeConfig


def test_defaults_start_with_fake_provider() -> None:
    config = ConfigLoader().load(environ={})

    assert config.provider is ProviderName.FAKE
    assert config.openai_model == DEFAULT_OPENAI_MODEL
    assert config.deepseek_model == DEFAULT_DEEPSEEK_MODEL
    assert config.ollama_model == DEFAULT_OLLAMA_MODEL
    assert config.provider_timeout_seconds == DEFAULT_PROVIDER_TIMEOUT_SECONDS
    assert config.max_turn_seconds == DEFAULT_MAX_TURN_SECONDS
    assert config.openai_max_retries == DEFAULT_OPENAI_MAX_RETRIES
    assert config.deepseek_max_retries == DEFAULT_DEEPSEEK_MAX_RETRIES
    assert config.ollama_base_url == DEFAULT_OLLAMA_BASE_URL
    assert config.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert config.stream is DEFAULT_STREAM


def test_invalid_provider_has_clear_error() -> None:
    with pytest.raises(
        ConfigError,
        match=r"provider.*fake, openai, deepseek, ollama",
    ):
        ConfigLoader().load(environ={"SJTUCLAW_PROVIDER": "unknown"})


def test_cli_overrides_environment() -> None:
    config = ConfigLoader().load(
        environ={
            "SJTUCLAW_PROVIDER": "ollama",
            "SJTUCLAW_OPENAI_MODEL": "environment-model",
        },
        cli_args=["--provider", "openai", "--openai-model", "cli-model"],
    )

    assert config.provider is ProviderName.OPENAI
    assert config.openai_model == "cli-model"


def test_environment_overrides_application_settings() -> None:
    config = ConfigLoader().load(
        app_settings={
            "provider": "fake",
            "ollama_model": "settings-model",
            "max_output_tokens": 512,
        },
        environ={
            "SJTUCLAW_PROVIDER": "ollama",
            "SJTUCLAW_OLLAMA_MODEL": "environment-model",
            "SJTUCLAW_MAX_OUTPUT_TOKENS": "2048",
        },
    )

    assert config.provider is ProviderName.OLLAMA
    assert config.ollama_model == "environment-model"
    assert config.max_output_tokens == 2048


def test_application_settings_override_defaults() -> None:
    config = ConfigLoader().load(
        app_settings={
            "openai_model": "settings-openai-model",
            "provider_timeout_seconds": 45,
            "stream": False,
        },
        environ={},
    )

    assert config.openai_model == "settings-openai-model"
    assert config.provider_timeout_seconds == 45.0
    assert config.stream is False


def test_provider_and_turn_timeouts_are_independent() -> None:
    config = ConfigLoader().load(
        app_settings={
            "provider_timeout_seconds": 12,
            "max_turn_seconds": 34,
        },
        environ={},
    )

    assert config.provider_timeout_seconds == 12.0
    assert config.max_turn_seconds == 34.0


def test_max_turn_cli_overrides_environment() -> None:
    config = ConfigLoader().load(
        environ={"SJTUCLAW_MAX_TURN_SECONDS": "20"},
        cli_args=["--max-turn-seconds", "10"],
    )

    assert config.max_turn_seconds == 10.0


def test_max_turn_environment_overrides_application_settings() -> None:
    config = ConfigLoader().load(
        app_settings={"max_turn_seconds": 30},
        environ={"SJTUCLAW_MAX_TURN_SECONDS": "15"},
    )

    assert config.max_turn_seconds == 15.0


def test_openai_and_ollama_keep_separate_model_names() -> None:
    config = ConfigLoader().load(
        app_settings={
            "openai_model": "cloud-model",
            "ollama_model": "local-model",
        },
        environ={},
    )

    assert config.openai_model == "cloud-model"
    assert config.ollama_model == "local-model"


def test_deepseek_configuration_is_independent_and_serializes_no_key() -> None:
    fake_key = "sk-deepseek-test-never-use"
    config = ConfigLoader().load(
        environ={
            "SJTUCLAW_PROVIDER": "deepseek",
            "SJTUCLAW_DEEPSEEK_MODEL": "deepseek-test-model",
            "SJTUCLAW_DEEPSEEK_MAX_RETRIES": "0",
            "DEEPSEEK_API_KEY": fake_key,
        },
    )

    assert config.provider is ProviderName.DEEPSEEK
    assert config.deepseek_model == "deepseek-test-model"
    assert config.deepseek_max_retries == 0
    assert fake_key not in repr(config)
    assert fake_key not in str(config.to_dict())
    assert "api_key" not in str(config.to_dict()).lower()


@pytest.mark.parametrize(
    "url",
    [
        "localhost:11434",
        "ftp://localhost:11434",
        "http://",
        "http://user:password@localhost:11434",
    ],
)
def test_invalid_ollama_url_is_rejected(url: str) -> None:
    with pytest.raises(ConfigError, match="ollama_base_url"):
        ConfigLoader().load(
            app_settings={"ollama_base_url": url},
            environ={},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_timeout_seconds", 0),
        ("provider_timeout_seconds", -1),
        ("provider_timeout_seconds", float("nan")),
        ("provider_timeout_seconds", float("inf")),
        ("provider_timeout_seconds", "not-a-number"),
        ("max_turn_seconds", 0),
        ("max_turn_seconds", -1),
        ("max_turn_seconds", float("nan")),
        ("max_turn_seconds", float("inf")),
        ("max_turn_seconds", "not-a-number"),
        ("openai_max_retries", -1),
        ("openai_max_retries", "not-an-integer"),
        ("deepseek_max_retries", -1),
        ("deepseek_max_retries", "not-an-integer"),
        ("max_output_tokens", 0),
        ("max_output_tokens", -1),
        ("max_output_tokens", "not-an-integer"),
    ],
)
def test_invalid_numeric_settings_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ConfigError, match=field):
        ConfigLoader().load(
            app_settings={field: value},
            environ={},
        )


@pytest.mark.parametrize(
    "field",
    ["openai_model", "deepseek_model", "ollama_model"],
)
def test_blank_model_name_is_rejected(field: str) -> None:
    with pytest.raises(ConfigError, match=field):
        ConfigLoader().load(
            app_settings={field: "   "},
            environ={},
        )


def test_runtime_config_is_immutable() -> None:
    config = ConfigLoader().load(environ={})

    with pytest.raises(FrozenInstanceError):
        config.stream = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "fake"),
        ("provider_timeout_seconds", True),
        ("max_turn_seconds", True),
        ("openai_max_retries", False),
        ("deepseek_max_retries", False),
        ("max_output_tokens", True),
        ("stream", 1),
        ("ollama_base_url", 11434),
    ],
)
def test_runtime_config_rejects_directly_constructed_wrong_types(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ConfigError, match=field):
        RuntimeConfig(**{field: value})  # type: ignore[arg-type]
