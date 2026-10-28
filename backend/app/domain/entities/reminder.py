from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.reminder_status import ReminderStatus


@dataclass
class Reminder:
    """A time-based reminder owned by an agent and, when known, a user.

    A reminder is deliberately not a task: tasks carry workflow state, while a
    reminder is a single instant at which something should be surfaced. The two
    share storage patterns, not semantics.
    """

    title: str
    remind_at: datetime
    notes: str = ""
    status: ReminderStatus = ReminderStatus.PENDING
    agent_id: EntityId | None = None
    user_id: EntityId | None = None
    id: EntityId = field(default_factory=EntityId.new)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.title, "title")
        if self.remind_at.tzinfo is None or self.remind_at.utcoffset() is None:
            raise ValueError("remind_at must include a timezone offset")
        self.remind_at = self.remind_at.astimezone(UTC)

    def touch(self) -> None:
        self.updated_at = utc_now()
