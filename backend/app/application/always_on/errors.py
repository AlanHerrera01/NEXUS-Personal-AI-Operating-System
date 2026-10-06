class AlwaysOnError(Exception):
    """Base for Always-On use-case failures."""


class ScheduledJobNotFound(AlwaysOnError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"scheduled job {job_id} not found")
        self.job_id = job_id


class JobExecutionNotFound(AlwaysOnError):
    def __init__(self, execution_id: str) -> None:
        super().__init__(f"job execution {execution_id} not found")
        self.execution_id = execution_id


class ProactiveRuleNotFound(AlwaysOnError):
    def __init__(self, rule_id: str) -> None:
        super().__init__(f"proactive rule {rule_id} not found")
        self.rule_id = rule_id


class TriggerEventNotFound(AlwaysOnError):
    def __init__(self, event_id: str) -> None:
        super().__init__(f"trigger event {event_id} not found")
        self.event_id = event_id


class JobQuotaExceeded(AlwaysOnError):
    """The user already holds as many active jobs as they are allowed."""

    def __init__(self, current: int, limit: int) -> None:
        super().__init__(
            f"active job limit reached: {current} of {limit} already active"
        )
        self.current = current
        self.limit = limit


class ConcurrencyLimitExceeded(AlwaysOnError):
    """Too many of this user's jobs are already executing right now."""

    def __init__(self, current: int, limit: int) -> None:
        super().__init__(
            f"concurrent execution limit reached: {current} of {limit} already running"
        )
        self.current = current
        self.limit = limit


class InvalidSchedule(AlwaysOnError):
    """The requested schedule is not one this system will run."""


class IntervalTooShort(AlwaysOnError):
    def __init__(self, requested: int, minimum: int) -> None:
        super().__init__(
            f"interval_seconds must be at least {minimum} seconds, got {requested}"
        )
        self.requested = requested
        self.minimum = minimum


class EventRateLimited(AlwaysOnError):
    def __init__(self, source: str) -> None:
        super().__init__(f"event rate limit exceeded for source {source!r}")
        self.source = source


class AlwaysOnDisabled(AlwaysOnError):
    """The feature is switched off in this deployment."""