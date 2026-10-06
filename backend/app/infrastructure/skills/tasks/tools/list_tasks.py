from pydantic import Field

from app.application.tasks.list_tasks import MAX_LIMIT, ListTasksUseCase
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolContext, ToolInput, ToolOutput
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.task_status import TaskStatus
from app.infrastructure.skills.tasks.tools.contracts import SKILL_NAME, TaskSummary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": ["string", "null"],
            "enum": ["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED", None],
            "description": "Optional status filter",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": "Maximum tasks to return"},
    },
    "required": [],
    "additionalProperties": False,
}


class TaskListInput(ToolInput):
    status: TaskStatus | None = None
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)


class TaskListOutput(ToolOutput):
    items: list[TaskSummary]
    count: int


class TaskListTool(UseCaseTool[TaskListInput, TaskListOutput]):
    def __init__(self, repository: TaskRepository) -> None:
        super().__init__(
            name="task.list",
            description="List the tasks of the current user, optionally filtered by status.",
            skill_name=SKILL_NAME,
            input_model=TaskListInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            category="tasks",
        )
        self.use_case = ListTasksUseCase(repository)

    async def run(self, payload: TaskListInput, context: ToolContext) -> TaskListOutput:
        tasks = self.use_case.execute(
            agent_id=context.agent_id,
            status=payload.status,
            limit=payload.limit,
        )
        return TaskListOutput(
            items=[
                TaskSummary(
                    task_id=str(task.id),
                    title=task.title,
                    description=task.description,
                    status=task.status,
                    due_date=task.due_date,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                for task in tasks
            ],
            count=len(tasks),
        )
