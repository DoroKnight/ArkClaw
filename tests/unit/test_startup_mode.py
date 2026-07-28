from __future__ import annotations

import pytest

from sjtuclaw.application.autostart_service import AUTOSTART_ARGUMENT
from sjtuclaw.application.startup_mode import (
    StartupModeArgumentError,
    parse_startup_mode,
)


def test_ordinary_launch_is_not_startup_mode() -> None:
    assert parse_startup_mode(["SJTUClaw.exe"]) is False
    assert parse_startup_mode([]) is False


def test_only_fixed_startup_argument_enables_startup_mode() -> None:
    assert AUTOSTART_ARGUMENT == "--startup"
    assert parse_startup_mode(["SJTUClaw.exe", "--startup"]) is True


@pytest.mark.parametrize(
    "arguments",
    [
        ["SJTUClaw.exe", "--startup", "--extra"],
        ["SJTUClaw.exe", "--Startup"],
        ["SJTUClaw.exe", "--startup=true"],
        ["SJTUClaw.exe", "startup"],
    ],
)
def test_unknown_or_mutated_arguments_fail_closed(
    arguments: list[str],
) -> None:
    with pytest.raises(StartupModeArgumentError) as captured:
        parse_startup_mode(arguments)

    assert str(captured.value) == (
        "The application startup arguments are invalid."
    )
    assert repr(captured.value) == (
        "StartupModeArgumentError("
        "'The application startup arguments are invalid.'"
        ")"
    )
