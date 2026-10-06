from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType


class CreateMemoryRequest(BaseModel):
    agent_id: UUID
    content: str = Field(min_length=1, max_length=10000)
    memory_type: MemoryType
    source: MemorySource
    importance: MemoryImportance = MemoryImportance.MEDIUM
    requested_persistence: MemoryPersistenceDecision = MemoryPersistenceDecision.SAVE
    user_instruction: str = Field(default="", max_length=2000)


class SearchMemoryRequest(BaseModel):
    agent_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)


class MemoryResponse(BaseModel):
    id: str
    agent_id: str
    content: str
    memory_type: str
    source: str
    importance: str
    persistence_decision: str


class MemoryDecisionResponse(BaseModel):
    saved: bool
    decision: str
    reason: str
    memory: MemoryResponse | None = None


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
