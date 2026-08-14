from __future__ import annotations

import inspect
import logging
import traceback
from types import TracebackType
from typing import Self

import pytest

from arkclaw.application.system.autostart_service import AUTOSTART_VALUE_NAME
from arkclaw.infrastructure.autostart import windows_run_key
from arkclaw.infrastructure.autostart.windows_run_key import (
    AutostartBackendError,
    WindowsRunKeyAutostartBackend,
)


class _FakeKey:
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback_value: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback_value


def test_missing_run_key_is_read_only_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_calls = 0

    def missing_key(*args: object, **kwargs: object) -> _FakeKey:
        del args, kwargs
        raise FileNotFoundError

    def forbidden_create(*args: object, **kwargs: object) -> _FakeKey:
        del args, kwargs
        nonlocal create_calls
        create_calls += 1
        raise AssertionError("A query must not create the Run key.")

    monkeypatch.setattr(windows_run_key.winreg, "OpenKey", missing_key)
    monkeypatch.setattr(
        windows_run_key.winreg,
        "CreateKeyEx",
        forbidden_create,
    )

    assert WindowsRunKeyAutostartBackend().read_value() is None
    assert create_calls == 0


def test_backend_reads_only_fixed_run_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[object, str, int]] = []
    queried: list[str] = []

    def open_key(
        root: object,
        path: str,
        *,
        access: int,
    ) -> _FakeKey:
        opened.append((root, path, access))
        return _FakeKey()

    def query_value(key: object, name: str) -> tuple[str, int]:
        del key
        queried.append(name)
        return ('"C:\\Fixed\\ArkClaw.exe" --startup', 1)

    monkeypatch.setattr(windows_run_key.winreg, "OpenKey", open_key)
    monkeypatch.setattr(
        windows_run_key.winreg,
        "QueryValueEx",
        query_value,
    )

    value = WindowsRunKeyAutostartBackend().read_value()

    assert value is not None
    assert value.value_type == 1
    assert value.command == '"C:\\Fixed\\ArkClaw.exe" --startup'
    assert queried == [AUTOSTART_VALUE_NAME]
    assert opened == [
        (
            windows_run_key.winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            windows_run_key.winreg.KEY_QUERY_VALUE,
        )
    ]


def test_write_and_delete_use_only_fixed_value_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[str, int, str]] = []
    deletes: list[str] = []
    command = '"C:\\Fixed\\ArkClaw.exe" --startup'

    monkeypatch.setattr(
        windows_run_key.winreg,
        "CreateKeyEx",
        lambda *args, **kwargs: _FakeKey(),
    )
    monkeypatch.setattr(
        windows_run_key.winreg,
        "OpenKey",
        lambda *args, **kwargs: _FakeKey(),
    )

    def set_value(
        key: object,
        name: str,
        reserved: int,
        value_type: int,
        value: str,
    ) -> None:
        del key, reserved
        writes.append((name, value_type, value))

    def delete_value(key: object, name: str) -> None:
        del key
        deletes.append(name)

    monkeypatch.setattr(windows_run_key.winreg, "SetValueEx", set_value)
    monkeypatch.setattr(
        windows_run_key.winreg,
        "DeleteValue",
        delete_value,
    )
    backend = WindowsRunKeyAutostartBackend()

    backend.write_value(command)
    backend.delete_value()

    assert writes == [
        (AUTOSTART_VALUE_NAME, windows_run_key.winreg.REG_SZ, command)
    ]
    assert deletes == [AUTOSTART_VALUE_NAME]


def test_backend_error_output_does_not_expose_registry_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive = "unsafe-autostart-command-never-display"

    def fail_open(*args: object, **kwargs: object) -> _FakeKey:
        del args, kwargs
        raise PermissionError(sensitive)

    monkeypatch.setattr(windows_run_key.winreg, "OpenKey", fail_open)
    captured_error: AutostartBackendError | None = None

    try:
        WindowsRunKeyAutostartBackend().read_value()
    except AutostartBackendError as error:
        captured_error = error
        with caplog.at_level(logging.ERROR):
            logging.getLogger(__name__).exception("safe autostart failure")
        visible = "".join(
            traceback.format_exception(
                type(error),
                error,
                error.__traceback__,
            )
        )
    else:
        raise AssertionError("Expected a sanitized backend error.")

    assert captured_error is not None
    assert captured_error.__cause__ is None
    assert captured_error.__context__ is None
    assert sensitive not in str(captured_error)
    assert sensitive not in repr(captured_error)
    assert sensitive not in visible
    assert sensitive not in caplog.text


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_backend_mutation_errors_have_no_sensitive_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    sensitive = f"unsafe-{operation}-body-never-display"
    monkeypatch.setattr(
        windows_run_key.winreg,
        "CreateKeyEx",
        lambda *args, **kwargs: _FakeKey(),
    )
    monkeypatch.setattr(
        windows_run_key.winreg,
        "OpenKey",
        lambda *args, **kwargs: _FakeKey(),
    )

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise PermissionError(sensitive)

    if operation == "write":
        monkeypatch.setattr(windows_run_key.winreg, "SetValueEx", fail)
    else:
        monkeypatch.setattr(windows_run_key.winreg, "DeleteValue", fail)
    backend = WindowsRunKeyAutostartBackend()
    captured_error: AutostartBackendError | None = None

    try:
        if operation == "write":
            backend.write_value('"C:\\Fixed\\ArkClaw.exe" --startup')
        else:
            backend.delete_value()
    except AutostartBackendError as error:
        captured_error = error
        with caplog.at_level(logging.ERROR):
            logging.getLogger(__name__).exception("safe autostart failure")
        visible = "".join(
            traceback.format_exception(
                type(error),
                error,
                error.__traceback__,
            )
        )
    else:
        raise AssertionError("Expected a sanitized backend error.")

    assert captured_error is not None
    assert captured_error.__cause__ is None
    assert captured_error.__context__ is None
    assert sensitive not in str(captured_error)
    assert sensitive not in repr(captured_error)
    assert sensitive not in visible
    assert sensitive not in caplog.text


def test_backend_never_touches_startup_approved() -> None:
    source = inspect.getsource(windows_run_key)

    assert "StartupApproved" not in source
