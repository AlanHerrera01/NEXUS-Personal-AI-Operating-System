from abc import ABC, abstractmethod

from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.entity_id import EntityId


class AgentRunRepository(ABC):
    """Persistence port for agent runs.

    ``user_id`` on the reads is what makes resume and status endpoints safe. The
    run id arrives from the URL, so without an owner comparison a caller who
    guessed or listed a run id could read another user's request text and drive
    their run's state machine.
    """

    @abstractmethod
    def save(self, agent_run: AgentRun) -> AgentRun:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, agent_run_id: EntityId, user_id: EntityId) -> AgentRun | None:
        """The run, or None if it does not exist or is not owned by ``user_id``."""
        raise NotImplementedError