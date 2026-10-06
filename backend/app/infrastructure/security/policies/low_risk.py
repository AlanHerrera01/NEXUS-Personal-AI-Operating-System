from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_context import TrustContext


class LowRiskPolicy(Policy):
    """Auto-allow low-risk actions, unless the tool asks for confirmation.

    ``LowReadonlyPolicy`` only covers the read-only subset, which left low-risk
    actions with a side effect falling through to the default deny. The risk
    tier is declared by the tool itself, so the engine enforces the tier rather
    than second-guessing every individual tool.

    A tool that declares ``requires_confirmation`` is escalated to ASK here, so
    the flag can never be silently ignored.
    """

    def evaluate(self, context: TrustContext) -> PolicyResult:
        if context.risk_level is not RiskLevel.LOW:
            return PolicyResult.not_applicable(self.policy_id)

        if context.tool_metadata.get("requires_confirmation"):
            return PolicyResult.ask(
                self.policy_id,
                f"Action '{context.tool_name}' requires confirmation",
            )

        return PolicyResult.allow(
            self.policy_id,
            f"Low-risk action '{context.tool_name}' is allowed",
        )

    @property
    def policy_id(self) -> str:
        return "low_risk"

    @property
    def priority(self) -> int:
        # Below LowReadonlyPolicy so the more specific read-only rule is the one
        # that explains the decision.
        return 5