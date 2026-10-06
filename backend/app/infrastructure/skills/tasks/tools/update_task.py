from datetime import datetime

from pydantic import Field

from app.application.tasks.errors import TaskNotFoundError, TaskTransitionError
from app.application.tasks.update_task import UpdateTaskUseCase
from app.application.tasks.validation import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import EntityIdArgument, ToolContext, ToolInput
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.task_status import TaskStatus
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.tasks.tools.contracts import SKILL_NAME, TaskSummary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "Identifier of the task"},
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_TITLE_LENGTH,
            "description": "New task title",
        },
        "description": {
            "type": "string",
            "maxLength": MAX_DESCRIPTION_LENGTH,
            "description": "New task description",
        },
        "due_date": {"type": ["string", "null"], "description": "New ISO-8601 date or null to clear"},
        "status": {
            "type": ["string", "null"],
            "enum": ["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED", None],
            "description": "New task status",
        },
    },
    "required": ["task_id"],
    "additionalProperties": False,
}


class TaskUpdateInput(ToolInput):
    task_id: EntityIdArgument
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    due_date: datetime | None = None
    status: TaskStatus | None = None

    def provided_fields(self) -> set[str]:
        return self.model_fields_set - {"task_id"}


class TaskUpdateTool(UseCaseTool[TaskUpdateInput, TaskSummary]):
    def __init__(self, repository: TaskRepository) -> None:
        super().__init__(
            name="task.update",
            description="Update title, description, due date or status of a task.",
            skill_name=SKILL_NAME,
            input_model=TaskUpdateInput,
            input_schema=INPUT_SCHEMA,
            read_only=False,
            side_effect=True,
            category="tasks",
            error_codes={
                TaskNotFoundError: ToolErrorCode.TASK_NOT_FOUND,
                TaskTransitionError: ToolErrorCode.TASK_TRANSITION_INVALID,
            },
        )
        self.use_case = UpdateTaskUseCase(repository)

    async def run(self, payload: TaskUpdateInput, context: ToolContext) -> TaskSummary:
        changes: dict[str, object] = {
            "agent_id": context.agent_id,
            "task_id": payload.task_id,
        }
        for field_name in payload.provided_fields():
            changes[field_name] = getattr(payload, field_name)
        task = self.use_case.execute(**changes)
        return TaskSummary(
            task_id=str(task.id),
            title=task.title,
            description=task.description,
            status=task.status,
            due_date=task.due_date,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
