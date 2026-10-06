from abc import ABC, abstractmethod

from app.domain.entities.task import Task
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.task_status import TaskStatus


class TaskRepository(ABC):
    @abstractmethod
    def save(self, task: Task) -> Task:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, task_id: EntityId) -> Task | None:
        raise NotImplementedError

    @abstractmethod
    def list_by_agent(
        self,
        agent_id: EntityId,
        limit: int = 100,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        raise NotImplementedError
