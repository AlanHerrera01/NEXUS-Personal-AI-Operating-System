from dataclasses import dataclass
from datetime import datetime

from app.application.calendar.errors import InvalidEventError
from app.application.calendar.validation import MAX_LIMIT
from app.domain.entities.calendar_event import CalendarEvent
from app.domain.repositories.calendar_event_repository import CalendarEventRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class ListCalendarEventsUseCase:
    repository: CalendarEventRepository

    def execute(
        self,
        agent_id: EntityId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[CalendarEvent]:
        if limit < 1 or limit > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if start is not None and end is not None and end <= start:
            raise InvalidEventError("end must be after start")
        return self.repository.list_by_agent(agent_id, limit=limit, start=start, end=end)
