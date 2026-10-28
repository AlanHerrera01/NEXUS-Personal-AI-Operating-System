from enum import StrEnum


class ReminderStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    CANCELLED = "CANCELLED"
