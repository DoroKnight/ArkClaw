"""Strict parsing for the fixed packaged startup mode."""

from __future__ import annotations

from collections.abc import Sequence

from sjtuclaw.application.autostart_service import AUTOSTART_ARGUMENT


class StartupModeArgumentError(ValueError):
    """Raised without retaining or displaying an unsupported argument."""

    def __init__(self) -> None:
        super().__init__("The application startup arguments are invalid.")


def parse_startup_mode(argv: Sequence[str]) -> bool:
    """Accept only the ordinary launch or the fixed ``--startup`` mode."""

    arguments = tuple(argv)
    if not arguments:
        return False
    options = arguments[1:]
    if not options:
        return False
    if options == (AUTOSTART_ARGUMENT,):
        return True
    raise StartupModeArgumentError
