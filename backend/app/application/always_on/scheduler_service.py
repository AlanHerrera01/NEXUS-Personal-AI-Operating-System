"""The thing the scheduler wakes up to run.

Deliberately sequential within a tick. A tick can see up to ``max_jobs_per_tick``
due jobs, and running them concurrently would defeat the per-user concurrency
limit the dispatcher enforces -- the limit would be enforced, then immediately
circumvented by the batch itself. Sequential also keeps a burst of 200 overdue
jobs from opening 200 database sessions and 200 agent runs at the same instant.

The cost is that a slow job delays the others in its batch. That is the right
trade for a personal system with a handful of users: correctness and a bounded
blast radius beat shaving seconds off a batch nobody is watching.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.application.always_on.job_dispatcher import (
    DispatchOutcome,
    DispatchOutcomeType,
    JobDispatcher,
)
from app.application.security.approval_service import ApprovalService
from app.domain.entities._common import utc_now
from app.domain.repositories.job_execution_repository import JobExecutionRepository
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository


@dataclass
class TickReport:
    """What one pass over the due jobs did. Returned for logging and tests."""

    now: datetime
    considered: int = 0
    outcomes: list[DispatchOutcome] = field(default_factory=list)
    expired_permission_requests: int = 0
    errors: list[str] = field(default_factory=list)

    def count(self, outcome: DispatchOutcomeType) -> int:
        return sum(1 for item in self.outcomes if item.outcome is outcome)

    @property
    def dispatched(self) -> int:
        return self.count(DispatchOutcomeType.DISPATCHED)


class AlwaysOnSchedulerService:
    """Claims and dispatches the jobs whose clock has come round."""

    def __init__(
        self,
        *,
        scheduled_job_repository: ScheduledJobRepository,
        job_execution_repository: JobExecutionRepository,
        dispatcher: JobDispatcher,
        approval_service: ApprovalService | None = None,
        max_jobs_per_tick: int = 50,
        logger: logging.Logger | None = None,
    ) -> None:
        self.scheduled_job_repository = scheduled_job_repository
        self.job_execution_repository = job_execution_repository
        self.dispatcher = dispatcher
        self.approval_service = approval_service
        self.max_jobs_per_tick = max_jobs_per_tick
        self.logger = logger or logging.getLogger(__name__)

    async def tick(self, now: datetime | None = None) -> TickReport:
        """One pass. Never raises: a bad job must not stop the loop."""
        moment = now or utc_now()
        report = TickReport(now=moment)

        if self.approval_service is not None:
            try:
                report.expired_permission_requests = (
                    self.approval_service.expire_old_requests()
                )
            except Exception as error:  # noqa: BLE001
                self.logger.warning("could not expire permission requests: %s", error)
                report.errors.append(f"expire permission requests: {error}")

        try:
            jobs = self.scheduled_job_repository.list_due(
                moment, limit=self.max_jobs_per_tick
            )
        except Exception as error:  # noqa: BLE001
            self.logger.error("could not list due jobs: %s", error)
            report.errors.append(f"list due jobs: {error}")
            return report

        report.considered = len(jobs)
        for job in jobs:
            try:
                report.outcomes.append(await self.dispatcher.run_due_occurrence(job, moment))
            except Exception as error:  # noqa: BLE001
                # One poisoned job is contained here so the rest of the batch and
                # every future tick still run.
                self.logger.exception(
                    "scheduled job %s failed to dispatch", getattr(job, "id", "?")
                )
                report.errors.append(f"job {getattr(job, 'id', '?')}: {error}")

        self.logger.info(
            "always-on tick at %s: considered=%d dispatched=%d skipped=%d "
            "waiting=%d failed=%d duplicate=%d",
            moment.isoformat(),
            report.considered,
            report.count(DispatchOutcomeType.SUCCEEDED),
            report.count(DispatchOutcomeType.SKIPPED),
            report.count(DispatchOutcomeType.WAITING_PERMISSION),
            report.count(DispatchOutcomeType.FAILED),
            report.count(DispatchOutcomeType.DUPLICATE),
        )
        return report