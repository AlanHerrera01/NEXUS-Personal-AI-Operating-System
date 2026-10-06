from enum import StrEnum


class ScheduledJobStatus(StrEnum):
    """Lifecycle of a :class:`ScheduledJob`.

    ``FAILED`` is sticky on purpose. A job that blew up and stopped is a
    different thing from a paused job, and silently reactivating it on the next
    poll would re-run whatever made it fail without anyone asking.
    """

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL

    @property
    def is_schedulable(self) -> bool:
        """Only ACTIVE jobs are eligible to be claimed by the dispatcher."""
        return self is ScheduledJobStatus.ACTIVE


_TERMINAL = frozenset(
    {
        ScheduledJobStatus.COMPLETED,
        ScheduledJobStatus.FAILED,
        ScheduledJobStatus.CANCELLED,
    }
)