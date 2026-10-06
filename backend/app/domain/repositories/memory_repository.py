from abc import ABC, abstractmethod

from app.domain.entities.memory import Memory
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_type import MemoryType


class MemoryRepository(ABC):
    """Persistence port for memories.

    Every read and write takes a ``user_id``. That is the whole point of this
    interface as it now stands: the port cannot be implemented in a way that
    answers a query without knowing whose data is being asked for. An IDOR here
    is not a missing check in one method, it is unrepresentable.

    ``user_id`` is required rather than optional. An optional owner on a read
    means "return everything when the caller does not care", which is exactly the
    default that produced cross-user reads.
    """

    @abstractmethod
    def save(self, memory: Memory) -> Memory:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, memory_id: EntityId, user_id: EntityId) -> Memory | None:
        """The memory, or None if it does not exist *or* is owned by someone else.

        None rather than a sentinel or an exception: "not yours" and "does not
        exist" are the same answer to a caller, and making them distinguishable
        is what turns this into an existence oracle.
        """
        raise NotImplementedError

    @abstractmethod
    def list_by_agent(
        self, agent_id: EntityId, user_id: EntityId, limit: int = 100
    ) -> list[Memory]:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        agent_id: EntityId,
        user_id: EntityId,
        query: str,
        limit: int = 10,
        memory_types: set[MemoryType] | None = None,
    ) -> list[Memory]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, memory_id: EntityId, agent_id: EntityId, user_id: EntityId) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_agent(self, agent_id: EntityId, user_id: EntityId) -> int:
        raise NotImplementedError