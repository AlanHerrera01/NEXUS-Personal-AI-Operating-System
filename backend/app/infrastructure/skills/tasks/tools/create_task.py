from datetime import datetime

from pydantic import Field

from app.application.tasks.create_task import CreateTaskUseCase
from app.application.tasks.validation import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.repositories.task_repository import TaskRepository
from app.infrastructure.skills.tasks.tools.contracts import SKILL_NAME, TaskSummary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_TITLE_LENGTH,
            "description": "Short task title",
        },
        "description": {
            "type": "string",
            "maxLength": MAX_DESCRIPTION_LENGTH,
            "description": "Optional task description",
        },
        "due_date": {"type": ["string", "null"], "description": "Optional ISO-8601 date"},
    },
    "required": ["title"],
    "additionalProperties": False,
}


class TaskCreateInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    due_date: datetime | None = None


class TaskCreateTool(UseCaseTool[TaskCreateInput, TaskSummary]):
    def __init__(self, repository: TaskRepository) -> None:
        super().__init__(
            name="task.create",
            description="Create a task for the current user.",
            skill_name=SKILL_NAME,
            input_model=TaskCreateInput,
            input_schema=INPUT_SCHEMA,
            read_only=False,
            side_effect=True,
            category="tasks",
        )
        self.use_case = CreateTaskUseCase(repository)

    async def run(self, payload: TaskCreateInput, context: ToolContext) -> TaskSummary:
        task = self.use_case.execute(
            agent_id=context.agent_id,
            title=payload.title,
            description=payload.description,
            due_date=payload.due_date,
        )
        return TaskSummary(
            task_id=str(task.id),
            title=task.title,
            description=task.description,
            status=task.status,
            due_date=task.due_date,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
