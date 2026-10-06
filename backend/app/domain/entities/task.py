from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.task_status import TaskStatus


@dataclass
class Task:
    title: str
    description: str = ""
    agent_id: EntityId | None = None
    id: EntityId = field(default_factory=EntityId.new)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    due_date: datetime | None = None

    def __post_init__(self) -> None:
        require_text(self.title, "title")

    def touch(self) -> None:
        self.updated_at = utc_now()

    def transition_to(self, status: TaskStatus) -> None:
        allowed = {
            TaskStatus.PENDING: {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.CANCELLED},
            TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.CANCELLED},
            TaskStatus.COMPLETED: set(),
            TaskStatus.CANCELLED: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid task transition: {self.status} -> {status}")
        self.status = status
        self.updated_at = utc_now()