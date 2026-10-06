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
