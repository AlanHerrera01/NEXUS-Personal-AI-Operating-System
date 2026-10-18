from datetime import datetime

from app.domain.ports.tool import ToolOutput

SKILL_NAME = "calendar"


class CalendarEventSummary(ToolOutput):
    """One event as the model sees it.

    Deliberately no provider URL and no external id: this is NEXUS's own
    calendar, so a link to a system that does not exist would be a field that is
    always empty.
    """

    event_id: str
    title: str
    description: str = ""
    start_at: datetime
    end_at: datetime
    location: str | None = None
    created_at: datetime | None = None
