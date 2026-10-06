from dataclasses import dataclass

from app.application.tasks.errors import TaskTransitionError
from app.application.tasks.get_task import GetTaskUseCase
from app.domain.entities.task import Task
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.task_status import TaskStatus


@dataclass
class CompleteTaskUseCase:
    repository: TaskRepository

    def execute(self, agent_id: EntityId, task_id: EntityId) -> Task:
        task = GetTaskUseCase(self.repository).execute(agent_id, task_id)
        if task.status is not TaskStatus.COMPLETED:
            try:
                task.transition_to(TaskStatus.COMPLETED)
            except ValueError as error:
                raise TaskTransitionError(task.status.value, TaskStatus.COMPLETED.value) from error
        return self.repository.save(task)
