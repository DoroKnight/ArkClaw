"""Fixed HKCU Run-key backend for the optional SJTUClaw autostart entry."""

from __future__ import annotations

import winreg as winreg

from sjtuclaw.application.autostart_service import (
    AUTOSTART_VALUE_NAME,
    AutostartStoredValue,
)

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutostartBackendError(RuntimeError):
    """Fixed-message backend failure without registry value disclosure."""


class WindowsRunKeyAutostartBackend:
    """Access only the fixed SJTUClaw value in the current user's Run key."""

    def read_value(self) -> AutostartStoredValue | None:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _RUN_KEY_PATH,
                access=winreg.KEY_QUERY_VALUE,
            )
        except FileNotFoundError:
            return None
        except OSError:
            pass
        else:
            try:
                with key:
                    try:
                        value, value_type = winreg.QueryValueEx(
                            key,
                            AUTOSTART_VALUE_NAME,
                        )
                    except FileNotFoundError:
                        return None
            except OSError:
                pass
            else:
                try:
                    normalized_type = int(value_type)
                except (OverflowError, TypeError, ValueError):
                    pass
                else:
                    command = value if isinstance(value, str) else None
                    return AutostartStoredValue(
                        value_type=normalized_type,
                        command=command,
                    )
        raise AutostartBackendError(
            "The autostart registry value could not be read safely."
        )

    def write_value(self, command: str) -> None:
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                _RUN_KEY_PATH,
                access=winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    AUTOSTART_VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    command,
                )
        except OSError:
            pass
        else:
            return
        raise AutostartBackendError(
            "The autostart registry value could not be written safely."
        )

    def delete_value(self) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _RUN_KEY_PATH,
                access=winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
        except OSError:
            pass
        else:
            return
        raise AutostartBackendError(
            "The autostart registry value could not be deleted safely."
        )
