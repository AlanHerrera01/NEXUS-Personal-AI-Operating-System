from dataclasses import dataclass

from app.application.memory.service import MemoryEvaluation, MemoryService
from app.domain.entities.memory_candidate import MemoryCandidate


@dataclass
class SaveMemoryUseCase:
    memory_service: MemoryService

    def execute(self, candidate: MemoryCandidate) -> MemoryEvaluation:
        return self.memory_service.save_memory(candidate)
