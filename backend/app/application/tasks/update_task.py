from dataclasses import dataclass
from datetime import datetime

from app.application.tasks.errors import TaskTransitionError
from app.application.tasks.get_task import GetTaskUseCase
from app.application.tasks.validation import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH
from app.domain.entities._common import require_text
from app.domain.entities.task import Task
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.task_status import TaskStatus

_UNSET = object()


@dataclass
class UpdateTaskUseCase:
    repository: TaskRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        task_id: EntityId,
        title: str | None = None,
        description: str | None = None,
        due_date: datetime | None | object = _UNSET,
        status: TaskStatus | None = None,
    ) -> Task:
        task = GetTaskUseCase(self.repository).execute(agent_id, task_id)
        if title is not None:
            require_text(title, "title")
            if len(title) > MAX_TITLE_LENGTH:
                raise ValueError(f"title must be at most {MAX_TITLE_LENGTH} characters")
            task.title = title
        if description is not None:
            if len(description) > MAX_DESCRIPTION_LENGTH:
                raise ValueError(f"description must be at most {MAX_DESCRIPTION_LENGTH} characters")
            task.description = description
        if due_date is not _UNSET:
            task.due_date = due_date
        if status is not None and status is not task.status:
            try:
                task.transition_to(status)
            except ValueError as error:
                raise TaskTransitionError(task.status.value, status.value) from error
        else:
            task.touch()
        return self.repository.save(task)
