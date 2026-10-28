"""Dependency providers for the calendar read route.

Named individually, like the overview's, so the route's two data sources can be
substituted in tests without a database. The agent repository is here because
ownership of an event runs through its agent: the calendar read needs the
caller's agents before it can name a single event.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.infrastructure.persistence.repositories.calendar_event_repository import (
    SqlAlchemyCalendarEventRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def get_calendar_agent_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRepository:
    return SqlAlchemyAgentRepository(session)


def get_calendar_event_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyCalendarEventRepository:
    return SqlAlchemyCalendarEventRepository(session)
