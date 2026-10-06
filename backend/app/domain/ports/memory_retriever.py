from abc import ABC, abstractmethod
from app.domain.entities.memory import Memory
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_type import MemoryType


class MemoryRetriever(ABC):
    """Read-side port for pulling memories into a prompt.

    ``user_id`` is a required argument rather than an optional filter. Retrieval
    is the highest-consequence read in the system: whatever comes back here is
    spliced into the model's context and can steer a decision. A retriever that
    can be called without an owner is a retriever that can be asked for everyone.
    """

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