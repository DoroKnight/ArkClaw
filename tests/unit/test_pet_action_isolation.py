"""Isolation checks for the capability-gated pet action boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from sjtuclaw.application.pet_action_sequence import PetActionName
from sjtuclaw.application.pet_track0 import (
    ActionOutcome,
    AnimationPlayerCapabilities,
)
from sjtuclaw.presentation.qt.pet_window import PlaceholderAnimationPlayer

_ROOT = Path(__file__).parents[2]
_ACTION_SEQUENCE_MODULE = (
    _ROOT / "src" / "sjtuclaw" / "application" / "pet_action_sequence.py"
)
_TRACK0_MODULE = _ROOT / "src" / "sjtuclaw" / "application" / "pet_track0.py"
_PET_WINDOW_MODULE = (
    _ROOT / "src" / "sjtuclaw" / "presentation" / "qt" / "pet_window.py"
)


def _imported_module_names(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return frozenset(names)


def test_placeholder_never_starts_production_sequence() -> None:
    player = PlaceholderAnimationPlayer()

    assert player.capabilities == AnimationPlayerCapabilities(
        False,
        False,
        False,
        False,
    )
    assert player.request(PetActionName.IDLE) is ActionOutcome.LEGACY_DIRECT
    assert player.play_call_count == 0


def test_sequencing_modules_do_not_import_agent_or_provider_layers() -> None:
    forbidden = {"agent_loop", "runtime_bridge", "provider", "secrets", "openai"}

    for path in (_ACTION_SEQUENCE_MODULE, _TRACK0_MODULE, _PET_WINDOW_MODULE):
        imports = _imported_module_names(path)
        assert not any(
            any(part in name for part in forbidden)
            for name in imports
        ), (path, imports)
