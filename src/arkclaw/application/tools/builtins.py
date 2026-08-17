"""Built-in safe desktop tools for the ArkClaw Agent Runtime."""

from __future__ import annotations

import ast
import operator
import platform
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from arkclaw.domain.models import (
    ExecutionContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)


class DateTimeTool:
    """Return the current local time, UTC timestamp, and day of week."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_current_time",
            description="Get the current date, local time, and UTC timestamp.",
            input_schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Optional timezone name (defaults to local).",
                    }
                },
                "additionalProperties": False,
            },
            risk=ToolRisk.SAFE,
        )

    async def execute(
        self,
        arguments: dict[str, object],
        context: ExecutionContext,
    ) -> ToolResult:
        now_local = datetime.now()
        now_utc = datetime.now(UTC)
        result_str = (
            f"Local Time: {now_local.strftime('%Y-%m-%d %H:%M:%S (%A)')}\n"
            f"UTC Time: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        return ToolResult(
            call_id=getattr(context, "call_id", "call_time"),
            success=True,
            content=result_str,
        )


class CalculateTool:
    """Safely calculate mathematical expressions using an AST evaluator."""

    _OPERATORS: ClassVar[dict[type[ast.AST], Callable[..., Any]]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculate",
            description="Evaluate a basic math arithmetic expression (e.g. '128 * 4 + 32').",
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate.",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            risk=ToolRisk.SAFE,
        )

    def _eval_node(self, node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            bin_op_type = type(node.op)
            if bin_op_type not in self._OPERATORS:
                raise ValueError(f"Unsupported operator: {bin_op_type.__name__}")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            res = self._OPERATORS[bin_op_type](left, right)
            return float(res) if isinstance(res, float) else int(res)
        if isinstance(node, ast.UnaryOp):
            unary_op_type = type(node.op)
            if unary_op_type not in self._OPERATORS:
                raise ValueError(f"Unsupported operator: {unary_op_type.__name__}")
            operand = self._eval_node(node.operand)
            res = self._OPERATORS[unary_op_type](operand)
            return float(res) if isinstance(res, float) else int(res)
        raise ValueError(f"Unsupported expression syntax: {type(node).__name__}")

    async def execute(
        self,
        arguments: dict[str, object],
        context: ExecutionContext,
    ) -> ToolResult:
        expr = str(arguments.get("expression", "")).strip()
        if not expr:
            return ToolResult(
                call_id=getattr(context, "call_id", "call_calc"),
                success=False,
                content="Error: Empty expression.",
                error_code="invalid_expression",
            )
        try:
            tree = ast.parse(expr, mode="eval")
            result = self._eval_node(tree.body)
            return ToolResult(
                call_id=getattr(context, "call_id", "call_calc"),
                success=True,
                content=f"{expr} = {result}",
            )
        except ZeroDivisionError:
            return ToolResult(
                call_id=getattr(context, "call_id", "call_calc"),
                success=False,
                content="Error: Division by zero.",
                error_code="division_by_zero",
            )
        except Exception as exc:
            return ToolResult(
                call_id=getattr(context, "call_id", "call_calc"),
                success=False,
                content=f"Error evaluating '{expr}': {exc}",
                error_code="evaluation_failed",
            )


class SystemInfoTool:
    """Return non-sensitive system environment and ArkClaw version info."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_system_info",
            description="Get operating system, Python runtime, and desktop environment summary.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            risk=ToolRisk.SAFE,
        )

    async def execute(
        self,
        arguments: dict[str, object],
        context: ExecutionContext,
    ) -> ToolResult:
        del arguments
        info = (
            f"OS: {platform.system()} {platform.release()} ({platform.version()})\n"
            f"Architecture: {platform.machine()}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"App: ArkClaw v0.1.0"
        )
        return ToolResult(
            call_id=getattr(context, "call_id", "call_sysinfo"),
            success=True,
            content=info,
        )


class PetControlTool:
    """Request a desktop pet action or posture change."""

    def __init__(self, action_trigger: Any = None) -> None:
        self._action_trigger = action_trigger

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="pet_action_control",
            description="Trigger a desktop pet action (e.g. 'sit', 'relax', 'sleep').",
            input_schema={
                "type": "object",
                "properties": {
                    "action_name": {
                        "type": "string",
                        "description": "Name of the action to trigger (e.g. 'sit', 'relax').",
                    }
                },
                "required": ["action_name"],
                "additionalProperties": False,
            },
            risk=ToolRisk.SAFE,
        )

    async def execute(
        self,
        arguments: dict[str, object],
        context: ExecutionContext,
    ) -> ToolResult:
        action_name = str(arguments.get("action_name", "")).strip().lower()
        if not action_name:
            return ToolResult(
                call_id=getattr(context, "call_id", "call_pet"),
                success=False,
                content="Error: action_name is required.",
                error_code="missing_action_name",
            )
        if callable(self._action_trigger):
            try:
                self._action_trigger(action_name)
                return ToolResult(
                    call_id=getattr(context, "call_id", "call_pet"),
                    success=True,
                    content=f"Triggered desktop pet action: {action_name}",
                )
            except Exception as exc:
                return ToolResult(
                    call_id=getattr(context, "call_id", "call_pet"),
                    success=False,
                    content=f"Failed to trigger pet action '{action_name}': {exc}",
                    error_code="trigger_failed",
                )
        return ToolResult(
            call_id=getattr(context, "call_id", "call_pet"),
            success=True,
            content=f"Pet action command accepted: {action_name}",
        )
