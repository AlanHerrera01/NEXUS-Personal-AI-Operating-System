from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class DisabledSkillPolicy(Policy):
    """Deny access to disabled skills."""

    def __init__(self, disabled_skills: frozenset[str] = frozenset()) -> None:
        self._disabled_skills = disabled_skills

    def evaluate(self, context: TrustContext) -> PolicyResult:
        if context.skill_name in self._disabled_skills:
            return PolicyResult.deny(
                self.policy_id,
                f"Skill '{context.skill_name}' is disabled"
            )
        return PolicyResult.not_applicable(self.policy_id)

    @property
    def policy_id(self) -> str:
        return "disabled_skill"

    @property
    def priority(self) -> int:
        return 100  # High priority - deny disabled skills
