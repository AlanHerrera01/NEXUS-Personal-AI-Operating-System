"""Turns an approval decision back into forward progress.

Before this existed, approving a permission request only flipped the
``PermissionRequest`` to ``APPROVED``. Nobody called
:meth:`AgentOrchestrator.resume`, so the ``AgentRun`` stayed in
``WAITING_PERMISSION`` forever and the approved action never ran. That is a
correctness bug for interactive use, and for Always-On it is worse: a scheduled
job that hits an ASK occupies a concurrency slot and an open execution
indefinitely, and nothing in the system ever moves it again.

This service is the bridge. The existing approve/reject routes call it after
recording the decision, and it:

1. resumes the run through the orchestrator -- so the approved action goes back
   through the same Trust Engine and mints a fresh, single-use
   ``ExecutionAuthorization``. The approval is a *decision*, not a token: the
   token is minted again at execution time and cannot be replayed;
2. writes the outcome onto the linked job execution, closing it out or returning
   it to ``WAITING_PERMISSION`` if the resumed turn asks for something else;
3. is a no-op for manual runs, which have no job execution to reconcile.

Approvals are still single-use and still expiring. Nothing here relaxes that.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from app.application.agents.orchestrator import AgentExecutionResult, AgentOrchestrator
from app.domain.entities._common import utc_now
from app.domain.entities.job_execution import JobExecution
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.job_execution_repository import JobExecutionRepository
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.job_execution_status import JobExecutionStatus


@dataclass
class ReconciliationOutcome:
    """What a human decision did to the run behind it."""

    resumed: bool
    run_status: AgentRunStatus | None = None
    execution_status: JobExecutionStatus | None = None
    detail: str = ""
    result: AgentExecutionResult | None = None


class JobExecutionCoordinator:
    """Resumes approved runs and keeps job executions in step with them."""

    def __init__(
        self,
        *,
        orchestrator: AgentOrchestrator,
        agent_run_repository: AgentRunRepository,
        job_execution_repository: JobExecutionRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.agent_run_repository = agent_run_repository
        self.job_execution_repository = job_execution_repository
        self.logger = logger or logging.getLogger(__name__)

    async def reconcile(
        self,
        run_id: EntityId,
        allow: bool,
        user_id: EntityId,
        now: datetime | None = None,
    ) -> ReconciliationOutcome:
        """Resume ``run_id`` on behalf of ``user_id`` and reconcile its execution.

        ``user_id`` is required, not optional, for two reasons that both bite here.
        The run is loaded through it, so a caller cannot reconcile somebody else's
        run; and ``orchestrator.resume`` refuses to proceed without an identity,
        so an omitted argument would surface as a generic "resume failed" inside
        the broad ``except`` below -- every human approval silently failing to
        advance its run, which is exactly the bug this class exists to fix.
        """
        moment = now or utc_now()
        run = self.agent_run_repository.get_by_id(run_id, user_id)
        if run is None:
            return ReconciliationOutcome(
                resumed=False, detail=f"agent run {run_id} not found"
            )
        if run.status is not AgentRunStatus.WAITING_PERMISSION:
            return ReconciliationOutcome(
                resumed=False,
                run_status=run.status,
                detail=f"agent run is {run.status.value}, not waiting for permission",
            )

        execution = self._open_execution(run_id)

        try:
            result = await self.orchestrator.resume(run, allow, user_id=str(user_id))
        except Exception as error:  # noqa: BLE001
            self.logger.exception("resume failed for run %s", run_id)
            if execution is not None:
                self._settle(execution, JobExecutionStatus.FAILED, f"resume failed: {error}")
            return ReconciliationOutcome(
                resumed=False, run_status=run.status, detail=f"resume failed: {error}"
            )

        status = result.run.status
        execution_status = None
        if execution is not None:
            if status is AgentRunStatus.COMPLETED:
                execution_status = JobExecutionStatus.COMPLETED
            elif status is AgentRunStatus.WAITING_PERMISSION:
                # The resumed turn hit another ASK. The execution stays open and
                # the user is asked again -- escalating, never auto-resolving.
                execution_status = JobExecutionStatus.WAITING_PERMISSION
            else:
                execution_status = JobExecutionStatus.FAILED
            self._settle(execution, execution_status, result.response)

        return ReconciliationOutcome(
            resumed=True,
            run_status=status,
            execution_status=execution_status,
            detail=result.response or status.value,
            result=result,
        )

    # -- internals -------------------------------------------------------

    def _open_execution(self, run_id: EntityId) -> JobExecution | None:
        try:
            return self.job_execution_repository.get_open_by_run(run_id)
        except Exception as error:  # noqa: BLE001
            self.logger.warning("could not find an execution for run %s: %s", run_id, error)
            return None

    def _settle(
        self, execution: JobExecution, status: JobExecutionStatus, summary: str | None
    ) -> None:
        try:
            if status is JobExecutionStatus.COMPLETED:
                execution.mark_completed(summary)
            elif status is JobExecutionStatus.WAITING_PERMISSION:
                execution.mark_waiting_permission()
            elif status is JobExecutionStatus.CANCELLED:
                execution.mark_cancelled(summary)
            else:
                execution.mark_failed(summary or f"run ended {status.value}")
            self.job_execution_repository.save(execution)
        except Exception as error:  # noqa: BLE001
            # Never let a bookkeeping failure mask the fact that the run resumed.
            self.logger.exception(
                "could not update execution %s to %s", execution.id, status.value
            )