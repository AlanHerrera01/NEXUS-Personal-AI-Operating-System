from dataclasses import dataclass

from app.application.memory.service import MemoryService
from app.domain.entities.memory import Memory
from app.domain.value_objects.entity_id import EntityId


@dataclass
class SearchMemoriesUseCase:
    memory_service: MemoryService

    def execute(
        self,
        agent_id: EntityId,
        user_id: EntityId,
        query: str,
        limit: int = 10,
    ) -> list[Memory]:
        return self.memory_service.retrieve_memories(agent_id, user_id, query, limit)
