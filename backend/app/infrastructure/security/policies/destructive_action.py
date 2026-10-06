from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class DestructiveActionPolicy(Policy):
    """Ask or deny destructive actions like delete, drop, destroy, etc."""

    DESTRUCTIVE_KEYWORDS = frozenset({
        "delete", "drop", "destroy", "remove", "truncate", "overwrite",
        "purge", "erase", "clear", "reset", "bulk_delete", "mass_delete"
    })

    def evaluate(self, context: TrustContext) -> PolicyResult:
        # Check tool name for destructive keywords
        tool_lower = context.tool_name.lower()
        
        for keyword in self.DESTRUCTIVE_KEYWORDS:
            if keyword in tool_lower:
                return PolicyResult.ask(
                    self.policy_id,
                    f"Destructive action '{context.tool_name}' requires explicit confirmation"
                )
        
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "destructive_action"

    @property
    def priority(self) -> int:
        return 70  # High priority - protect against destructive actions
