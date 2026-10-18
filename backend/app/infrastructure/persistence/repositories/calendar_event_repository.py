from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.calendar_event import CalendarEvent
from app.domain.repositories.calendar_event_repository import CalendarEventRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.domain_mappers import (
    calendar_event_from_model,
    calendar_event_to_model,
)
from app.infrastructure.persistence.models import CalendarEventModel


class SqlAlchemyCalendarEventRepository(CalendarEventRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, event: CalendarEvent) -> CalendarEvent:
        existing = self.session.get(CalendarEventModel, event.id.value)
        if existing is None:
            self.session.add(calendar_event_to_model(event))
        else:
            existing.agent_id = event.agent_id.value if event.agent_id else None
            existing.title = event.title
            existing.description = event.description
            existing.location = event.location
            existing.start_at = event.start_at
            existing.end_at = event.end_at
            existing.updated_at = event.updated_at
        self.session.commit()
        return calendar_event_from_model(self.session.get(CalendarEventModel, event.id.value))

    def get_by_id(self, event_id: EntityId) -> CalendarEvent | None:
        model = self.session.get(CalendarEventModel, event_id.value)
        return calendar_event_from_model(model) if model else None

    def list_by_agent(
        self,
        agent_id: EntityId,
        limit: int = 100,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CalendarEvent]:
        statement = select(CalendarEventModel).where(CalendarEventModel.agent_id == agent_id.value)
        # Overlap, expressed as the two halves of the window test: the event ends
        # after the window opens and starts before it closes.
        if start is not None:
            statement = statement.where(CalendarEventModel.end_at > start)
        if end is not None:
            statement = statement.where(CalendarEventModel.start_at < end)
        models = self.session.scalars(
            statement.order_by(CalendarEventModel.start_at.asc()).limit(limit)
        ).all()
        return [calendar_event_from_model(model) for model in models]
