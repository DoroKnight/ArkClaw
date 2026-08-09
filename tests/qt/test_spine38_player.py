from __future__ import annotations

import inspect

from sjtuclaw.presentation.qt import spine38_player


def test_spine_player_adapter_remains_qt_free() -> None:
    """The serialized player seam must not acquire QObject/thread affinity."""

    source = inspect.getsource(spine38_player)
    assert "PySide6" not in source
    assert "QTimer" not in source
