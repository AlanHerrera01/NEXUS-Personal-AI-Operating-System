from dataclasses import dataclass

from app.application.memory.service import MemoryService
from app.domain.entities.memory import Memory
from app.domain.value_objects.entity_id import EntityId


@dataclass
class GetMemoryUseCase:
    memory_service: MemoryService

    def execute(
        self, memory_id: EntityId, agent_id: EntityId, user_id: EntityId
    ) -> Memory | None:
        return self.memory_service.get_memory(memory_id, agent_id, user_id)
