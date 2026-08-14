import importlib
import json
import logging
import sys
import traceback
from collections.abc import Callable
from typing import cast

import pytest
from scripts.manual_credential_targets import ManualCredentialTargetResolver

from arkclaw.config.errors import (
    SecretStoreAccessDeniedError,
    SecretStoreCorruptedError,
    SecretStoreError,
    SecretStoreUnavailableError,
)
from arkclaw.config.loader import ConfigLoader
from arkclaw.config.secrets import SecretValue
from arkclaw.domain.models import (
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    CredentialId,
)
from arkclaw.infrastructure.security import windows_credential_store
from arkclaw.infrastructure.security.windows_credential_store import (
    OPENAI_API_KEY_TARGET,
    CredentialBackendAccessDeniedError,
    CredentialBackendCorruptedError,
    CredentialBackendUnavailableError,
    CredentialTargetResolutionError,
    CredentialTargetResolver,
    Win32CredentialBackend,
    WindowsCredentialSecretStore,
)

_TEST_TARGET = "ArkClaw/Test/OpenAI/APIKey"
_FAKE_API_KEY = "sk-test-never-use-this-value"


class _FakeCredentialBackend:
    def __init__(self) -> None:
        self.blob: bytes | None = None
        self.error: Exception | None = None
        self.read_targets: list[str] = []
        self.write_targets: list[str] = []
        self.delete_targets: list[str] = []

    def read(self, target_name: str) -> bytes | None:
        self.read_targets.append(target_name)
        if self.error is not None:
            raise self.error
        return self.blob

    def write(self, target_name: str, secret_bytes: bytes) -> None:
        self.write_targets.append(target_name)
        if self.error is not None:
            raise self.error
        self.blob = secret_bytes

    def delete(self, target_name: str) -> None:
        self.delete_targets.append(target_name)
        if self.error is not None:
            raise self.error
        self.blob = None


def _store(
    backend: _FakeCredentialBackend | None = None,
) -> tuple[WindowsCredentialSecretStore, _FakeCredentialBackend]:
    selected_backend = backend or _FakeCredentialBackend()
    return (
        WindowsCredentialSecretStore(
            backend=selected_backend,
            openai_credential_id=OPENAI_MANUAL_TEST_CREDENTIAL_ID,
            target_resolver=ManualCredentialTargetResolver(),
        ),
        selected_backend,
    )


def _capture_logged_failure(
    operation: Callable[[], object],
    caplog: pytest.LogCaptureFixture,
) -> tuple[SecretStoreError, str]:
    caplog.clear()
    try:
        operation()
    except SecretStoreError as error:
        rendered = "".join(traceback.format_exception(error))
        logging.getLogger("test.windows-store.failure").exception(
            "Credential operation failed safely."
        )
        return error, rendered
    raise AssertionError("operation did not raise SecretStoreError")


def _assert_sensitive_error_is_sanitized(
    error: SecretStoreError,
    rendered: str,
    caplog: pytest.LogCaptureFixture,
    sensitive_text: str,
) -> None:
    assert sensitive_text not in str(error)
    assert sensitive_text not in repr(error)
    assert sensitive_text not in rendered
    assert sensitive_text not in caplog.text
    assert error.__cause__ is None
    assert error.__context__ is None


def test_default_credential_target_is_stable() -> None:
    assert OPENAI_API_KEY_TARGET == "ArkClaw/OpenAI/APIKey"


@pytest.mark.parametrize(
    "credential_id",
    [
        OPENAI_MANUAL_TEST_CREDENTIAL_ID,
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    ],
)
def test_production_resolver_rejects_manual_test_ids(
    credential_id: CredentialId,
) -> None:
    with pytest.raises(
        CredentialTargetResolutionError,
        match="credential identifier is not permitted",
    ) as raised:
        CredentialTargetResolver.resolve(credential_id)

    assert credential_id.value not in str(raised.value)
    assert "ArkClaw/" not in str(raised.value)


