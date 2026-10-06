from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_context import TrustContext


class HighRiskPolicy(Policy):
    """Deny high-risk actions unless explicitly allowed."""

    def evaluate(self, context: TrustContext) -> PolicyResult:
        if context.risk_level == RiskLevel.HIGH:
            return PolicyResult.deny(
                self.policy_id,
                f"High-risk action '{context.tool_name}' is not allowed"
            )
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "high_risk"

    @property
    def priority(self) -> int:
        return 90  # High priority - deny high risk
