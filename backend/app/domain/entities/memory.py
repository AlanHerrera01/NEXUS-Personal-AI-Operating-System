from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType


@dataclass
class Memory:
    content: str
    memory_type: MemoryType
    persistence: MemoryPersistenceDecision = MemoryPersistenceDecision.SAVE
    agent_id: EntityId | None = None
    #: Who owns this memory. Optional on the entity because rows predate it, but
    #: the firewall refuses to persist a memory without an owner, so every stored
    #: memory has one. A memory with no owner is a memory nobody can be denied.
    user_id: EntityId | None = None
    source: MemorySource = MemorySource.SYSTEM
    importance: MemoryImportance = MemoryImportance.MEDIUM
    id: EntityId = field(default_factory=EntityId.new)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.content, "content")

    @property
    def can_be_persisted(self) -> bool:
        return self.persistence is MemoryPersistenceDecision.SAVE

    @property
    def persistence_decision(self) -> MemoryPersistenceDecision:
        return self.persistence
