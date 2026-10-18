from abc import ABC, abstractmethod

from app.domain.entities.agent_action import AgentAction
from app.domain.value_objects.entity_id import EntityId


class AgentActionRepository(ABC):
    @abstractmethod
    def save(self, action: AgentAction) -> AgentAction:
        raise NotImplementedError

    @abstractmethod
    def list_by_run(self, agent_run_id: EntityId) -> list[AgentAction]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_for_user(self, user_id: EntityId, limit: int = 200) -> list[AgentAction]:
        """The most recent actions across every run owned by ``user_id``.

        An action carries no owner of its own -- ownership lives on the run it
        belongs to -- so the port takes the user and the implementation joins.
        The filter is part of the query rather than a post-filter: an audit feed
        that fetches every action and then drops the ones that are not the
        caller's is one forgotten line away from showing them.
        """
        raise NotImplementedError
