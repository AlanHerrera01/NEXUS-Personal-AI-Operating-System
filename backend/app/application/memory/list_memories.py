from dataclasses import dataclass

from app.application.memory.service import MemoryService
from app.domain.entities.memory import Memory
from app.domain.value_objects.entity_id import EntityId


@dataclass
class ListMemoriesUseCase:
    memory_service: MemoryService

    def execute(
        self, agent_id: EntityId, user_id: EntityId, limit: int = 100
    ) -> list[Memory]:
        return self.memory_service.list_memories(agent_id, user_id, limit)
