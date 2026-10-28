from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.reminder import Reminder
from app.domain.repositories.reminder_repository import ReminderRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.reminder_status import ReminderStatus
from app.infrastructure.persistence.mappers.domain_mappers import (
    reminder_from_model,
    reminder_to_model,
)
from app.infrastructure.persistence.models import ReminderModel


class SqlAlchemyReminderRepository(ReminderRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, reminder: Reminder) -> Reminder:
        existing = self.session.get(ReminderModel, reminder.id.value)
        if existing is None:
            self.session.add(reminder_to_model(reminder))
        else:
            existing.agent_id = reminder.agent_id.value if reminder.agent_id else None
            existing.user_id = reminder.user_id.value if reminder.user_id else None
            existing.title = reminder.title
            existing.notes = reminder.notes
            existing.remind_at = reminder.remind_at
            existing.status = reminder.status.value
            existing.updated_at = reminder.updated_at
        self.session.commit()
        return reminder_from_model(self.session.get(ReminderModel, reminder.id.value))

    def get_by_id(
        self, reminder_id: EntityId, agent_id: EntityId, user_id: EntityId | None
    ) -> Reminder | None:
        statement = self._scope(
            select(ReminderModel).where(ReminderModel.id == reminder_id.value),
            agent_id,
            user_id,
        )
        model = self.session.scalars(statement).first()
        return reminder_from_model(model) if model else None

    def list_by_owner(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        status: ReminderStatus | None = None,
        upcoming_only: bool = False,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[Reminder]:
        statement = self._scope(select(ReminderModel), agent_id, user_id)
        if status is not None:
            statement = statement.where(ReminderModel.status == status.value)
        if upcoming_only:
            statement = statement.where(ReminderModel.remind_at >= (now or datetime.now(UTC)))
        models = self.session.scalars(
            statement.order_by(ReminderModel.remind_at.asc()).limit(limit)
        ).all()
        return [reminder_from_model(model) for model in models]

    @staticmethod
    def _scope(statement, agent_id: EntityId, user_id: EntityId | None):
        statement = statement.where(ReminderModel.agent_id == agent_id.value)
        if user_id is None:
            return statement.where(ReminderModel.user_id.is_(None))
        return statement.where(ReminderModel.user_id == user_id.value)
