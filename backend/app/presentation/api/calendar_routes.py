from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.infrastructure.persistence.repositories.calendar_event_repository import (
    SqlAlchemyCalendarEventRepository,
)
from app.presentation.dependencies.calendar import (
    get_calendar_agent_repository,
    get_calendar_event_repository,
)
from app.presentation.dependencies.identity import current_user_id
from app.presentation.schemas.calendar import CalendarEventResponse

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])


def _aware(value: datetime | None, field_name: str) -> datetime | None:
    """Refuse a window edge with no offset rather than guessing a zone.

    The same rule the event entity applies, for the same reason: "from 10:00"
    with no offset does not identify an instant, and reading it as UTC when the
    caller meant somewhere else would silently widen the window they asked for.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must include a timezone offset",
        )
    return value


@router.get("/events", response_model=list[CalendarEventResponse])
def list_calendar_events(
    start: datetime | None = Query(
        default=None, description="Only events that end after this instant."
    ),
    end: datetime | None = Query(
        default=None, description="Only events that start before this instant."
    ),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: EntityId = Depends(current_user_id),
    agent_repository: SqlAlchemyAgentRepository = Depends(get_calendar_agent_repository),
    calendar_repository: SqlAlchemyCalendarEventRepository = Depends(
        get_calendar_event_repository
    ),
) -> list[CalendarEventResponse]:
    """The caller's calendar, read straight from the store.

    Owner-scoped through the agents: an event belongs to an agent, and an agent
    belongs to a user, so the only events read are those of the caller's own
    agents. Without that hop this route would hand back the whole deployment's
    calendar, which is why the filtering is done by identity rather than by a
    query parameter.
    """
    window_start = _aware(start, "start")
    window_end = _aware(end, "end")
    events = []
    for agent in agent_repository.list_by_user(user_id):
        events.extend(
            calendar_repository.list_by_agent(
                agent.id, limit=limit, start=window_start, end=window_end
            )
        )
    # Each agent was capped at ``limit``; the merged list is capped again so the
    # response honours the parameter the caller actually set.
    events.sort(key=lambda event: event.start_at)
    return [
        CalendarEventResponse(
            id=str(event.id),
            title=event.title,
            description=event.description,
            location=event.location,
            start_at=event.start_at.isoformat(),
            end_at=event.end_at.isoformat(),
            agent_id=str(event.agent_id) if event.agent_id else None,
            created_at=event.created_at.isoformat(),
        )
        for event in events[:limit]
    ]
