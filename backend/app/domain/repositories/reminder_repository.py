from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.reminder import Reminder
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.reminder_status import ReminderStatus


class ReminderRepository(ABC):
    @abstractmethod
    def save(self, reminder: Reminder) -> Reminder:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(
        self, reminder_id: EntityId, agent_id: EntityId, user_id: EntityId | None
    ) -> Reminder | None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError
