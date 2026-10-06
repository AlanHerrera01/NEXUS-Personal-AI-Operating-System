"""Reading and mutating scheduled jobs.

Ownership is checked here against ``user_id`` on every path, not in the route
layer. Two consequences worth stating:

* a caller who guesses another user's job id gets the same
  ``ScheduledJobNotFound`` as one who guesses a non-existent id, so the API is
  not an enumeration oracle for "does this id exist";
* a job's ``user_id`` is immutable, which is what makes the ownership check
  meaningful at all.
"""

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.always_on.errors import (
    InvalidSchedule,
    JobExecutionNotFound,
    ScheduledJobNotFound,
)
from app.domain.entities._common import utc_now
from app.domain.entities.job_execution import JobExecution
from app.domain.entities.scheduled_job import ScheduledJob, ScheduledJobError
from app.domain.repositories.job_execution_repository import JobExecutionRepository
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository
from app.domain.value_objects.cron_expression import CronExpression, CronExpressionError
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType


@dataclass
class GetScheduledJobUseCase:
    scheduled_job_repository: ScheduledJobRepository

    def execute(self, job_id: EntityId, user_id: EntityId) -> ScheduledJob:
        job = self.scheduled_job_repository.get_by_id(job_id)
        if job is None or not job.is_owned_by(user_id):
            raise ScheduledJobNotFound(str(job_id))
        return job


@dataclass
class ListScheduledJobsUseCase:
    scheduled_job_repository: ScheduledJobRepository

    def execute(
        self,
        user_id: EntityId,
        status: ScheduledJobStatus | None = None,
        limit: int = 100,
    ) -> list[ScheduledJob]:
        return self.scheduled_job_repository.list_by_user(user_id, status, limit)


@dataclass
class PauseScheduledJobUseCase:
    scheduled_job_repository: ScheduledJobRepository

    def execute(self, job_id: EntityId, user_id: EntityId) -> ScheduledJob:
        job = GetScheduledJobUseCase(self.scheduled_job_repository).execute(job_id, user_id)
        return self.scheduled_job_repository.save(job.pause())


@dataclass
class ResumeScheduledJobUseCase:
    scheduled_job_repository: ScheduledJobRepository

    def execute(self, job_id: EntityId, user_id: EntityId) -> ScheduledJob:
        """Reactivate a paused or failed job and recompute its next fire time.

        Rescheduling from *now* rather than from the stale ``next_run_at`` stops
        a job that sat paused for a week from firing the instant it is resumed, a
        week late.
        """
        job = GetScheduledJobUseCase(self.scheduled_job_repository).execute(job_id, user_id)
        if job.status is ScheduledJobStatus.ACTIVE:
            return job
        if job.status.is_terminal and job.status is not ScheduledJobStatus.FAILED:
            # COMPLETED and CANCELLED are settled histories; reopening them
            # would resurrect work the user finished or deliberately stopped.
            raise InvalidSchedule(f"cannot resume a {job.status.value} job")

        job.activate()

        # Reschedule whenever the retained slot is missing or already in the past.
        # A paused job keeps its old next_run_at, so testing only for None would
        # leave a week-old slot in place and the job would fire the instant it
        # resumed -- a week late, exactly what this method exists to prevent.
        # A future slot is left alone so resume does not drift a schedule that
        # is still perfectly good.
        moment = utc_now()
        if job.trigger_type.is_clock_based and (
            job.next_run_at is None or job.next_run_at <= moment
        ):
            job.schedule_from(moment)
        return self.scheduled_job_repository.save(job)


@dataclass
class CancelScheduledJobUseCase:
    scheduled_job_repository: ScheduledJobRepository

    def execute(self, job_id: EntityId, user_id: EntityId) -> ScheduledJob:
        job = GetScheduledJobUseCase(self.scheduled_job_repository).execute(job_id, user_id)
        return self.scheduled_job_repository.save(job.cancel())


@dataclass
class UpdateScheduledJobUseCase:
    """Change a job's description of itself.

    The trigger *type* and the owning agent are deliberately immutable here.
    Changing the type would mean re-validating every schedule field under a new
    interpretation, and changing the agent would silently redirect work that was
    authorised against a different agent's tools. Both belong on a new job, not
    an edit of this one.
    """

    scheduled_job_repository: ScheduledJobRepository

    def execute(
        self,
        job_id: EntityId,
        user_id: EntityId,
        *,
        name: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
        cron_expression: str | None = None,
        interval_seconds: int | None = None,
        payload: dict | None = None,
    ) -> ScheduledJob:
        job = GetScheduledJobUseCase(self.scheduled_job_repository).execute(job_id, user_id)

        if job.status.is_terminal:
            raise InvalidSchedule(f"cannot edit a {job.status.value} job")

        if name is not None:
            job.name = name
        if description is not None:
            job.description = description
        if payload is not None:
            job.payload = payload

        if timezone is not None:
            try:
                job.timezone = ZoneInfo(timezone).key
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise InvalidSchedule(f"unknown IANA timezone: {timezone!r}") from error

        if cron_expression is not None:
            # Validated against the possibly-new timezone, so "09:00" cannot
            # silently keep meaning the old zone's 09:00.
            try:
                CronExpression(cron_expression, job.timezone)
            except CronExpressionError as error:
                raise InvalidSchedule(str(error)) from error
            job.cron_expression = cron_expression

        if interval_seconds is not None:
            if interval_seconds <= 0:
                raise InvalidSchedule("interval_seconds must be greater than zero")
            job.interval_seconds = interval_seconds

        try:
            job.revalidate()
        except ScheduledJobError as error:
            raise InvalidSchedule(str(error)) from error

        if job.trigger_type.is_clock_based:
            job.schedule_from(utc_now())
        return self.scheduled_job_repository.save(job)


@dataclass
class ListJobExecutionsUseCase:
    job_execution_repository: JobExecutionRepository
    scheduled_job_repository: ScheduledJobRepository

    def execute(
        self, job_id: EntityId, user_id: EntityId, limit: int = 50
    ) -> list[JobExecution]:
        job = GetScheduledJobUseCase(self.scheduled_job_repository).execute(job_id, user_id)
        return self.job_execution_repository.list_by_job(job.id, limit)


@dataclass
class GetJobExecutionUseCase:
    job_execution_repository: JobExecutionRepository

    def execute(self, execution_id: EntityId, user_id: EntityId) -> JobExecution:
        execution = self.job_execution_repository.get_by_id(execution_id)
        if execution is None or not execution.is_owned_by(user_id):
            raise JobExecutionNotFound(str(execution_id))
        return execution