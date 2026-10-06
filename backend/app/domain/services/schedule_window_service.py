"""What to do about occurrences that were missed while the process was down.

This is a policy decision, so it lives in Domain rather than being spread across
the dispatcher's ``if`` statements. Getting it wrong is expensive in both
directions, so it is worth naming explicitly.

**Fire it.** The occurrence is within the grace window. Nothing was lost; the
process just started late.

**Skip it.** The occurrence is older than the grace window. Replaying it would
mean an agent acting on stale context -- a "what did I do today" summary at 09:00
the next morning answers a question about yesterday. Worse, an ``INTERVAL`` job
that was due every five minutes and was missed for a week has 2000 pending
occurrences, and naively catching up turns a downtime into an agent stampede.

Missed occurrences are skipped, not replayed. The job is then rescheduled from
*now* rather than from its stale ``next_run_at``, which is what stops an
interval job from immediately becoming due again on the very next tick.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.entities.scheduled_job import ScheduledJob


class OccurrenceOutcome(StrEnum):
    FIRE = "FIRE"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class OccurrenceDecision:
    outcome: OccurrenceOutcome
    reason: str
    #: The occurrence this decision refers to, i.e. the ``next_run_at`` the job
    #: was holding when it was found due.
    scheduled_for: datetime
    #: Where the schedule should land after this decision. For a skipped
    #: occurrence this is computed from *now*, not from ``scheduled_for``.
    next_run_at: datetime | None


class ScheduleWindowService:
    """Decides whether a due occurrence should run, and where the job lands next."""

    def __init__(self, grace_seconds: int = 900) -> None:
        if grace_seconds < 0:
            raise ValueError("grace_seconds must not be negative")
        self.grace_seconds = grace_seconds

    def decide(self, job: ScheduledJob, now: datetime) -> OccurrenceDecision:
        """Decide the fate of the occurrence the job is currently holding."""
        if job.next_run_at is None:
            raise ValueError("job is not due: it has no next_run_at")
        if not job.trigger_type.is_clock_based:
            raise ValueError("event jobs have no clock-based occurrence")

        scheduled_for = job.next_run_at

        if job.has_missed(now, self.grace_seconds):
            # Re-anchor from now. Leaving next_run_at on the stale value would
            # make the job due again immediately, forever.
            return OccurrenceDecision(
                outcome=OccurrenceOutcome.SKIP,
                reason=(
                    f"occurrence {scheduled_for.isoformat()} was missed by more than "
                    f"{self.grace_seconds}s; skipped instead of replayed"
                ),
                scheduled_for=scheduled_for,
                next_run_at=job.next_occurrence_after(now),
            )

        return OccurrenceDecision(
            outcome=OccurrenceOutcome.FIRE,
            reason=f"occurrence {scheduled_for.isoformat()} is within the grace window",
            scheduled_for=scheduled_for,
            next_run_at=job.next_occurrence_after(scheduled_for),
        )