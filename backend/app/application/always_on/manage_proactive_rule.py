"""Managing the rules that let NEXUS speak first.

Same ownership discipline as the job use cases: every read is scoped to
``user_id`` and a miss is indistinguishable from a non-existent id.
"""

from dataclasses import dataclass

from app.application.always_on.errors import ProactiveRuleNotFound
from app.domain.entities.proactive_rule import ProactiveRule, ProactiveRuleError
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.proactive_rule_repository import ProactiveRuleRepository
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CreateProactiveRuleUseCase:
    proactive_rule_repository: ProactiveRuleRepository
    agent_repository: AgentRepository
    max_rules_per_user: int = 50

    def execute(
        self,
        *,
        user_id: EntityId,
        agent_id: EntityId,
        name: str,
        condition: dict,
        action: dict,
        cooldown_seconds: int = 3_600,
        enabled: bool = True,
    ) -> ProactiveRule:
        existing = self.proactive_rule_repository.count_by_user(user_id)
        if existing >= self.max_rules_per_user:
            raise ProactiveRuleError(
                f"proactive rule limit reached: {existing} of {self.max_rules_per_user}"
            )

        # Owner-scoped, same reason as scheduled jobs: a proactive rule fires
        # unattended, so binding one to somebody else's agent would be a
        # standing invitation rather than a one-off mistake.
        agent = self.agent_repository.get_by_id(agent_id, user_id)
        if agent is None:
            raise ValueError("agent not found")
        if agent.status is not AgentStatus.ACTIVE:
            raise ValueError("inactive agents cannot have proactive rules")

        try:
            rule = ProactiveRule(
                user_id=user_id,
                agent_id=agent_id,
                name=name,
                condition=condition,
                action=action,
                cooldown_seconds=cooldown_seconds,
                enabled=enabled,
            )
        except ProactiveRuleError as error:
            raise ValueError(str(error)) from error

        return self.proactive_rule_repository.save(rule)


@dataclass
class ListProactiveRulesUseCase:
    proactive_rule_repository: ProactiveRuleRepository

    def execute(
        self, user_id: EntityId, enabled_only: bool = False, limit: int = 100
    ) -> list[ProactiveRule]:
        return self.proactive_rule_repository.list_by_user(
            user_id, enabled_only=enabled_only, limit=limit
        )


@dataclass
class GetProactiveRuleUseCase:
    proactive_rule_repository: ProactiveRuleRepository

    def execute(self, rule_id: EntityId, user_id: EntityId) -> ProactiveRule:
        rule = self.proactive_rule_repository.get_by_id(rule_id)
        if rule is None or not rule.is_owned_by(user_id):
            raise ProactiveRuleNotFound(str(rule_id))
        return rule


@dataclass
class SetProactiveRuleEnabledUseCase:
    proactive_rule_repository: ProactiveRuleRepository

    def execute(self, rule_id: EntityId, user_id: EntityId, enabled: bool) -> ProactiveRule:
        rule = GetProactiveRuleUseCase(self.proactive_rule_repository).execute(
            rule_id, user_id
        )
        return self.proactive_rule_repository.save(
            rule.enable() if enabled else rule.disable()
        )


@dataclass
class DeleteProactiveRuleUseCase:
    """Removes a rule outright.

    There is no soft delete and no cancelled status for rules: unlike a job, a
    rule owns nothing, has no execution history and no run to strand, so
    removing the row is the honest operation.
    """

    proactive_rule_repository: ProactiveRuleRepository

    def execute(self, rule_id: EntityId, user_id: EntityId) -> None:
        rule = GetProactiveRuleUseCase(self.proactive_rule_repository).execute(
            rule_id, user_id
        )
        self.proactive_rule_repository.delete(rule.id)