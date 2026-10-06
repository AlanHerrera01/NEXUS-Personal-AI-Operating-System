from dataclasses import dataclass
from datetime import datetime

from app.application.tasks.validation import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH
from app.domain.entities._common import require_text
from app.domain.entities.task import Task
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CreateTaskUseCase:
    repository: TaskRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        title: str,
        description: str = "",
        due_date: datetime | None = None,
    ) -> Task:
        require_text(title, "title")
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"description must be at most {MAX_DESCRIPTION_LENGTH} characters")
        task = Task(title=title, description=description, agent_id=agent_id, due_date=due_date)
        return self.repository.save(task)
