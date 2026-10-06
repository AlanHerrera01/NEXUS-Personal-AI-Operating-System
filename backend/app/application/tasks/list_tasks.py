from dataclasses import dataclass

from app.domain.entities.task import Task
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.task_status import TaskStatus

MAX_LIMIT = 200


@dataclass
class ListTasksUseCase:
    repository: TaskRepository

    def execute(
        self,
        agent_id: EntityId,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[Task]:
        if limit < 1 or limit > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        return self.repository.list_by_agent(agent_id, limit=limit, status=status)
