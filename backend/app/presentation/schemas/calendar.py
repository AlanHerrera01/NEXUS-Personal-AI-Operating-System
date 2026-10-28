from pydantic import BaseModel


class CalendarEventResponse(BaseModel):
    """One event on the caller's calendar.

    ``start_at``/``end_at`` are ISO-8601 in UTC, because that is how the event is
    stored: the entity normalises every instant to UTC and refuses a naive one.
    Rendering it in the viewer's zone is the client's job, so the offset it shows
    is the reader's and not the server's.
    """

    id: str
    title: str
    description: str
    location: str | None
    start_at: str
    end_at: str
    agent_id: str | None
    created_at: str
