from datetime import datetime

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput
from app.domain.value_objects.task_status import TaskStatus

SKILL_NAME = "tasks"


class TaskSummary(ToolOutput):
    task_id: str
    title: str
    description: str = ""
    status: TaskStatus
    due_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
