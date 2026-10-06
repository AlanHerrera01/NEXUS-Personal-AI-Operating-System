from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision


@dataclass(frozen=True)
class MemoryDecision:
    persistence: MemoryPersistenceDecision
    reason: str


class MemoryPolicy(ABC):
    @abstractmethod
    def evaluate(self, candidate: MemoryCandidate) -> MemoryDecision:
        raise NotImplementedError
