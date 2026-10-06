from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_context import TrustContext


class LowReadonlyPolicy(Policy):
    """Allow low-risk read-only actions without confirmation."""

    def evaluate(self, context: TrustContext) -> PolicyResult:
        if context.risk_level == RiskLevel.LOW and context.read_only:
            return PolicyResult.allow(
                self.policy_id,
                f"Low-risk read-only action '{context.tool_name}' is allowed"
            )
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "low_readonly"

    @property
    def priority(self) -> int:
        return 10  # Low priority - allow safe actions
