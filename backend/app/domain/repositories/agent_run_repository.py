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

    @abstractmethod
    def delete(self, agent_run_id: EntityId, user_id: EntityId) -> bool:
        """Delete the run and what hangs off it, if it belongs to ``user_id``.

        Scoped by owner for the same reason the reads are: the run id arrives
        from a URL, so an unscoped delete would let any caller erase another
        user's history. Returns True when a run was deleted, False when it did
        not exist or was not owned.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_conversation(
        self, conversation_id: EntityId, user_id: EntityId
    ) -> list[AgentRun]:
        """The conversation's runs, oldest first.

        Owner-scoped like the other reads: the conversation id arrives from a
        URL, so an unscoped query would hand back another user's exchanges.
        Oldest first because the caller rebuilds the thread in the order it was
        written.
        """
        raise NotImplementedError