from abc import ABC, abstractmethod

from app.domain.entities.proactive_rule import ProactiveRule
from app.domain.value_objects.entity_id import EntityId


class ProactiveRuleRepository(ABC):
    """Persistence for :class:`ProactiveRule`."""

    @abstractmethod
    def save(self, rule: ProactiveRule) -> ProactiveRule:
        """Insert or update the rule and return the stored state."""

    @abstractmethod
    def get_by_id(self, rule_id: EntityId) -> ProactiveRule | None: ...

    @abstractmethod
    def list_by_user(
        self, user_id: EntityId, enabled_only: bool = False, limit: int = 100
    ) -> list[ProactiveRule]:
        """Rules owned by ``user_id``, newest first."""

    @abstractmethod
    def count_by_user(self, user_id: EntityId) -> int:
        """Total rules for the user, used to enforce the per-user quota."""

    @abstractmethod
    def delete(self, rule_id: EntityId) -> None:
        """Remove the rule outright."""