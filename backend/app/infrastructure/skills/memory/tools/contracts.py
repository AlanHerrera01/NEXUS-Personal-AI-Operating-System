from app.application.tools.errors import ToolExecutionError
from app.domain.ports.tool import ToolContext, ToolOutput
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_type import MemoryType
from app.domain.value_objects.tool_error_code import ToolErrorCode

SKILL_NAME = "memory"


class MemorySummary(ToolOutput):
    memory_id: str
    content: str
    memory_type: MemoryType
    importance: MemoryImportance | None = None
    created_at: str | None = None


def require_acting_user(context: ToolContext) -> EntityId:
    """The owner every memory read and write is scoped to.

    ``ToolContext.user_id`` is optional on the dataclass, so a caller that
    constructs a context by hand -- a test, a future always-on job, anything not
    going through the orchestrator -- can produce one with no identity at all. If
    the memory tools treated that as "no filter", the owner requirement would
    hold everywhere except on the paths nobody exercised. Refusing here keeps the
    unscoped read unrepresentable regardless of who builds the context.
    """
    if context.user_id is None:
        raise ToolExecutionError(
            ToolErrorCode.FORBIDDEN_ARGUMENTS,
            "memory tools require an authenticated user on the tool context",
        )
    return context.user_id
