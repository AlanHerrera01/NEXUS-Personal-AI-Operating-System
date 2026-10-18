from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.calendar_event import CalendarEvent
from app.domain.value_objects.entity_id import EntityId


class CalendarEventRepository(ABC):
    @abstractmethod
    def save(self, event: CalendarEvent) -> CalendarEvent:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, event_id: EntityId) -> CalendarEvent | None:
        raise NotImplementedError

    @abstractmethod
    def list_by_agent(
        self,
        agent_id: EntityId,
        limit: int = 100,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CalendarEvent]:
        """Events owned by ``agent_id`` that touch the ``[start, end)`` window.

        Overlap, not containment. An event running 09:00-12:00 is part of a
        10:00-11:00 question even though neither of its edges falls inside that
        window, and a query built on containment would silently omit it.
        """
        raise NotImplementedError
