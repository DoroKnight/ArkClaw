"""Optional PySide6 runtime bridge."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge

__all__ = ["QtRuntimeBridge"]


def __getattr__(name: str) -> object:
    if name != "QtRuntimeBridge":
        raise AttributeError(name)
    from arkclaw.presentation.qt.runtime_bridge import (
        QtRuntimeBridge as _QtRuntimeBridge,
    )

    globals()[name] = _QtRuntimeBridge
    return _QtRuntimeBridge
