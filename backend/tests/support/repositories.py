from datetime import datetime

from app.domain.entities.permission_request import PermissionRequest
from app.domain.entities.task import Task
from app.domain.ports.permission_request_repository import PermissionRequestRepository
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.task_status import TaskStatus


class InMemoryPermissionRequestRepository(PermissionRequestRepository):
    """Real storage for permission requests.

    Using a real repository instead of a Mock is what lets the human-in-the-loop
    tests exercise the actual approve/reject state machine rather than assert
    that a mock was called.
    """

    def __init__(self) -> None:
        self.items: dict[EntityId, PermissionRequest] = {}

    def save(self, request: PermissionRequest) -> None:
        self.items[request.id] = request

    def get_by_id(self, request_id: EntityId) -> PermissionRequest | None:
        return self.items.get(request_id)

    def get_by_run_id(self, run_id: EntityId) -> list[PermissionRequest]:
        return [r for r in self.items.values() if r.agent_run_id == run_id]

    def get_pending_by_run_id(self, run_id: EntityId) -> PermissionRequest | None:
        for request in self.items.values():
            if request.agent_run_id == run_id and request.status is PermissionRequestStatus.PENDING:
                return request
        return None

    def list_all(self) -> list[PermissionRequest]:
        return list(self.items.values())


class FakeTaskRepository(TaskRepository):
    def __init__(self) -> None:
        self.items: dict[EntityId, Task] = {}
        self.error: Exception | None = None
        self.saved: list[Task] = []

    def save(self, task: Task) -> Task:
        if self.error is not None:
            raise self.error
        self.items[task.id] = task
        self.saved.append(task)
        return task

    def get_by_id(self, task_id: EntityId) -> Task | None:
        if self.error is not None:
            raise self.error
        return self.items.get(task_id)

    def list_by_agent(
        self,
        agent_id: EntityId,
        limit: int = 100,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        if self.error is not None:
            raise self.error
        found = [task for task in self.items.values() if task.agent_id == agent_id]
        if status is not None:
            found = [task for task in found if task.status is status]
        return sorted(found, key=lambda task: task.created_at, reverse=True)[:limit]


class FailingTaskRepository(FakeTaskRepository):
    def save(self, task: Task) -> Task:
        raise RuntimeError("connection reset by peer")


def make_task(agent_id: EntityId, title: str = "Review NEXUS", **kwargs) -> Task:
    due_date: datetime | None = kwargs.pop("due_date", None)
    return Task(title=title, description=kwargs.pop("description", ""), agent_id=agent_id, due_date=due_date, **kwargs)
