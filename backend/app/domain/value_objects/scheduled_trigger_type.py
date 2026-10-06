from enum import StrEnum


class ScheduledTriggerType(StrEnum):
    """How a scheduled job decides it is time to fire.

    ``EVENT`` is not a clock at all: such a job has no ``next_run_at`` and only
    ever fires from :class:`TriggerEvent` ingestion. Keeping it in the same enum
    (rather than a separate concept) is what lets a job be paused, listed and
    audited uniformly regardless of why it runs.
    """

    ONCE = "ONCE"
    INTERVAL = "INTERVAL"
    CRON = "CRON"
    EVENT = "EVENT"

    @property
    def is_clock_based(self) -> bool:
        """True when the scheduler advances this job on its own."""
        return self is not ScheduledTriggerType.EVENT