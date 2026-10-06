from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class UnknownToolPolicy(Policy):
    """Deny access to unknown tools."""

    def evaluate(self, context: TrustContext) -> PolicyResult:
        # This policy is applied when the tool is not in the registry
        # The check for unknown tools happens before policy evaluation
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "unknown_tool"

    @property
    def priority(self) -> int:
        return 100  # High priority - deny unknown tools
