from dataclasses import dataclass
from datetime import datetime

from app.application.reminders.errors import InvalidReminderError
from app.domain.entities.reminder import Reminder
from app.domain.repositories.reminder_repository import ReminderRepository
from app.domain.value_objects.entity_id import EntityId

MAX_TITLE_LENGTH = 300
MAX_NOTES_LENGTH = 10_000


@dataclass
class CreateReminderUseCase:
    repository: ReminderRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        title: str,
        remind_at: datetime,
        notes: str = "",
    ) -> Reminder:
        if len(title) > MAX_TITLE_LENGTH:
            raise InvalidReminderError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        if len(notes) > MAX_NOTES_LENGTH:
            raise InvalidReminderError(
                f"notes must be at most {MAX_NOTES_LENGTH} characters"
            )
        try:
            reminder = Reminder(
                title=title,
                remind_at=remind_at,
                notes=notes,
                agent_id=agent_id,
                user_id=user_id,
            )
        except ValueError as error:
            raise InvalidReminderError(str(error)) from error
        return self.repository.save(reminder)
