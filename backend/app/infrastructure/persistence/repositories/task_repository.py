from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.task import Task
from app.domain.repositories.task_repository import TaskRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.task_status import TaskStatus
from app.infrastructure.persistence.mappers.domain_mappers import task_from_model, task_to_model
from app.infrastructure.persistence.models import TaskModel


class SqlAlchemyTaskRepository(TaskRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, task: Task) -> Task:
        existing = self.session.get(TaskModel, task.id.value)
        if existing is None:
            self.session.add(task_to_model(task))
        else:
            existing.agent_id = task.agent_id.value if task.agent_id else None
            existing.title = task.title
            existing.description = task.description
            existing.status = task.status.value
            existing.due_date = task.due_date
            existing.updated_at = task.updated_at
        self.session.commit()
        return task_from_model(self.session.get(TaskModel, task.id.value))

    def get_by_id(self, task_id: EntityId) -> Task | None:
        model = self.session.get(TaskModel, task_id.value)
        return task_from_model(model) if model else None

    def list_by_agent(
        self,
        agent_id: EntityId,
        limit: int = 100,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        statement = select(TaskModel).where(TaskModel.agent_id == agent_id.value)
        if status is not None:
            statement = statement.where(TaskModel.status == status.value)
        models = self.session.scalars(
            statement.order_by(TaskModel.created_at.desc()).limit(limit)
        ).all()
        return [task_from_model(model) for model in models]
