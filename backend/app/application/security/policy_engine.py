from app.domain.ports.policy import Policy
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class PolicyEngine:
    """Evaluates security policies in priority order."""

    def __init__(self, policies: list[Policy]) -> None:
        # Sort policies by priority (highest first)
        self.policies = sorted(policies, key=lambda p: p.priority, reverse=True)

    def evaluate(self, context: TrustContext) -> PolicyResult:
        """Evaluate all policies and return the most restrictive decision."""
        results = []
        
        for policy in self.policies:
            result = policy.evaluate(context)
            results.append(result)
            
            # If a policy is applicable and returns DENY, we can stop
            # DENY always prevails
            if result.applicable and result.decision == PermissionDecision.DENY:
                return result
        
        # Check if any ASK policies exist
        ask_results = [r for r in results if r.applicable and r.decision == PermissionDecision.ASK]
        if ask_results:
            # Return the first ASK result (highest priority)
            return ask_results[0]
        
        # Check if any ALLOW policies exist
        allow_results = [r for r in results if r.applicable and r.decision == PermissionDecision.ALLOW]
        if allow_results:
            # Return the first ALLOW result (highest priority)
            return allow_results[0]
        
        # Default deny if no policies apply
        return PolicyResult.deny(
            "default_deny",
            "No applicable policy found - default deny"
        )

    def add_policy(self, policy: Policy) -> None:
        """Add a new policy and re-sort by priority."""
        self.policies.append(policy)
        self.policies.sort(key=lambda p: p.priority, reverse=True)

    def remove_policy(self, policy_id: str) -> None:
        """Remove a policy by ID."""
        self.policies = [p for p in self.policies if p.policy_id != policy_id]
