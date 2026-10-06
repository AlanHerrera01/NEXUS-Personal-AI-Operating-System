from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.ports.tool import ToolContext, ToolInput, ToolOutput
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.memory.tools.contracts import SKILL_NAME, require_acting_user

MAX_CONTENT_LENGTH = 4_000

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "Fact worth remembering, written in third person"},
        "memory_type": {
            "type": "string",
            "enum": ["EPISODIC", "SEMANTIC", "PREFERENCE"],
            "description": "Kind of memory to store",
        },
        "importance": {
            "type": ["string", "null"],
            "enum": ["LOW", "MEDIUM", "HIGH", None],
            "description": "How relevant the memory is",
        },
    },
    "required": ["content", "memory_type"],
    "additionalProperties": False,
}


class MemorySaveInput(ToolInput):
    content: str
    memory_type: MemoryType
    importance: MemoryImportance = MemoryImportance.MEDIUM


class MemorySaveOutput(ToolOutput):
    saved: bool
    persistence: str
    reason: str
    memory_id: str | None = None


class MemorySaveTool(UseCaseTool[MemorySaveInput, MemorySaveOutput]):
    """Writes through MemoryService so MemoryPolicy and MemoryFirewall always run."""

    def __init__(self, use_case: SaveMemoryUseCase) -> None:
        super().__init__(
            name="memory.save",
            description="Store a memory about the user. The memory policy decides whether it is persisted.",
            skill_name=SKILL_NAME,
            input_model=MemorySaveInput,
            input_schema=INPUT_SCHEMA,
            # LOW, not MEDIUM: this writes only into NEXUS's own memory, scoped
            # to the calling agent, and is reversible. Whether the candidate is
            # actually persisted is decided by MemoryPolicy and MemoryFirewall,
            # which run inside the use case. Rating it MEDIUM made the agent
            # require a human before it could remember anything, which defeats
            # the point of a personal assistant. memory.delete stays MEDIUM
            # because forgetting is genuinely destructive.
            risk_level=RiskLevel.LOW,
            read_only=False,
            side_effect=True,
            category="memory",
        )
        self.use_case = use_case

    async def run(self, payload: MemorySaveInput, context: ToolContext) -> MemorySaveOutput:
        if len(payload.content) > MAX_CONTENT_LENGTH:
            raise ValueError(f"content must be at most {MAX_CONTENT_LENGTH} characters")
        candidate = MemoryCandidate(
            agent_id=context.agent_id,
            content=payload.content,
            memory_type=payload.memory_type,
            source=MemorySource.AGENT_ACTION,
            importance=payload.importance,
            user_instruction=context.user_request,
            # Ownership is taken from the context, never inferred. Without it the
            # firewall would refuse the write outright, which is the correct
            # outcome but surfaces to the model as a blocked tool rather than as
            # the identity bug it actually is.
            user_id=require_acting_user(context),
        )
        try:
            evaluation = self.use_case.execute(candidate)
        except ValueError as error:
            raise ToolExecutionError(
                ToolErrorCode.MEMORY_BLOCKED, "memory rejected by the memory firewall"
            ) from error
        if evaluation.memory is None:
            return MemorySaveOutput(
                saved=False,
                persistence=evaluation.decision.persistence.value,
                reason=evaluation.decision.reason,
            )
        return MemorySaveOutput(
            saved=True,
            persistence=evaluation.decision.persistence.value,
            reason=evaluation.decision.reason,
            memory_id=str(evaluation.memory.id),
        )
