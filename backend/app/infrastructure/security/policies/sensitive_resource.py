from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class SensitiveResourcePolicy(Policy):
    """Deny access to sensitive resources like credentials, secrets, etc."""

    SENSITIVE_KEYWORDS = frozenset({
        "credential", "password", "secret", "token", "api_key", "private_key",
        "ssh_key", "auth", "authentication", ".env", "keychain", "vault"
    })

    def evaluate(self, context: TrustContext) -> PolicyResult:
        # Check tool name for sensitive keywords
        tool_lower = context.tool_name.lower()
        skill_lower = context.skill_name.lower()
        
        for keyword in self.SENSITIVE_KEYWORDS:
            if keyword in tool_lower or keyword in skill_lower:
                return PolicyResult.deny(
                    self.policy_id,
                    f"Access to sensitive resource '{context.tool_name}' is prohibited"
                )
        
        # Check arguments for sensitive patterns
        for key, value in context.arguments.items():
            if isinstance(value, str):
                key_lower = key.lower()
                value_lower = value.lower()
                for keyword in self.SENSITIVE_KEYWORDS:
                    if keyword in key_lower or keyword in value_lower:
                        return PolicyResult.deny(
                            self.policy_id,
                            f"Access to sensitive resource is prohibited"
                        )
        
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "sensitive_resource"

    @property
    def priority(self) -> int:
        return 95  # Very high priority - protect sensitive resources
