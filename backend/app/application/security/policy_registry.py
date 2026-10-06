from app.application.security.policy_engine import PolicyEngine
from app.domain.ports.policy import Policy
from app.infrastructure.security.policies.destructive_action import DestructiveActionPolicy
from app.infrastructure.security.policies.disabled_skill import DisabledSkillPolicy
from app.infrastructure.security.policies.high_risk import HighRiskPolicy
from app.infrastructure.security.policies.low_readonly import LowReadonlyPolicy
from app.infrastructure.security.policies.low_risk import LowRiskPolicy
from app.infrastructure.security.policies.medium_risk import MediumRiskPolicy
from app.infrastructure.security.policies.permission import PermissionPolicy
from app.infrastructure.security.policies.sensitive_resource import SensitiveResourcePolicy
from app.infrastructure.security.policies.unknown_tool import UnknownToolPolicy


class PolicyRegistry:
    """Registry and factory for security policies."""

    def __init__(
        self,
        permission_checker=None,
        disabled_skills: frozenset[str] = frozenset(),
        permission_resolver=None,
    ) -> None:
        self.permission_checker = permission_checker
        self.disabled_skills = disabled_skills
        self.permission_resolver = permission_resolver

    def create_default_policies(self) -> list[Policy]:
        """Create the default set of security policies."""
        # The permission policy is always present. Previously it was built only
        # when a checker was supplied, and the HTTP wiring supplied none, so
        # permission grants never reached a decision. Absent a repository it now
        # abstains rather than denying everything -- see PermissionPolicy for why
        # the two are different and which one owns default-deny.
        if self.permission_resolver is not None or self.permission_checker is not None:
            permission_policy = PermissionPolicy(
                self.permission_checker, self.permission_resolver
            )
        else:
            permission_policy = None

        policies = [
            UnknownToolPolicy(),
            DisabledSkillPolicy(self.disabled_skills),
            SensitiveResourcePolicy(),
            HighRiskPolicy(),
            permission_policy,
            DestructiveActionPolicy(),
            MediumRiskPolicy(),
            LowReadonlyPolicy(),
            LowRiskPolicy(),
        ]
        # Filter out None policies
        return [p for p in policies if p is not None]

    def create_policy_engine(self) -> PolicyEngine:
        """Create a PolicyEngine with default policies."""
        policies = self.create_default_policies()
        return PolicyEngine(policies)

    def create_custom_policy_engine(self, policies: list[Policy]) -> PolicyEngine:
        """Create a PolicyEngine with custom policies."""
        return PolicyEngine(policies)
