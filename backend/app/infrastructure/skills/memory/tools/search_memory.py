from app.application.memory.search_memories import SearchMemoriesUseCase
from app.application.tools.base import UseCaseTool
from pydantic import Field

from app.domain.entities.memory import Memory
from app.domain.ports.tool import ToolContext, ToolInput, ToolOutput
from app.infrastructure.skills.memory.tools.contracts import (
    SKILL_NAME,
    MemorySummary,
    require_acting_user,
)

MAX_QUERY_LENGTH = 500
MAX_LIMIT = 50

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_QUERY_LENGTH,
            "description": "Natural language search over stored memories",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": "Maximum memories to return"},
    },
    "required": ["query"],
    "additionalProperties": False,
}


class MemorySearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)


class MemorySearchOutput(ToolOutput):
    items: list[MemorySummary]
    count: int


def to_summary(memory: Memory) -> MemorySummary:
    return MemorySummary(
        memory_id=str(memory.id),
        content=memory.content,
        memory_type=memory.memory_type,
        importance=memory.importance,
        created_at=memory.created_at.isoformat(),
    )


class MemorySearchTool(UseCaseTool[MemorySearchInput, MemorySearchOutput]):
    def __init__(self, use_case: SearchMemoriesUseCase) -> None:
        super().__init__(
            name="memory.search",
            description="Search the memories of the current user.",
            skill_name=SKILL_NAME,
            input_model=MemorySearchInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            category="memory",
        )
        self.use_case = use_case

    async def run(self, payload: MemorySearchInput, context: ToolContext) -> MemorySearchOutput:
        user_id = require_acting_user(context)
        memories = self.use_case.execute(
            context.agent_id, user_id, payload.query, limit=payload.limit
        )
        return MemorySearchOutput(items=[to_summary(memory) for memory in memories], count=len(memories))
