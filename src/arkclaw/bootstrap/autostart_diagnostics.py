"""Strict, side-effect-free packaged autostart runtime diagnostics."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import TextIO

from arkclaw.application.system.startup_mode import (
    AUTOSTART_DIAGNOSTIC_ARGUMENT,
)
from arkclaw.bootstrap.autostart import (
    diagnose_production_autostart_eligibility,
)

_DIAGNOSTIC_SAFE_CODE = "autostart_runtime_diagnostic_complete"


def is_autostart_runtime_diagnostic_requested(
    argv: Sequence[str],
) -> bool:
    """Match only the single fixed diagnostic argument."""

    arguments = tuple(argv)
    return len(arguments) >= 2 and arguments[1:] == (
        AUTOSTART_DIAGNOSTIC_ARGUMENT,
    )


def write_autostart_runtime_diagnostic(stream: TextIO) -> int:
    """Write one bounded JSON object containing only fixed values."""

    result = diagnose_production_autostart_eligibility()
    payload = {
        "autostart_runtime_diagnostic": True,
        "reason": result.reason.value,
        "safe_code": _DIAGNOSTIC_SAFE_CODE,
        "schema_version": 1,
        "supported": result.supported,
    }
    stream.write(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    stream.write("\n")
    return 0


def run_autostart_runtime_diagnostic_if_requested(
    argv: Sequence[str],
    *,
    stream: TextIO | None = None,
) -> int | None:
    """Return ``None`` for normal startup without constructing runtime objects."""

    if not is_autostart_runtime_diagnostic_requested(argv):
        return None
    return write_autostart_runtime_diagnostic(
        sys.stdout if stream is None else stream
    )
