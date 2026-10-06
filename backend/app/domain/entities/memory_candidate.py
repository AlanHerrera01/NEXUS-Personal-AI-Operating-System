from dataclasses import dataclass

from app.domain.entities._common import require_text
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType


@dataclass(frozen=True)
class MemoryCandidate:
    agent_id: EntityId
    content: str
    memory_type: MemoryType
    source: MemorySource
    importance: MemoryImportance
    requested_persistence: MemoryPersistenceDecision = MemoryPersistenceDecision.SAVE
    user_instruction: str = ""
    #: Who asked for this memory. Carried on the candidate so the owner is decided
    #: before persistence rather than patched onto the entity afterwards -- a value
    #: filled in after the fact is a value that can be forgotten.
    user_id: EntityId | None = None

    def __post_init__(self) -> None:
        require_text(self.content, "content")

    def to_memory(self, decision: MemoryPersistenceDecision):
        from app.domain.entities.memory import Memory

        return Memory(
            agent_id=self.agent_id,
            content=self.content,
            memory_type=self.memory_type,
            source=self.source,
            importance=self.importance,
            persistence=decision,
            user_id=self.user_id,
        )
