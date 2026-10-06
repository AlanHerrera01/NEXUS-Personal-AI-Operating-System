from app.application.tasks.errors import TaskNotFoundError
from app.application.tasks.get_task import GetTaskUseCase
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import EntityIdArgument, ToolContext, ToolInput
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.tasks.tools.contracts import SKILL_NAME, TaskSummary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"task_id": {"type": "string", "description": "Identifier of the task"}},
    "required": ["task_id"],
    "additionalProperties": False,
}


class TaskGetInput(ToolInput):
    task_id: EntityIdArgument


class TaskGetTool(UseCaseTool[TaskGetInput, TaskSummary]):
    def __init__(self, repository: TaskRepository) -> None:
        super().__init__(
            name="task.get",
            description="Get one task of the current user by identifier.",
            skill_name=SKILL_NAME,
            input_model=TaskGetInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            category="tasks",
            error_codes={TaskNotFoundError: ToolErrorCode.TASK_NOT_FOUND},
        )
        self.use_case = GetTaskUseCase(repository)

    async def run(self, payload: TaskGetInput, context: ToolContext) -> TaskSummary:
        task = self.use_case.execute(context.agent_id, payload.task_id)
        return TaskSummary(
            task_id=str(task.id),
            title=task.title,
            description=task.description,
            status=task.status,
            due_date=task.due_date,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
