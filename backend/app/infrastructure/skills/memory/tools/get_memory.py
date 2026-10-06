from app.application.memory.get_memory import GetMemoryUseCase
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import EntityIdArgument, ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.memory.tools.contracts import (
    SKILL_NAME,
    MemorySummary,
    require_acting_user,
)
from app.infrastructure.skills.memory.tools.search_memory import to_summary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"memory_id": {"type": "string", "description": "Identifier of the memory"}},
    "required": ["memory_id"],
    "additionalProperties": False,
}


class MemoryGetInput(ToolInput):
    memory_id: EntityIdArgument


class MemoryGetTool(UseCaseTool[MemoryGetInput, MemorySummary]):
    def __init__(self, use_case: GetMemoryUseCase) -> None:
        super().__init__(
            name="memory.get",
            description="Get one memory of the current user by identifier.",
            skill_name=SKILL_NAME,
            input_model=MemoryGetInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            category="memory",
            error_codes={LookupError: ToolErrorCode.MEMORY_NOT_FOUND},
        )
        self.use_case = use_case

    async def run(self, payload: MemoryGetInput, context: ToolContext) -> MemorySummary:
        user_id = require_acting_user(context)
        memory = self.use_case.execute(payload.memory_id, context.agent_id, user_id)
        if memory is None:
            raise LookupError("memory does not exist")
        return to_summary(memory)
