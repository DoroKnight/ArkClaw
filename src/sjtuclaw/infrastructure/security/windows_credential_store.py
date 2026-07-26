"""Windows Credential Manager adapter for provider credentials."""

from __future__ import annotations

import sys
from typing import Any, ClassVar, Protocol, cast

from sjtuclaw.config.errors import (
    SecretStoreAccessDeniedError,
    SecretStoreCorruptedError,
    SecretStoreError,
    SecretStoreUnavailableError,
)
from sjtuclaw.config.secrets import SecretValue
from sjtuclaw.domain.models import (
    DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    CredentialId,
)

OPENAI_API_KEY_TARGET = "SJTUClaw/OpenAI/APIKey"
DEEPSEEK_API_KEY_TARGET = (
    f"SJTUClaw/Credentials/{DEEPSEEK_DEFAULT_CREDENTIAL_ID.value}"
)
OPENAI_MANUAL_TEST_TARGET = "SJTUClaw/Test/OpenAI/APIKey"
DEEPSEEK_MANUAL_TEST_TARGET = "SJTUClaw/Test/DeepSeek/APIKey"

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_ACCESS_DENIED = 5
_ERROR_NOT_SUPPORTED = 50
_ERROR_CALL_NOT_IMPLEMENTED = 120
_ERROR_NOT_FOUND = 1168
_ERROR_NO_SUCH_LOGON_SESSION = 1312
_MAX_CREDENTIAL_BLOB_SIZE = 2560


class CredentialTargetResolver:
    """Resolve only reserved or validated opaque credential identifiers."""

    _RESERVED_TARGETS: ClassVar[dict[CredentialId, str]] = {
        OPENAI_DEFAULT_CREDENTIAL_ID: OPENAI_API_KEY_TARGET,
        OPENAI_MANUAL_TEST_CREDENTIAL_ID: OPENAI_MANUAL_TEST_TARGET,
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID: DEEPSEEK_MANUAL_TEST_TARGET,
    }

    @classmethod
    def resolve(cls, credential_id: CredentialId) -> str:
        if not isinstance(credential_id, CredentialId):
            raise TypeError("credential_id must be a CredentialId")
        reserved = cls._RESERVED_TARGETS.get(credential_id)
        if reserved is not None:
            return reserved
        return f"SJTUClaw/Credentials/{credential_id.value}"


class CredentialBackendAccessDeniedError(Exception):
    """The operating system denied access to the credential."""


class CredentialBackendUnavailableError(Exception):
    """The operating-system credential service is unavailable."""


class CredentialBackendCorruptedError(Exception):
    """The backend returned an invalid credential blob."""


class CredentialBackend(Protocol):
    """Narrow byte-oriented boundary around a credential facility."""

    def read(self, target_name: str) -> bytes | None:
        """Return credential bytes, or None when the target does not exist."""

    def write(self, target_name: str, secret_bytes: bytes) -> None:
        """Create or replace a generic credential."""

    def delete(self, target_name: str) -> None:
        """Delete a credential; a missing target is not an error."""