@pytest.mark.parametrize(
    "operation",
    ["has", "get", "set", "delete"],
)
@pytest.mark.parametrize(
    "credential_id",
    [
        OPENAI_MANUAL_TEST_CREDENTIAL_ID,
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    ],
)
def test_production_store_rejects_manual_id_before_backend(
    operation: str,
    credential_id: CredentialId,
) -> None:
    backend = _FakeCredentialBackend()
    store = WindowsCredentialSecretStore(backend=backend)

    with pytest.raises(CredentialTargetResolutionError):
        if operation == "has":
            store.has_secret(credential_id)
        elif operation == "get":
            store.get_secret(credential_id)
        elif operation == "set":
            store.set_secret(
                credential_id,
                SecretValue(_FAKE_API_KEY),
            )
        else:
            store.delete_secret(credential_id)

    assert backend.read_targets == []
    assert backend.write_targets == []
    assert backend.delete_targets == []


def test_manual_openai_id_is_rejected_before_native_backend_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_calls = 0

    def fail_backend() -> Win32CredentialBackend:
        nonlocal backend_calls
        backend_calls += 1
        raise AssertionError("backend construction must not be reached")

    monkeypatch.setattr(
        windows_credential_store,
        "Win32CredentialBackend",
        fail_backend,
    )

    with pytest.raises(CredentialTargetResolutionError):
        WindowsCredentialSecretStore(
            openai_credential_id=OPENAI_MANUAL_TEST_CREDENTIAL_ID,
        )

    assert backend_calls == 0


def test_missing_credential_returns_none() -> None:
    store, backend = _store()

    assert store.has_openai_api_key() is False
    assert store.get_openai_api_key() is None
    assert backend.read_targets == [_TEST_TARGET, _TEST_TARGET]


def test_write_read_overwrite_and_delete_are_deterministic() -> None:
    store, backend = _store()

    store.set_openai_api_key(SecretValue("first-secret"))
    assert backend.blob == b"first-secret"
    assert store.has_openai_api_key() is True
    first = store.get_openai_api_key()
    assert first is not None
    assert first.reveal() == "first-secret"

    store.set_openai_api_key(SecretValue("replacement-secret"))
    replacement = store.get_openai_api_key()
    assert replacement is not None
    assert replacement.reveal() == "replacement-secret"

    store.delete_openai_api_key()
    store.delete_openai_api_key()
    assert store.get_openai_api_key() is None
    assert backend.write_targets == [_TEST_TARGET, _TEST_TARGET]
    assert backend.delete_targets == [_TEST_TARGET, _TEST_TARGET]


@pytest.mark.parametrize("value", ["", "   ", "\t\r\n"])
def test_blank_secret_is_rejected_without_backend_write(value: str) -> None:
    store, backend = _store()

    with pytest.raises(ValueError, match="blank"):
        store.set_openai_api_key(SecretValue(value))

    assert backend.write_targets == []
    assert backend.blob is None


@pytest.mark.parametrize(
    "blob",
    [
        b"\xff\xfe\xfa",
        cast(bytes, object()),
        b"",
        b"   ",
    ],
)
def test_invalid_credential_blob_is_reported_as_corrupted(blob: bytes) -> None:
    backend = _FakeCredentialBackend()
    backend.blob = blob
    store, _ = _store(backend)

    with pytest.raises(SecretStoreCorruptedError):
        store.get_openai_api_key()


@pytest.mark.parametrize(
    ("backend_error", "store_error", "expected_message"),
    [
        (
            CredentialBackendAccessDeniedError(_FAKE_API_KEY),
            SecretStoreAccessDeniedError,
            "Windows denied access to the credential.",
        ),
        (
            CredentialBackendUnavailableError(_FAKE_API_KEY),
            SecretStoreUnavailableError,
            "Windows Credential Manager is unavailable.",
        ),
        (
            CredentialBackendCorruptedError(_FAKE_API_KEY),
            SecretStoreCorruptedError,
            "Windows Credential Manager returned invalid credential data.",
        ),
    ],
)
def test_known_backend_errors_are_mapped_safely(
    backend_error: Exception,
    store_error: type[SecretStoreError],
    expected_message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _FakeCredentialBackend()
    backend.error = backend_error
    store, _ = _store(backend)

    error, rendered = _capture_logged_failure(store.has_openai_api_key, caplog)

    assert isinstance(error, store_error)
    assert str(error) == expected_message
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )


