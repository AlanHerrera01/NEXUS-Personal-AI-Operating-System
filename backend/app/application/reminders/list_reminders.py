from dataclasses import dataclass
from datetime import datetime

from app.application.reminders.errors import InvalidReminderError
from app.domain.entities.reminder import Reminder
from app.domain.repositories.reminder_repository import ReminderRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.reminder_status import ReminderStatus

MAX_LIMIT = 100


@dataclass
class ListRemindersUseCase:
    repository: ReminderRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        status: ReminderStatus | None = None,
        upcoming_only: bool = False,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[Reminder]:
        if limit < 1 or limit > MAX_LIMIT:
            raise InvalidReminderError(f"limit must be between 1 and {MAX_LIMIT}")
        return self.repository.list_by_owner(
            agent_id=agent_id,
            user_id=user_id,
            status=status,
            upcoming_only=upcoming_only,
            now=now,
            limit=limit,
        )
