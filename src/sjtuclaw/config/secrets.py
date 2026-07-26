"""Credential boundaries kept separate from RuntimeConfig."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol

from sjtuclaw.config.errors import SecretStoreReadOnlyError
from sjtuclaw.domain.models import (
    OPENAI_DEFAULT_CREDENTIAL_ID,
    CredentialId,
)


class SecretValue:
    """A value that is redacted from accidental string conversion and repr."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("secret value must not be blank")
        self.__value = value

    def reveal(self) -> str:
        """Explicitly reveal the secret for an authenticated API client."""

        return self.__value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


class SecretStore(Protocol):
    """Provider-neutral port for opaque credentials."""

    def has_secret(self, credential_id: CredentialId) -> bool:
        """Return whether the selected credential is available."""

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        """Read one credential without exposing it through repr or str."""

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        """Persist one credential."""

    def delete_secret(self, credential_id: CredentialId) -> None:
        """Delete one credential."""

    def has_openai_api_key(self) -> bool:
        """Compatibility facade for the reserved OpenAI credential."""

    def get_openai_api_key(self) -> SecretValue | None:
        """Read the API key without exposing it through repr or str."""

    def set_openai_api_key(self, value: SecretValue) -> None:
        """Persist the API key in the store."""

    def delete_openai_api_key(self) -> None:
        """Delete the API key from the store."""


class InMemorySecretStore:
    """Non-persistent test double for SecretStore."""

    def __init__(self) -> None:
        self.__secrets: dict[CredentialId, str] = {}

    def has_secret(self, credential_id: CredentialId) -> bool:
        return credential_id in self.__secrets

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        value = self.__secrets.get(credential_id)
        return SecretValue(value) if value is not None else None

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        self.__secrets[credential_id] = value.reveal()

    def delete_secret(self, credential_id: CredentialId) -> None:
        self.__secrets.pop(credential_id, None)

    def has_openai_api_key(self) -> bool:
        return self.has_secret(OPENAI_DEFAULT_CREDENTIAL_ID)

    def get_openai_api_key(self) -> SecretValue | None:
        return self.get_secret(OPENAI_DEFAULT_CREDENTIAL_ID)

    def set_openai_api_key(self, value: SecretValue) -> None:
        self.set_secret(OPENAI_DEFAULT_CREDENTIAL_ID, value)

    def delete_openai_api_key(self) -> None:
        self.delete_secret(OPENAI_DEFAULT_CREDENTIAL_ID)


class EnvironmentSecretStore:
    """Read a development credential from the process without persisting it."""

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        variable_name: str = "OPENAI_API_KEY",
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._variable_name = variable_name

    def has_openai_api_key(self) -> bool:
        return bool(self._environ.get(self._variable_name, "").strip())

    def get_openai_api_key(self) -> SecretValue | None:
        value = self._environ.get(self._variable_name, "").strip()
        return SecretValue(value) if value else None

    def set_openai_api_key(self, value: SecretValue) -> None:
        del value
        raise SecretStoreReadOnlyError(
            "EnvironmentSecretStore is read-only and never persists credentials."
        )

    def delete_openai_api_key(self) -> None:
        raise SecretStoreReadOnlyError(
            "EnvironmentSecretStore is read-only and never modifies the process environment."
        )

    def has_secret(self, credential_id: CredentialId) -> bool:
        return (
            credential_id == OPENAI_DEFAULT_CREDENTIAL_ID
            and self.has_openai_api_key()
        )

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        if credential_id != OPENAI_DEFAULT_CREDENTIAL_ID:
            return None
        return self.get_openai_api_key()

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        del credential_id
        self.set_openai_api_key(value)

    def delete_secret(self, credential_id: CredentialId) -> None:
        del credential_id
        self.delete_openai_api_key()
