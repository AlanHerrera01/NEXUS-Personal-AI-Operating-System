from enum import StrEnum


class JobExecutionStatus(StrEnum):
    """Lifecycle of one attempt to run a :class:`ScheduledJob`.

    ``SKIPPED`` is a first-class outcome, not an error. It is what a job records
    when the scheduler found it due after a downtime long enough that replaying
    every missed occurrence would be worse than dropping them. Without it,
    "we deliberately did not run this" and "we ran this and it broke" look
    identical in the history.

    ``WAITING_PERMISSION`` mirrors ``AgentRunStatus.WAITING_PERMISSION``. The
    run is suspended on a human decision and the execution stays open across
    process restarts; nothing re-drives it automatically.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL

    @property
    def is_open(self) -> bool:
        """True while the execution still owns an outcome it has not reported."""
        return self in _OPEN


_TERMINAL = frozenset(
    {
        JobExecutionStatus.COMPLETED,
        JobExecutionStatus.FAILED,
        JobExecutionStatus.SKIPPED,
        JobExecutionStatus.CANCELLED,
    }
)

_OPEN = frozenset(
    {
        JobExecutionStatus.QUEUED,
        JobExecutionStatus.RUNNING,
        JobExecutionStatus.WAITING_PERMISSION,
    }
)

#: Where an execution may legally move. An execution that reached a terminal
#: state is never reopened; recovery for a process that died mid-run is handled
#: by re-marking the *execution* as failed, never by rewinding it.
ALLOWED_TRANSITIONS: dict[JobExecutionStatus, frozenset[JobExecutionStatus]] = {
    JobExecutionStatus.QUEUED: frozenset(
        {
            JobExecutionStatus.RUNNING,
            JobExecutionStatus.SKIPPED,
            JobExecutionStatus.FAILED,
            JobExecutionStatus.CANCELLED,
        }
    ),
    JobExecutionStatus.RUNNING: frozenset(
        {
            JobExecutionStatus.WAITING_PERMISSION,
            JobExecutionStatus.COMPLETED,
            JobExecutionStatus.FAILED,
            # A claimed execution can still be declined before any work starts
            # -- most often by the per-user concurrency limit. That is a
            # deliberate non-execution, not a failure, and recording it as FAILED
            # would put a red error in the history for normal, correct behaviour.
            JobExecutionStatus.SKIPPED,
            JobExecutionStatus.CANCELLED,
        }
    ),
    JobExecutionStatus.WAITING_PERMISSION: frozenset(
        {
            JobExecutionStatus.COMPLETED,
            JobExecutionStatus.FAILED,
            JobExecutionStatus.CANCELLED,
        }
    ),
    JobExecutionStatus.COMPLETED: frozenset(),
    JobExecutionStatus.FAILED: frozenset(),
    JobExecutionStatus.SKIPPED: frozenset(),
    JobExecutionStatus.CANCELLED: frozenset(),
}