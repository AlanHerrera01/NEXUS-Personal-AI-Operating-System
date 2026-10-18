from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CalendarEvent:
    """A block of time on the agent's own calendar.

    NEXUS is the system of record here: an event exists because it was written
    here, not because it was mirrored from somewhere else, and nothing in this
    entity reaches a provider. That is why it carries no external identifier and
    no provider URL -- a field that is always empty is a promise the code cannot
    keep, and one a later reader would try to fill in.
    """

    title: str
    start_at: datetime
    end_at: datetime
    description: str = ""
    location: str | None = None
    agent_id: EntityId | None = None
    id: EntityId = field(default_factory=EntityId.new)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.title, "title")
        self.start_at = _aware_utc(self.start_at, "start")
        self.end_at = _aware_utc(self.end_at, "end")
        if self.end_at <= self.start_at:
            raise ValueError("end must be after start")

    def touch(self) -> None:
        self.updated_at = utc_now()


def _aware_utc(value: datetime, field_name: str) -> datetime:
    """Convert to UTC, refusing a naive value instead of guessing a zone.

    An event is a wall-clock appointment, so "10:00" with no offset does not
    identify an instant. Reading it as UTC when the caller meant 10:00 somewhere
    else moves the appointment hours away from where it belongs, and no later
    reader can tell that it happened. Asking for the offset costs one retry that
    names the field; guessing costs a meeting nobody attends.
    """
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value.astimezone(UTC)
