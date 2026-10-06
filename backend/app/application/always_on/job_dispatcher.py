"""Turns a due job or a received event into an agent run.

This is the only place in the Always-On feature that is allowed to start an
agent run, and it does so by calling the existing
:class:`~app.application.agents.orchestrator.AgentOrchestrator`. There is no
second execution pipeline here. Everything that makes an agent run safe --
context building, plan validation, the Trust Engine, ``ExecutionAuthorization``,
the runtime -- is reached only because the orchestrator is reached, and that
includes the parts that make it safe *against* the scheduler. A job does not get
a shortcut, a wider tool set or a standing permission just because it was
programmed by its own owner; the request it submits is treated exactly as if a
human had typed it into the chat box.

Ordering of the four steps below is the whole concurrency story, so it is worth
stating in order:

1. **Insert the execution** keyed on ``(job, occurrence)``. The unique
   constraint means exactly one of N racing workers creates the row; the rest
   get the existing one back and return immediately. Nothing has been executed
   yet, so this is cheap and safe to lose.
2. **Claim it**, a compare-and-set from ``QUEUED`` to ``RUNNING``. This is what
   stops a worker that crashed earlier from being re-run by a later sweep while
   the original is still alive.
3. **Advance the job's schedule.** Losing this race is not an error: the
   execution claim in step 2 is what actually grants the right to run, and the
   schedule is only bookkeeping.
4. **Create the agent run and execute it.**

Doing the insert first is what makes a crash recoverable without losing or
duplicating work. A process that dies between steps 1 and 4 leaves a claimed
``RUNNING`` execution with no run attached, which the recovery sweep in
:class:`~app.application.always_on.recovery_service.AlwaysOnRecoveryService`
fails explicitly rather than retrying.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.application.agents.orchestrator import AgentExecutionResult, AgentOrchestrator
from app.application.agent_runs.create_agent_run import CreateAgentRunUseCase
from app.application.always_on.errors import ConcurrencyLimitExceeded
from app.domain.entities.job_execution import JobExecution
from app.domain.entities.scheduled_job import ScheduledJob
from app.domain.entities.trigger_event import TriggerEvent
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.job_execution_repository import JobExecutionRepository
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository
from app.domain.services.schedule_window_service import (
    OccurrenceOutcome,
    ScheduleWindowService,
)
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.job_execution_status import JobExecutionStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType

#: Cap on the instruction text a job may carry. The agent run's ``user_request``
#: is user-authored text, not a document store.
MAX_REQUEST_LENGTH = 8_000

DEFAULT_CLOCK_REQUEST = "Run the scheduled task that is due and report what you find."
DEFAULT_EVENT_REQUEST = "Handle the event that was received and report what you did."


class DispatchOutcomeType(StrEnum):
    """Why a dispatch attempt ended the way it did."""

    DISPATCHED = "DISPATCHED"
    #: The run completed on its own.
    SUCCEEDED = "SUCCEEDED"
    #: The Trust Engine escalated and the run is parked on a human decision.
    WAITING_PERMISSION = "WAITING_PERMISSION"
    #: The occurrence was too old to replay; recorded as SKIPPED.
    SKIPPED = "SKIPPED"
    #: Another worker already owns this occurrence.
    DUPLICATE = "DUPLICATE"
    #: This user's concurrency budget is full.
    DEFERRED = "DEFERRED"
    #: The run or the job itself failed.
    FAILED = "FAILED"


@dataclass(frozen=True)
class DispatchOutcome:
    outcome: DispatchOutcomeType
    execution: JobExecution | None
    detail: str
    result: AgentExecutionResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def clock_idempotency_key(job: ScheduledJob, scheduled_for: datetime) -> str:
    """Deterministic key for a clock occurrence.

    Derived purely from the job and the occurrence instant, so every worker and
    every restart computes the same string. Nothing about the attempt is in here,
    which is exactly why a retry must not produce a second run.
    """
    return f"schedule:{job.id}:{scheduled_for.isoformat()}"


def event_idempotency_key(job: ScheduledJob, event: TriggerEvent) -> str:
    return f"event:{job.id}:{event.id}"


class JobDispatcher:
    """Drives one occurrence of a scheduled job to an outcome."""

    def __init__(
        self,
        *,
        create_agent_run: CreateAgentRunUseCase,
        orchestrator: AgentOrchestrator,
        agent_run_repository: AgentRunRepository,
        scheduled_job_repository: ScheduledJobRepository,
        job_execution_repository: JobExecutionRepository,
        window_service: ScheduleWindowService,
        max_concurrent_runs_per_user: int = 3,
    ) -> None:
        self.create_agent_run = create_agent_run
        self.orchestrator = orchestrator
        self.agent_run_repository = agent_run_repository
        self.scheduled_job_repository = scheduled_job_repository
        self.job_execution_repository = job_execution_repository
        self.window_service = window_service
        self.max_concurrent_runs_per_user = max_concurrent_runs_per_user

    # -- public entry points ---------------------------------------------

    async def run_due_occurrence(
        self, job: ScheduledJob, now: datetime
    ) -> DispatchOutcome:
        """Handle the clock occurrence the job is currently holding."""
        if job.next_run_at is None:
            return DispatchOutcome(
                DispatchOutcomeType.SKIPPED,
                None,
                "job has no next_run_at, so nothing is due",
            )

        scheduled_for = job.next_run_at
        execution = JobExecution(
            scheduled_job_id=job.id,
            user_id=job.user_id,
            idempotency_key=clock_idempotency_key(job, scheduled_for),
            scheduled_for=scheduled_for,
        )

        claimed = self._insert_and_claim(execution, now)
        if (
            claimed.outcome is not DispatchOutcomeType.DISPATCHED
            or claimed.execution is None
        ):
            # DUPLICATE (another worker owns it) or FAILED (could not record it).
            return claimed
        execution = claimed.execution

        # Only the worker holding the claim advances the schedule. Losing that
        # race is harmless: the claim, not the schedule, granted the right to run.
        decision = self.window_service.decide(job, now)
        won = self.scheduled_job_repository.try_advance_schedule(
            job.id, decision.scheduled_for, decision.next_run_at
        )

        if decision.outcome is OccurrenceOutcome.SKIP:
            execution.mark_skipped(decision.reason)
            self.job_execution_repository.save(execution)
            return DispatchOutcome(
                DispatchOutcomeType.SKIPPED, execution, decision.reason
            )

        if decision.next_run_at is None:
            # Nothing will ever fire again. Leaving the job ACTIVE with a null
            # next_run_at would strand it: not due, not terminal, never runnable.
            if won:
                if job.trigger_type is ScheduledTriggerType.ONCE:
                    job.complete()
                else:
                    job.mark_failed("the schedule has no further occurrences")
                self.scheduled_job_repository.save(job)
        elif won:
            # record_run stamps last_run_at and rolls the schedule forward.
            self.scheduled_job_repository.save(job.record_run(now, decision.next_run_at))

        return await self._execute(job, execution, now)

    async def run_event_triggered(
        self, job: ScheduledJob, event: TriggerEvent, now: datetime
    ) -> DispatchOutcome:
        """Handle an inbound event for an EVENT-triggered job."""
        execution = JobExecution(
            scheduled_job_id=job.id,
            user_id=job.user_id,
            idempotency_key=event_idempotency_key(job, event),
            scheduled_for=now,
            trigger_event_id=event.id,
        )

        claimed = self._insert_and_claim(execution, now)
        if (
            claimed.outcome is not DispatchOutcomeType.DISPATCHED
            or claimed.execution is None
        ):
            return claimed
        execution = claimed.execution

        # An event job has no clock, so its schedule is left alone entirely.
        return await self._execute(job, execution, now, event=event)

    # -- internals -------------------------------------------------------

    def _insert_and_claim(
        self, candidate: JobExecution, now: datetime
    ) -> DispatchOutcome:
        """Insert-then-claim, returning ``DUPLICATE`` if another worker won."""
        try:
            execution, created = self.job_execution_repository.create_if_absent(candidate)
        except Exception as error:  # noqa: BLE001 - surfaced as a failure outcome
            return DispatchOutcome(
                DispatchOutcomeType.FAILED,
                None,
                f"could not record the execution: {error}",
            )

        if not created:
            return DispatchOutcome(
                DispatchOutcomeType.DUPLICATE,
                execution,
                "this occurrence was already handled",
            )

        if not self.job_execution_repository.try_claim(execution.id, now):
            return DispatchOutcome(
                DispatchOutcomeType.DUPLICATE,
                execution,
                "another worker claimed this execution",
            )

        # The claim above happened in the database; the in-memory entity is still
        # QUEUED because create_if_absent read the row back before the UPDATE.
        # Bring it into line with what the row now says. Without this the entity
        # stays QUEUED, and the first transition the dispatcher attempts after
        # starting the run -- mark_waiting_permission() -- is illegal from QUEUED,
        # so every scheduled run that needed human approval would raise.
        execution.claim(now)

        return DispatchOutcome(
            DispatchOutcomeType.DISPATCHED,
            execution,
            "execution claimed",
        )

    def _concurrency_blocked(self, user_id) -> str | None:
        """Explain why this user's next run must wait, or ``None`` to proceed.

        Counts every RUNNING execution for the user, not just recent ones: a run
        that is still going after an hour is still consuming a slot, and the
        whole point of the limit is to bound how much work is in flight at once.
        """
        running = self.job_execution_repository.count_by_user_status(
            user_id, JobExecutionStatus.RUNNING
        )
        if running < self.max_concurrent_runs_per_user:
            return None
        return (
            f"{running} of this user's jobs are already running "
            f"(limit {self.max_concurrent_runs_per_user})"
        )

    def build_request(self, job: ScheduledJob, event: TriggerEvent | None) -> str:
        """Assemble the ``user_request`` the agent run will carry.

        The instruction comes from the job's own payload -- text the user typed
        when they created the job. For event triggers the event *type* is
        prepended as context, and only after passing
        :class:`TriggerEvent`'s charset validation, so it cannot carry
        arbitrary text into the prompt.
        """
        payload_prompt = job.payload.get("prompt") or job.payload.get("instruction")
        if payload_prompt is not None and not isinstance(payload_prompt, str):
            raise ValueError("job payload 'prompt' must be a string")

        if event is not None:
            body = (payload_prompt or DEFAULT_EVENT_REQUEST).strip()
            request = f"[triggered by event: {event.event_type}]\n{body}"
        else:
            request = (payload_prompt or DEFAULT_CLOCK_REQUEST).strip()

        request = request[:MAX_REQUEST_LENGTH]
        if not request:
            raise ValueError("scheduled job resolved to an empty request")
        return request

    async def _execute(
        self,
        job: ScheduledJob,
        execution: JobExecution,
        now: datetime,
        event: TriggerEvent | None = None,
    ) -> DispatchOutcome:
        blocked = self._concurrency_blocked(job.user_id)
        if blocked is not None:
            # SKIPPED, not FAILED: nothing went wrong, the user is simply at
            # their concurrency limit. The occurrence is dropped and the job
            # picks up again at its next scheduled time -- this is a deliberate
            # non-execution, which is exactly what SKIPPED exists to record.
            execution.mark_skipped(blocked)
            self.job_execution_repository.save(execution)
            return DispatchOutcome(
                DispatchOutcomeType.DEFERRED,
                execution,
                blocked,
                metadata={"error_code": ConcurrencyLimitExceeded.__name__},
            )

        try:
            request = self.build_request(job, event)
        except ValueError as error:
            execution.mark_failed(f"invalid job payload: {error}")
            self.job_execution_repository.save(execution)
            return DispatchOutcome(DispatchOutcomeType.FAILED, execution, str(error))

        try:
            # Reuses the existing use case, which rejects unknown and inactive
            # agents. A job pointing at a deleted agent fails here rather than
            # silently creating an orphan run. The job's owner is passed through,
            # so a run is created for the user the job belongs to rather than for
            # whoever happened to start the worker.
            run = self.create_agent_run.execute(job.agent_id, request, job.user_id)
        except ValueError as error:
            execution.mark_failed(f"cannot start an agent run: {error}")
            self.job_execution_repository.save(execution)
            self.scheduled_job_repository.save(job.mark_failed(str(error)))
            return DispatchOutcome(DispatchOutcomeType.FAILED, execution, str(error))

        execution.attach_run(run.id).mark_running()
        self.job_execution_repository.save(execution)

        try:
            # The job owner's id is passed as the acting user, so the Trust Engine
            # evaluates the run against the person who owns the job rather than
            # against a system identity with wider rights.
            result = await self.orchestrator.execute(run, user_id=str(job.user_id))
        except Exception as error:  # noqa: BLE001 - a crash must not lose the execution
            execution.mark_failed(f"agent run raised: {error}")
            self.job_execution_repository.save(execution)
            return DispatchOutcome(
                DispatchOutcomeType.FAILED, execution, f"agent run raised: {error}"
            )

        return self._record_result(job, execution, result)

    def _record_result(
        self,
        job: ScheduledJob,
        execution: JobExecution,
        result: AgentExecutionResult,
    ) -> DispatchOutcome:
        """Translate the agent run's terminal state into the execution's."""
        status = result.run.status

        if status is AgentRunStatus.WAITING_PERMISSION:
            execution.mark_waiting_permission()
            self.job_execution_repository.save(execution)
            # The job itself stays healthy: it is waiting on a human, not broken.
            return DispatchOutcome(
                DispatchOutcomeType.WAITING_PERMISSION,
                execution,
                result.reason or "waiting on a human decision",
                result=result,
            )

        if status is AgentRunStatus.COMPLETED:
            execution.mark_completed(result.response)
            self.job_execution_repository.save(execution)
            if job.status.is_schedulable and job.next_run_at is None:
                # A one-shot reaching its terminal state completes the job too.
                self.scheduled_job_repository.save(job.complete())
            return DispatchOutcome(
                DispatchOutcomeType.SUCCEEDED, execution, "completed", result=result
            )

        detail = result.response or f"agent run ended as {status.value}"
        execution.mark_failed(detail)
        self.job_execution_repository.save(execution)
        return DispatchOutcome(
            DispatchOutcomeType.FAILED, execution, detail, result=result
        )