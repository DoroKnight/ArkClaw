"""Unit tests for ToolRegistry, built-in tools, and AgentLoop tool execution."""

import asyncio
from unittest.mock import MagicMock

from arkclaw.application.agent.agent_loop import AgentLoop
from arkclaw.application.agent.context_manager import ContextManager
from arkclaw.application.tools.builtins import (
    CalculateTool,
    DateTimeTool,
    PetControlTool,
    SystemInfoTool,
)
from arkclaw.application.tools.tool_registry import (
    ToolRegistry,
    create_default_tool_registry,
)
from arkclaw.domain.events import AgentEventType, LLMEvent
from arkclaw.domain.models import (
    ExecutionContext,
    PolicyDecision,
    PolicyOutcome,
    ToolCall,
    ToolRisk,
    UserMessageCommand,
)


def test_date_time_tool_executes() -> None:
    async def scenario() -> None:
        tool = DateTimeTool()
        spec = tool.spec()
        assert spec.name == "get_current_time"
        assert spec.risk is ToolRisk.SAFE
        context = ExecutionContext(turn_id="t1", session_id="s1")
        result = await tool.execute({}, context)
        assert result.success is True
        assert "Local Time:" in result.content
        assert "UTC Time:" in result.content

    asyncio.run(scenario())


def test_calculate_tool_executes() -> None:
    async def scenario() -> None:
        tool = CalculateTool()
        context = ExecutionContext(turn_id="t1", session_id="s1")
        result = await tool.execute({"expression": "100 * 2 + 50 / 2"}, context)
        assert result.success is True
        assert "225" in result.content

        err_result = await tool.execute({"expression": "10 / 0"}, context)
        assert err_result.success is False
        assert err_result.error_code == "division_by_zero"

    asyncio.run(scenario())


def test_system_info_tool_executes() -> None:
    async def scenario() -> None:
        tool = SystemInfoTool()
        context = ExecutionContext(turn_id="t1", session_id="s1")
        result = await tool.execute({}, context)
        assert result.success is True
        assert "OS:" in result.content
        assert "Python:" in result.content
        assert "ArkClaw" in result.content

    asyncio.run(scenario())


def test_pet_control_tool_executes() -> None:
    async def scenario() -> None:
        triggered_actions = []

        def on_pet_action(name: str) -> None:
            triggered_actions.append(name)

        tool = PetControlTool(on_pet_action)
        context = ExecutionContext(turn_id="t1", session_id="s1")
        result = await tool.execute({"action_name": "sit"}, context)
        assert result.success is True
        assert triggered_actions == ["sit"]

    asyncio.run(scenario())


def test_default_tool_registry_contains_builtins() -> None:
    registry = create_default_tool_registry()
    assert len(registry) == 4
    assert "get_current_time" in registry
    assert "calculate" in registry
    assert "get_system_info" in registry
    assert "pet_action_control" in registry
    specs = registry.list_specs()
    assert len(specs) == 4


def test_agent_loop_executes_registered_tool() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()
        registry.register(CalculateTool())

        fake_provider = MagicMock()
        fake_provider.name = "fake"

        call = ToolCall(
            call_id="call-123",
            name="calculate",
            arguments={"expression": "42 * 2"},
        )

        async def fake_stream(request):
            yield LLMEvent.call_tool(call)
            yield LLMEvent.completed()

        fake_provider.generate_stream = fake_stream

        agent_loop = AgentLoop(
            provider=fake_provider,
            context_manager=ContextManager(),
            tool_registry=registry,
        )

        command = UserMessageCommand.create("What is 42 * 2?")
        events = [event async for event in agent_loop.run(command)]

        types = [e.type for e in events]
        assert AgentEventType.TOOL_STARTED in types
        assert AgentEventType.TOOL_FINISHED in types
        assert AgentEventType.TURN_COMPLETED in types

        finished_event = next(
            e for e in events if e.type == AgentEventType.TOOL_FINISHED
        )
        assert "84" in finished_event.text

    asyncio.run(scenario())


def test_agent_loop_respects_denied_tool_policy() -> None:
    async def scenario() -> None:
        registry = ToolRegistry()
        registry.register(CalculateTool())

        mock_policy = MagicMock()
        mock_policy.evaluate.return_value = PolicyDecision(
            outcome=PolicyOutcome.DENY,
            reason="Blocked by security policy.",
        )

        fake_provider = MagicMock()
        fake_provider.name = "fake"

        call = ToolCall(
            call_id="call-456",
            name="calculate",
            arguments={"expression": "1 + 1"},
        )

        async def fake_stream(request):
            yield LLMEvent.call_tool(call)

        fake_provider.generate_stream = fake_stream

        agent_loop = AgentLoop(
            provider=fake_provider,
            context_manager=ContextManager(),
            tool_registry=registry,
            tool_policy=mock_policy,
        )

        command = UserMessageCommand.create("calculate 1 + 1")
        events = [event async for event in agent_loop.run(command)]

        types = [e.type for e in events]
        assert AgentEventType.TURN_FAILED in types
        failed_event = next(e for e in events if e.type == AgentEventType.TURN_FAILED)
        assert failed_event.error_code == "tool_denied"

    asyncio.run(scenario())
