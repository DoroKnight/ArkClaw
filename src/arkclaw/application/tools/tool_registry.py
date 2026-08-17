"""Tool registry and catalog for the ArkClaw Agent Runtime."""

from __future__ import annotations

from typing import Any

from arkclaw.application.tools.builtins import (
    CalculateTool,
    DateTimeTool,
    PetControlTool,
    SystemInfoTool,
)
from arkclaw.domain.models import ToolSpec
from arkclaw.domain.ports import Tool


class ToolRegistry:
    """Registry holding model-visible tools and their implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        spec = tool.spec()
        if not spec.name:
            raise ValueError("Tool name must not be empty.")
        self._tools[spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec() for tool in self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def create_default_tool_registry(
    *,
    pet_action_trigger: Any = None,
) -> ToolRegistry:
    """Create a default ToolRegistry pre-populated with safe built-in tools."""
    registry = ToolRegistry()
    registry.register(DateTimeTool())
    registry.register(CalculateTool())
    registry.register(SystemInfoTool())
    registry.register(PetControlTool(pet_action_trigger))
    return registry
