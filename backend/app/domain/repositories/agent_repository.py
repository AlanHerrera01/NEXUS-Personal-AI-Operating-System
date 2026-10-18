from abc import ABC, abstractmethod

from app.domain.entities.agent import Agent
from app.domain.value_objects.entity_id import EntityId


class AgentRepository(ABC):
    """Persistence port for agents.

    Reads take the owner for the same reason memory reads do: an agent id in a
    request body is caller-supplied, so without an owner check it names any
    agent on the deployment rather than one belonging to the caller.
    """

    @abstractmethod
    def save(self, agent: Agent) -> Agent:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, agent_id: EntityId, user_id: EntityId) -> Agent | None:
        """The agent, or None if it does not exist or is not owned by ``user_id``."""
        raise NotImplementedError

    @abstractmethod
    def list_by_user(self, user_id: EntityId) -> list[Agent]:
        """Every agent owned by ``user_id``, oldest first.

        The order is part of the contract rather than an implementation detail:
        the dashboard treats the first ACTIVE agent as *the* active agent, so
        returning them in whatever order the table happens to yield would make
        that choice unstable.
        """
        raise NotImplementedError