from dataclasses import dataclass

from app.application.tasks.errors import TaskNotFoundError
from app.domain.entities.task import Task
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class GetTaskUseCase:
    repository: TaskRepository

    def execute(self, agent_id: EntityId, task_id: EntityId) -> Task:
        task = self.repository.get_by_id(task_id)
        if task is None or task.agent_id != agent_id:
            raise TaskNotFoundError(str(task_id))
        return task