class Win32CredentialBackend:
    """Direct, delayed ctypes binding to the Win32 Credential API."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise CredentialBackendUnavailableError(
                "Windows Credential Manager is unavailable on this platform."
            )
        self._load_api()

    def _load_api(self) -> None:
        initialization_error: CredentialBackendUnavailableError | None = None
        try:
            import ctypes
            from ctypes import wintypes

            class _FileTime(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD),
                ]

            class _CredentialW(ctypes.Structure):
                pass

            byte_pointer = ctypes.POINTER(ctypes.c_ubyte)
            _CredentialW._fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", _FileTime),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", byte_pointer),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]
            credential_pointer = ctypes.POINTER(_CredentialW)

            advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            advapi32.CredReadW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(credential_pointer),
            ]
            advapi32.CredReadW.restype = wintypes.BOOL
            advapi32.CredWriteW.argtypes = [
                ctypes.POINTER(_CredentialW),
                wintypes.DWORD,
            ]
            advapi32.CredWriteW.restype = wintypes.BOOL
            advapi32.CredDeleteW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            advapi32.CredDeleteW.restype = wintypes.BOOL
            advapi32.CredFree.argtypes = [ctypes.c_void_p]
            advapi32.CredFree.restype = None
        except (AttributeError, OSError):
            initialization_error = CredentialBackendUnavailableError(
                "Windows Credential Manager could not be initialized."
            )

        if initialization_error is not None:
            raise initialization_error from None

        self._ctypes: Any = ctypes
        self._advapi32: Any = advapi32
        self._credential_type: Any = _CredentialW
        self._credential_pointer: Any = credential_pointer
        self._byte_pointer: Any = byte_pointer

    def read(self, target_name: str) -> bytes | None:
        credential = self._credential_pointer()
        if not self._advapi32.CredReadW(
            target_name,
            _CRED_TYPE_GENERIC,
            0,
            self._ctypes.byref(credential),
        ):
            error_code = self._ctypes.get_last_error()
            if error_code == _ERROR_NOT_FOUND:
                return None
            self._raise_windows_error(error_code)

        try:
            value = credential.contents
            size = int(value.CredentialBlobSize)
            if size < 0 or size > _MAX_CREDENTIAL_BLOB_SIZE:
                raise CredentialBackendCorruptedError(
                    "Credential blob size is invalid."
                )
            if size == 0:
                return b""
            if not value.CredentialBlob:
                raise CredentialBackendCorruptedError(
                    "Credential blob pointer is missing."
                )
            return cast(bytes, self._ctypes.string_at(value.CredentialBlob, size))
        finally:
            self._advapi32.CredFree(credential)

    def write(self, target_name: str, secret_bytes: bytes) -> None:
        if not secret_bytes or len(secret_bytes) > _MAX_CREDENTIAL_BLOB_SIZE:
            raise CredentialBackendCorruptedError(
                "Credential blob size is invalid."
            )

        buffer = self._ctypes.create_string_buffer(secret_bytes, len(secret_bytes))
        credential = self._credential_type()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = target_name
        credential.CredentialBlobSize = len(secret_bytes)
        credential.CredentialBlob = self._ctypes.cast(
            buffer,
            self._byte_pointer,
        )
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "SJTUClaw"

        try:
            if not self._advapi32.CredWriteW(self._ctypes.byref(credential), 0):
                self._raise_windows_error(self._ctypes.get_last_error())
        finally:
            self._ctypes.memset(buffer, 0, len(secret_bytes))

    def delete(self, target_name: str) -> None:
        if self._advapi32.CredDeleteW(target_name, _CRED_TYPE_GENERIC, 0):
            return
        error_code = self._ctypes.get_last_error()
        if error_code == _ERROR_NOT_FOUND:
            return
        self._raise_windows_error(error_code)

    @staticmethod
    def _raise_windows_error(error_code: int) -> None:
        if error_code == _ERROR_ACCESS_DENIED:
            raise CredentialBackendAccessDeniedError(
                "Windows denied credential access."
            )
        if error_code in {
            _ERROR_NOT_SUPPORTED,
            _ERROR_CALL_NOT_IMPLEMENTED,
            _ERROR_NO_SUCH_LOGON_SESSION,
        }:
            raise CredentialBackendUnavailableError(
                "Windows Credential Manager is unavailable."
            )
        raise OSError(error_code, "Windows Credential Manager operation failed.")


class WindowsCredentialSecretStore:
    """Persist provider credentials as Windows Generic Credentials."""

    def __init__(
        self,
        backend: CredentialBackend | None = None,
        *,
        openai_credential_id: CredentialId = OPENAI_DEFAULT_CREDENTIAL_ID,
    ) -> None:
        CredentialTargetResolver.resolve(openai_credential_id)
        self._openai_credential_id = openai_credential_id
        if backend is not None:
            self._backend = backend
            return
        initialization_error: SecretStoreUnavailableError | None = None
        try:
            self._backend = Win32CredentialBackend()
        except Exception:
            initialization_error = SecretStoreUnavailableError(
                "Windows Credential Manager is unavailable."
            )
        if initialization_error is not None:
            raise initialization_error from None

    def has_openai_api_key(self) -> bool:
        return self.has_secret(self._openai_credential_id)

    def get_openai_api_key(self) -> SecretValue | None:
        return self.get_secret(self._openai_credential_id)

    def set_openai_api_key(self, value: SecretValue) -> None:
        self.set_secret(self._openai_credential_id, value)

    def delete_openai_api_key(self) -> None:
        self.delete_secret(self._openai_credential_id)

    def has_secret(self, credential_id: CredentialId) -> bool:
        return self.get_secret(credential_id) is not None

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        target_name = CredentialTargetResolver.resolve(credential_id)
        store_error: SecretStoreError | None = None
        blob: bytes | None = None
        try:
            blob = self._backend.read(target_name)
        except Exception as error:
            store_error = self._map_store_error(error)
        if store_error is not None:
            raise store_error from None
        if blob is None:
            return None
        if not isinstance(blob, bytes):
            corrupted_error = SecretStoreCorruptedError(
                "The stored credential has an invalid binary type."
            )
            blob = None
            raise corrupted_error from None
        decoding_error: SecretStoreCorruptedError | None = None
        value = ""
        try:
            value = blob.decode("utf-8")
        except UnicodeDecodeError:
            decoding_error = SecretStoreCorruptedError(
                "The stored credential has an invalid encoding."
            )
        if decoding_error is not None:
            blob = None
            raise decoding_error from None
        if not value.strip():
            raise SecretStoreCorruptedError(
                "The stored credential is empty or invalid."
            )
        return SecretValue(value)

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        target_name = CredentialTargetResolver.resolve(credential_id)
        revealed = value.reveal()
        if not revealed.strip():
            raise ValueError("credential must not be blank")
        encoding_error: SecretStoreError | None = None
        encoded_value = b""
        try:
            encoded_value = revealed.encode("utf-8")
        except UnicodeEncodeError:
            encoding_error = SecretStoreError(
                "The credential could not be encoded safely."
            )
        if encoding_error is not None:
            revealed = ""
            encoded_value = b""
            del value
            raise encoding_error from None

        store_error: SecretStoreError | None = None
        try:
            self._backend.write(target_name, encoded_value)
        except Exception as error:
            store_error = self._map_store_error(error)
        revealed = ""
        encoded_value = b""
        del value
        if store_error is not None:
            raise store_error from None

    def delete_secret(self, credential_id: CredentialId) -> None:
        target_name = CredentialTargetResolver.resolve(credential_id)
        store_error: SecretStoreError | None = None
        try:
            self._backend.delete(target_name)
        except Exception as error:
            store_error = self._map_store_error(error)
        if store_error is not None:
            raise store_error from None

    @staticmethod
    def _map_store_error(error: Exception) -> SecretStoreError:
        if isinstance(error, CredentialBackendAccessDeniedError):
            return SecretStoreAccessDeniedError(
                "Windows denied access to the credential."
            )
        if isinstance(error, CredentialBackendUnavailableError):
            return SecretStoreUnavailableError(
                "Windows Credential Manager is unavailable."
            )
        if isinstance(error, CredentialBackendCorruptedError):
            return SecretStoreCorruptedError(
                "Windows Credential Manager returned invalid credential data."
            )
        return SecretStoreError("Windows Credential Manager operation failed.")