def test_unknown_backend_read_error_has_no_sensitive_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend_error = OSError(1234, _FAKE_API_KEY)
    backend = _FakeCredentialBackend()
    backend.error = backend_error
    store, _ = _store(backend)

    error, rendered = _capture_logged_failure(store.get_openai_api_key, caplog)

    assert str(error) == "Windows Credential Manager operation failed."
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )


def test_backend_write_error_has_no_sensitive_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _FakeCredentialBackend()
    backend.error = RuntimeError(_FAKE_API_KEY)
    store, _ = _store(backend)

    error, rendered = _capture_logged_failure(
        lambda: store.set_openai_api_key(SecretValue(_FAKE_API_KEY)),
        caplog,
    )

    assert str(error) == "Windows Credential Manager operation failed."
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )


def test_backend_delete_error_has_no_sensitive_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _FakeCredentialBackend()
    backend.error = RuntimeError(_FAKE_API_KEY)
    store, _ = _store(backend)

    error, rendered = _capture_logged_failure(store.delete_openai_api_key, caplog)

    assert str(error) == "Windows Credential Manager operation failed."
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )


def test_invalid_utf8_blob_has_no_sensitive_decode_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _FakeCredentialBackend()
    backend.blob = b"\xff" + _FAKE_API_KEY.encode("ascii")
    store, _ = _store(backend)

    error, rendered = _capture_logged_failure(store.get_openai_api_key, caplog)

    assert isinstance(error, SecretStoreCorruptedError)
    assert str(error) == "The stored credential has an invalid encoding."
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )
    assert not isinstance(error.__cause__, UnicodeDecodeError)
    assert not isinstance(error.__context__, UnicodeDecodeError)


def test_utf8_encoding_failure_has_no_sensitive_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unencodable_secret = f"{_FAKE_API_KEY}\ud800"
    store, backend = _store()

    error, rendered = _capture_logged_failure(
        lambda: store.set_openai_api_key(SecretValue(unencodable_secret)),
        caplog,
    )

    assert str(error) == "The credential could not be encoded safely."
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )
    assert not isinstance(error.__cause__, UnicodeEncodeError)
    assert not isinstance(error.__context__, UnicodeEncodeError)
    assert backend.write_targets == []


def test_backend_initialization_error_has_no_sensitive_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_backend() -> Win32CredentialBackend:
        raise CredentialBackendUnavailableError(_FAKE_API_KEY)

    monkeypatch.setattr(
        windows_credential_store,
        "Win32CredentialBackend",
        fail_backend,
    )

    error, rendered = _capture_logged_failure(
        WindowsCredentialSecretStore,
        caplog,
    )

    assert isinstance(error, SecretStoreUnavailableError)
    assert str(error) == "Windows Credential Manager is unavailable."
    _assert_sensitive_error_is_sanitized(
        error,
        rendered,
        caplog,
        _FAKE_API_KEY,
    )


def test_secret_config_exceptions_and_logs_do_not_expose_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "sk-windows-store-never-log"
    store, _ = _store()
    store.set_openai_api_key(SecretValue(api_key))
    secret = store.get_openai_api_key()
    assert secret is not None
    config = ConfigLoader().load(environ={})

    with caplog.at_level(logging.INFO):
        logging.getLogger("test.windows-store").info(
            "store=%r secret=%r config=%r",
            store,
            secret,
            config,
        )

    assert api_key not in repr(store)
    assert api_key not in repr(secret)
    assert api_key not in str(secret)
    assert api_key not in caplog.text
    assert api_key not in json.dumps(config.to_dict())
    assert "api_key" not in json.dumps(config.to_dict()).lower()


def test_non_windows_default_backend_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(
        SecretStoreUnavailableError,
        match="Windows Credential Manager is unavailable",
    ):
        WindowsCredentialSecretStore()


def test_module_import_does_not_construct_or_access_native_backend() -> None:
    module = importlib.import_module(
        "arkclaw.infrastructure.security.windows_credential_store"
    )

    assert not any(
        isinstance(value, Win32CredentialBackend)
        for value in vars(module).values()
    )


def test_all_ordinary_store_tests_use_injected_fake_backend() -> None:
    store, backend = _store()

    assert isinstance(backend, _FakeCredentialBackend)
    assert not isinstance(backend, Win32CredentialBackend)
    assert store.get_openai_api_key() is None
