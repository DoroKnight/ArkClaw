import json
import logging

import pytest

from sjtuclaw.config.errors import SecretStoreReadOnlyError
from sjtuclaw.config.loader import ConfigLoader
from sjtuclaw.config.secrets import (
    EnvironmentSecretStore,
    InMemorySecretStore,
    SecretValue,
)


def test_in_memory_secret_store_lifecycle() -> None:
    store = InMemorySecretStore()

    assert store.has_openai_api_key() is False
    assert store.get_openai_api_key() is None

    store.set_openai_api_key(SecretValue("development-secret"))

    assert store.has_openai_api_key() is True
    secret = store.get_openai_api_key()
    assert secret is not None
    assert secret.reveal() == "development-secret"

    store.delete_openai_api_key()
    assert store.has_openai_api_key() is False


def test_environment_secret_store_reads_without_persisting() -> None:
    store = EnvironmentSecretStore({"OPENAI_API_KEY": "development-secret"})

    assert store.has_openai_api_key() is True
    secret = store.get_openai_api_key()
    assert secret is not None
    assert secret.reveal() == "development-secret"

    with pytest.raises(SecretStoreReadOnlyError):
        store.set_openai_api_key(SecretValue("replacement-secret"))
    with pytest.raises(SecretStoreReadOnlyError):
        store.delete_openai_api_key()


def test_api_key_is_absent_from_config_serialization_repr_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "sk-example-never-log-this"
    config = ConfigLoader().load(
        environ={
            "OPENAI_API_KEY": api_key,
            "SJTUCLAW_PROVIDER": "fake",
        }
    )
    secret = EnvironmentSecretStore({"OPENAI_API_KEY": api_key}).get_openai_api_key()
    assert secret is not None

    serialized = json.dumps(config.to_dict())
    assert api_key not in serialized
    assert "api_key" not in serialized.lower()
    assert api_key not in repr(config)
    assert api_key not in repr(secret)
    assert api_key not in str(secret)

    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("config=%r secret=%r", config, secret)
    assert api_key not in caplog.text
