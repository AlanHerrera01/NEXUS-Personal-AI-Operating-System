from datetime import datetime

from app.domain.ports.tool import ToolOutput
from app.domain.value_objects.reminder_status import ReminderStatus

SKILL_NAME = "reminders"


class ReminderSummary(ToolOutput):
    reminder_id: str
    title: str
    notes: str = ""
    remind_at: datetime
    status: ReminderStatus
    created_at: datetime | None = None


class ReminderListOutput(ToolOutput):
    items: list[ReminderSummary]
    count: int
