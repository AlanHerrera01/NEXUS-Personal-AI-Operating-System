"""Reconciles state left behind by a process that died mid-execution.

An execution row is written and claimed *before* the agent run starts. That
ordering is what makes duplicate dispatch impossible, and it means a crash
leaves an execution that is ``RUNNING`` with no agent run attached, or one whose
run is still open. On the next boot those rows are not garbage to be ignored:
left alone, a job with a stuck ``RUNNING`` execution consumes a concurrency slot
forever and eventually blocks that user entirely.

The policy is **fail, never retry**.

Retrying is tempting because the work was probably harmless. It is wrong for two
reasons. First, the failure is indistinguishable from a worker that is merely
slow, and re-running work that may still be executing somewhere is how you get
two agent runs acting on the same account. Second, the idempotency key is
already consumed -- the occurrence is spent -- so a retry would have to invent a
fresh key, which means the database could no longer tell a retry from a genuine
second occurrence.

So a stranded execution is marked ``FAILED`` with a reason that says it was
recovered, and the user sees a real failure in their history that they can
re-trigger deliberately. An honest failure beats a silent duplicate.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.entities._common import utc_now
from app.domain.repositories.job_execution_repository import JobExecutionRepository
from app.domain.value_objects.job_execution_status import JobExecutionStatus

#: How long an execution may sit in RUNNING before it is assumed stranded.
#: Must comfortably exceed the longest permitted agent run, or a healthy but
#: slow run would be failed out from under itself by a concurrent worker.
DEFAULT_STALE_AFTER = timedelta(minutes=30)


@dataclass
class RecoveryReport:
    now: datetime
    failed_stale: int = 0
    skipped_waiting: int = 0
    ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class AlwaysOnRecoveryService:
    """Fails out executions whose worker is no longer running them."""

    def __init__(
        self,
        job_execution_repository: JobExecutionRepository,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
        logger: logging.Logger | None = None,
    ) -> None:
        self.job_execution_repository = job_execution_repository
        self.stale_after = stale_after
        self.logger = logger or logging.getLogger(__name__)

    def recover(self, now: datetime | None = None) -> RecoveryReport:
        moment = now or utc_now()
        report = RecoveryReport(now=moment)
        cutoff = moment - self.stale_after

        for status in (
            JobExecutionStatus.QUEUED,
            JobExecutionStatus.RUNNING,
        ):
            try:
                executions = self.job_execution_repository.list_by_status(status, limit=200)
            except Exception as error:  # noqa: BLE001
                self.logger.error("could not list %s executions: %s", status.value, error)
                report.errors.append(f"list {status.value}: {error}")
                continue

            for execution in executions:
                if self._is_stranded(execution, cutoff, moment):
                    self._fail(execution, report, moment)

        # WAITING_PERMISSION is deliberately left alone. It is not stranded: a
        # human is expected to answer, and the request expires on its own clock
        # via ApprovalService. Recovery must never "resolve" a pending approval.
        report.skipped_waiting = len(
            self._safe_list(JobExecutionStatus.WAITING_PERMISSION, report)
        )
        return report

    def _is_stranded(self, execution, cutoff: datetime, moment: datetime) -> bool:
        """Stale if untouched for longer than the window.

        QUEUED is judged against ``created_at`` because it may never have been
        claimed; RUNNING against ``claimed_at`` when present, since that is when
        the worker took ownership.
        """
        reference = execution.claimed_at or execution.started_at or execution.created_at
        if reference is None:
            return False
        return reference < cutoff

    def _fail(self, execution, report: RecoveryReport, moment: datetime) -> None:
        reason = (
            f"recovered after restart: the worker holding this execution stopped "
            f"before it reported an outcome (stale since "
            f"{execution.updated_at.isoformat()})"
        )
        try:
            execution.mark_failed(reason)
            self.job_execution_repository.save(execution)
            report.failed_stale += 1
            report.ids.append(str(execution.id))
            self.logger.warning(
                "failed stranded job execution %s (job %s)",
                execution.id,
                execution.scheduled_job_id,
            )
        except Exception as error:  # noqa: BLE001
            self.logger.error("could not fail execution %s: %s", execution.id, error)
            report.errors.append(f"fail {execution.id}: {error}")

    def _safe_list(self, status: JobExecutionStatus, report: RecoveryReport) -> list:
        try:
            return self.job_execution_repository.list_by_status(status, limit=200)
        except Exception as error:  # noqa: BLE001
            report.errors.append(f"list {status.value}: {error}")
            return []