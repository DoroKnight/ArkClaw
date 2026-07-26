"""Stable policy defaults for the first Agent milestone."""

from sjtuclaw.domain.models import (
    ExecutionContext,
    PolicyDecision,
    PolicyOutcome,
    ToolCall,
    ToolRisk,
    ToolSpec,
)


class DefaultToolPolicy:
    """Fail-closed permission policy used until approval UI is connected."""

    def evaluate(
        self,
        spec: ToolSpec,
        call: ToolCall,
        context: ExecutionContext,
    ) -> PolicyDecision:
        if spec.name != call.name:
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                reason="The registered tool does not match the requested tool.",
            )

        if spec.risk is ToolRisk.DESTRUCTIVE:
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                reason="Destructive tools are disabled.",
            )
        if spec.risk is ToolRisk.SAFE:
            return PolicyDecision(
                outcome=PolicyOutcome.ALLOW,
                reason="Safe registered tool.",
            )
        if context.approval is not None:
            if context.approval.matches(turn_id=context.turn_id, call=call):
                return PolicyDecision(
                    outcome=PolicyOutcome.ALLOW,
                    reason="The user approved this exact call.",
                )
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                reason="The approval does not match this tool call or is no longer valid.",
            )
        return PolicyDecision(
            outcome=PolicyOutcome.REQUIRE_APPROVAL,
            reason="This tool requires explicit user approval.",
            allow_for_session=spec.risk is ToolRisk.SENSITIVE_READ,
        )
