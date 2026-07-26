import hashlib
import hmac
import os
import secrets

import pytest
from scripts.manual_credential_targets import ManualCredentialTargetResolver

from sjtuclaw.config.secrets import SecretValue
from sjtuclaw.domain.models import OPENAI_MANUAL_TEST_CREDENTIAL_ID
from sjtuclaw.infrastructure.security.windows_credential_store import (
    WindowsCredentialSecretStore,
)

_ENABLED = os.environ.get("SJTUCLAW_RUN_WINDOWS_CREDENTIAL_INTEGRATION") == "1"


def _secret_digest(value: SecretValue) -> bytes:
    return hashlib.sha256(value.reveal().encode("utf-8")).digest()


@pytest.mark.skipif(
    not _ENABLED,
    reason="Set SJTUCLAW_RUN_WINDOWS_CREDENTIAL_INTEGRATION=1 to access the test Target.",
)
def test_windows_credential_manager_lifecycle() -> None:
    """Exercise only the fixed non-production Target with generated fake values."""

    store = WindowsCredentialSecretStore(
        openai_credential_id=OPENAI_MANUAL_TEST_CREDENTIAL_ID,
        target_resolver=ManualCredentialTargetResolver(),
    )
    first = SecretValue(f"sk-test-{secrets.token_hex(16)}")
    replacement = SecretValue(f"sk-test-{secrets.token_hex(16)}")

    try:
        store.delete_openai_api_key()
        assert store.get_openai_api_key() is None

        store.set_openai_api_key(first)
        saved = store.get_openai_api_key()
        assert saved is not None
        assert hmac.compare_digest(_secret_digest(saved), _secret_digest(first))

        store.set_openai_api_key(replacement)
        overwritten = store.get_openai_api_key()
        assert overwritten is not None
        assert hmac.compare_digest(
            _secret_digest(overwritten),
            _secret_digest(replacement),
        )

        store.delete_openai_api_key()
        assert store.get_openai_api_key() is None
    finally:
        store.delete_openai_api_key()
