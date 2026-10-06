from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import EntityIdArgument, ToolContext, ToolInput, ToolOutput
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.memory.tools.contracts import SKILL_NAME, require_acting_user

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"memory_id": {"type": "string", "description": "Identifier of the memory"}},
    "required": ["memory_id"],
    "additionalProperties": False,
}


class MemoryDeleteInput(ToolInput):
    memory_id: EntityIdArgument


class MemoryDeleteOutput(ToolOutput):
    deleted: bool
    memory_id: str


class MemoryDeleteTool(UseCaseTool[MemoryDeleteInput, MemoryDeleteOutput]):
    def __init__(self, use_case: DeleteMemoryUseCase) -> None:
        super().__init__(
            name="memory.delete",
            description="Delete one memory of the current user.",
            skill_name=SKILL_NAME,
            input_model=MemoryDeleteInput,
            input_schema=INPUT_SCHEMA,
            risk_level=RiskLevel.MEDIUM,
            read_only=False,
            side_effect=True,
            category="memory",
            error_codes={LookupError: ToolErrorCode.MEMORY_NOT_FOUND},
        )
        self.use_case = use_case

    async def run(self, payload: MemoryDeleteInput, context: ToolContext) -> MemoryDeleteOutput:
        user_id = require_acting_user(context)
        if not self.use_case.execute(payload.memory_id, context.agent_id, user_id):
            raise LookupError("memory does not exist")
        return MemoryDeleteOutput(deleted=True, memory_id=str(payload.memory_id))
