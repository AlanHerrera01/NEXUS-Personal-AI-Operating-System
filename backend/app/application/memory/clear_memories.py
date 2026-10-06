from dataclasses import dataclass

from app.application.memory.service import MemoryService
from app.domain.value_objects.entity_id import EntityId


@dataclass
class ClearMemoriesUseCase:
    memory_service: MemoryService

    def execute(self, agent_id: EntityId, user_id: EntityId) -> int:
        return self.memory_service.clear_memories(agent_id, user_id)
