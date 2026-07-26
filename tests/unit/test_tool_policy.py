from datetime import UTC, datetime, timedelta

from sjtuclaw.domain.models import (
    ApprovalRecord,
    ExecutionContext,
    PolicyOutcome,
    ToolCall,
    ToolRisk,
    ToolSpec,
)
from sjtuclaw.domain.policies import DefaultToolPolicy


def _call(
    *,
    call_id: str = "call-1",
    name: str = "open_url",
    arguments: dict[str, object] | None = None,
) -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name=name,
        arguments=dict(arguments or {"url": "https://example.test"}),
    )


def _approval(
    call: ToolCall,
    *,
    turn_id: str = "turn",
    expires_at: datetime | None = None,
) -> ApprovalRecord:
    return ApprovalRecord.for_call(
        turn_id=turn_id,
        call=call,
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
    )


def _context(
    *,
    turn_id: str = "turn",
    approval: ApprovalRecord | None = None,
) -> ExecutionContext:
    return ExecutionContext(turn_id=turn_id, session_id="session", approval=approval)


def test_safe_tool_is_allowed() -> None:
    spec = ToolSpec("clock", "Get time", {}, ToolRisk.SAFE)

    decision = DefaultToolPolicy().evaluate(
        spec,
        _call(name="clock", arguments={}),
        _context(),
    )

    assert decision.outcome is PolicyOutcome.ALLOW


def test_tool_name_mismatch_is_denied() -> None:
    spec = ToolSpec("clock", "Get time", {}, ToolRisk.SAFE)

    decision = DefaultToolPolicy().evaluate(spec, _call(name="shell"), _context())

    assert decision.outcome is PolicyOutcome.DENY


def test_side_effect_requires_approval() -> None:
    call = _call()
    spec = ToolSpec(call.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)

    decision = DefaultToolPolicy().evaluate(spec, call, _context())

    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL


def test_legacy_approved_flag_does_not_authorize_a_call() -> None:
    call = _call()
    spec = ToolSpec(call.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)
    context = ExecutionContext(turn_id="turn", session_id="session", approved=True)

    decision = DefaultToolPolicy().evaluate(spec, call, context)

    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL


def test_exact_approval_allows_side_effect() -> None:
    call = _call()
    spec = ToolSpec(call.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)

    decision = DefaultToolPolicy().evaluate(
        spec,
        call,
        _context(approval=_approval(call)),
    )

    assert decision.outcome is PolicyOutcome.ALLOW


def test_approval_rejects_modified_arguments() -> None:
    original = _call(arguments={"url": "https://safe.example"})
    modified = _call(arguments={"url": "https://other.example"})
    spec = ToolSpec(original.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)

    decision = DefaultToolPolicy().evaluate(
        spec,
        modified,
        _context(approval=_approval(original)),
    )

    assert decision.outcome is PolicyOutcome.DENY


def test_approval_rejects_cross_turn_replay() -> None:
    call = _call()
    spec = ToolSpec(call.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)

    decision = DefaultToolPolicy().evaluate(
        spec,
        call,
        _context(turn_id="turn-2", approval=_approval(call, turn_id="turn-1")),
    )

    assert decision.outcome is PolicyOutcome.DENY


def test_approval_rejects_different_call_id() -> None:
    original = _call(call_id="call-1")
    replay = _call(call_id="call-2")
    spec = ToolSpec(original.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)

    decision = DefaultToolPolicy().evaluate(
        spec,
        replay,
        _context(approval=_approval(original)),
    )

    assert decision.outcome is PolicyOutcome.DENY


def test_expired_approval_is_denied() -> None:
    call = _call()
    spec = ToolSpec(call.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)
    expired = _approval(call, expires_at=datetime.now(UTC) - timedelta(seconds=1))

    decision = DefaultToolPolicy().evaluate(spec, call, _context(approval=expired))

    assert decision.outcome is PolicyOutcome.DENY


def test_consumed_approval_is_denied() -> None:
    call = _call()
    spec = ToolSpec(call.name, "Open URL", {}, ToolRisk.SIDE_EFFECT)

    decision = DefaultToolPolicy().evaluate(
        spec,
        call,
        _context(approval=_approval(call).consume()),
    )

    assert decision.outcome is PolicyOutcome.DENY


def test_destructive_tool_is_denied_even_when_approved() -> None:
    call = _call(name="shell", arguments={"command": "whoami"})
    spec = ToolSpec(call.name, "Run shell", {}, ToolRisk.DESTRUCTIVE)

    decision = DefaultToolPolicy().evaluate(
        spec,
        call,
        _context(approval=_approval(call)),
    )

    assert decision.outcome is PolicyOutcome.DENY
