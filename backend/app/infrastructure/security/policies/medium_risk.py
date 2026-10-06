from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_context import TrustContext


class MediumRiskPolicy(Policy):
    """Ask for confirmation on medium-risk actions."""

    def evaluate(self, context: TrustContext) -> PolicyResult:
        if context.risk_level == RiskLevel.MEDIUM:
            return PolicyResult.ask(
                self.policy_id,
                f"Medium-risk action '{context.tool_name}' requires confirmation"
            )
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "medium_risk"

    @property
    def priority(self) -> int:
        return 50  # Medium priority
