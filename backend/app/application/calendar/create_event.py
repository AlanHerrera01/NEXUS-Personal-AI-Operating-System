from dataclasses import dataclass
from datetime import datetime

from app.application.calendar.errors import InvalidEventError
from app.application.calendar.validation import (
    MAX_DESCRIPTION_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_TITLE_LENGTH,
)
from app.domain.entities.calendar_event import CalendarEvent
from app.domain.repositories.calendar_event_repository import CalendarEventRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CreateCalendarEventUseCase:
    repository: CalendarEventRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str | None = None,
    ) -> CalendarEvent:
        for value, limit, field_name in (
            (title, MAX_TITLE_LENGTH, "title"),
            (description, MAX_DESCRIPTION_LENGTH, "description"),
            (location or "", MAX_LOCATION_LENGTH, "location"),
        ):
            if len(value) > limit:
                raise InvalidEventError(f"{field_name} must be at most {limit} characters")
        # The invariants live on the entity; translating its ValueError here is
        # what turns "the domain refused this" into "this input was wrong", which
        # is the only distinction the tool layer can act on.
        try:
            event = CalendarEvent(
                title=title,
                start_at=start,
                end_at=end,
                description=description,
                location=location,
                agent_id=agent_id,
            )
        except ValueError as error:
            raise InvalidEventError(str(error)) from error
        return self.repository.save(event)
