"""HTTP surface for scheduled jobs and their execution history.

Ownership is resolved by :mod:`app.presentation.dependencies.identity` and checked
inside the use cases, never here. The routes translate domain errors into status
codes and otherwise stay out of the way, so the authorisation rule that matters
has exactly one implementation to test.

The feature flag is enforced only on operations that *start work* -- creating a
job and ingesting an event. Reads, pauses and deletes stay available when the
scheduler is switched off, because a user who disables the feature still needs to
see and clean up the jobs they already created.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.application.always_on.create_scheduled_job import CreateScheduledJobUseCase
from app.application.always_on.errors import (
    AlwaysOnDisabled,
    AlwaysOnError,
    IntervalTooShort,
    InvalidSchedule,
    JobExecutionNotFound,
    JobQuotaExceeded,
    ScheduledJobNotFound,
)
from app.application.always_on.manage_scheduled_job import (
    CancelScheduledJobUseCase,
    GetJobExecutionUseCase,
    GetScheduledJobUseCase,
    ListJobExecutionsUseCase,
    ListScheduledJobsUseCase,
    PauseScheduledJobUseCase,
    ResumeScheduledJobUseCase,
    UpdateScheduledJobUseCase,
)
from app.config.settings import Settings, get_settings
from app.domain.entities.job_execution import JobExecution
from app.domain.entities.scheduled_job import ScheduledJob
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType
from app.presentation.dependencies.always_on import (
    get_cancel_scheduled_job_use_case,
    get_create_scheduled_job_use_case,
    get_get_job_execution_use_case,
    get_get_scheduled_job_use_case,
    get_list_job_executions_use_case,
    get_list_scheduled_jobs_use_case,
    get_pause_scheduled_job_use_case,
    get_resume_scheduled_job_use_case,
    get_update_scheduled_job_use_case,
)
from app.presentation.dependencies.identity import LOCAL_USER_ID

router = APIRouter(prefix="/api/v1/scheduled-jobs", tags=["always-on"])


# -- schemas ----------------------------------------------------------


class ScheduledJobResponse(BaseModel):
    id: str
    user_id: str
    agent_id: str
    name: str
    description: str
    trigger_type: str
    timezone: str
    cron_expression: str | None
    interval_seconds: int | None
    payload: dict
    status: str
    next_run_at: str | None
    last_run_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_entity(cls, job: ScheduledJob) -> "ScheduledJobResponse":
        return cls(
            id=str(job.id),
            user_id=str(job.user_id),
            agent_id=str(job.agent_id),
            name=job.name,
            description=job.description,
            trigger_type=job.trigger_type.value,
            timezone=job.timezone,
            cron_expression=job.cron_expression,
            interval_seconds=job.interval_seconds,
            payload=job.payload,
            status=job.status.value,
            next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
            last_run_at=job.last_run_at.isoformat() if job.last_run_at else None,
            last_error=job.last_error,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )


class JobExecutionResponse(BaseModel):
    id: str
    scheduled_job_id: str
    agent_run_id: str | None
    trigger_event_id: str | None
    status: str
    scheduled_for: str
    attempt: int
    result_summary: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_entity(cls, execution: JobExecution) -> "JobExecutionResponse":
        return cls(
            id=str(execution.id),
            scheduled_job_id=str(execution.scheduled_job_id),
            agent_run_id=(
                str(execution.agent_run_id) if execution.agent_run_id else None
            ),
            trigger_event_id=(
                str(execution.trigger_event_id) if execution.trigger_event_id else None
            ),
            status=execution.status.value,
            scheduled_for=execution.scheduled_for.isoformat(),
            attempt=execution.attempt,
            result_summary=execution.result_summary,
            error_message=execution.error_message,
            created_at=execution.created_at.isoformat(),
            started_at=execution.started_at.isoformat() if execution.started_at else None,
            completed_at=(
                execution.completed_at.isoformat() if execution.completed_at else None
            ),
        )


class CreateScheduledJobRequest(BaseModel):
    agent_id: str
    name: str = Field(min_length=1, max_length=200)
    trigger_type: str
    description: str = ""
    timezone: str = "UTC"
    cron_expression: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None
    payload: dict = Field(default_factory=dict)


class UpdateScheduledJobRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    timezone: str | None = None
    cron_expression: str | None = None
    interval_seconds: int | None = None
    payload: dict | None = None


# -- error translation ------------------------------------------------


def _raise_for(error: AlwaysOnError) -> None:
    """Map a domain failure to the closest HTTP status.

    Ownership failures deliberately collapse onto 404. Returning 403 for "not
    yours" and 404 for "does not exist" would let a caller enumerate which job
    ids are real, so both cases answer the same way.
    """
    if isinstance(error, (ScheduledJobNotFound, JobExecutionNotFound)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, AlwaysOnDisabled):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, (JobQuotaExceeded, IntervalTooShort)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, InvalidSchedule):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


# -- routes -----------------------------------------------------------


@router.get("", response_model=list[ScheduledJobResponse])
async def list_scheduled_jobs(
    job_status: ScheduledJobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    service: ListScheduledJobsUseCase = Depends(get_list_scheduled_jobs_use_case),
) -> list[ScheduledJobResponse]:
    jobs = service.execute(EntityId(LOCAL_USER_ID), job_status, limit)
    return [ScheduledJobResponse.from_entity(job) for job in jobs]


@router.post("", response_model=ScheduledJobResponse, status_code=status.HTTP_201_CREATED)
async def create_scheduled_job(
    body: CreateScheduledJobRequest,
    service: CreateScheduledJobUseCase = Depends(get_create_scheduled_job_use_case),
    settings: Settings = Depends(get_settings),
) -> ScheduledJobResponse:
    """Create a job.

    Refused with 503 while the feature flag is off, because creating a job that
    nothing will ever run is worse than refusing: the user would believe they had
    set something up.
    """
    if not settings.always_on_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Always-On is disabled in this deployment (always_on_enabled)",
        )

    try:
        trigger = ScheduledTriggerType(body.trigger_type)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown trigger_type: {body.trigger_type!r}",
        ) from error

    try:
        job = service.execute(
            user_id=EntityId(LOCAL_USER_ID),
            agent_id=EntityId.from_string(body.agent_id),
            name=body.name,
            trigger_type=trigger,
            description=body.description,
            timezone=body.timezone,
            cron_expression=body.cron_expression,
            interval_seconds=body.interval_seconds,
            run_at=body.run_at,
            payload=body.payload,
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise  # unreachable; _raise_for always raises
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    return ScheduledJobResponse.from_entity(job)


@router.get("/{job_id}", response_model=ScheduledJobResponse)
async def get_scheduled_job(
    job_id: str,
    service: GetScheduledJobUseCase = Depends(get_get_scheduled_job_use_case),
) -> ScheduledJobResponse:
    try:
        job = service.execute(
            EntityId.from_string(job_id), EntityId(LOCAL_USER_ID)
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return ScheduledJobResponse.from_entity(job)


@router.patch("/{job_id}", response_model=ScheduledJobResponse)
async def update_scheduled_job(
    job_id: str,
    body: UpdateScheduledJobRequest,
    service: UpdateScheduledJobUseCase = Depends(get_update_scheduled_job_use_case),
) -> ScheduledJobResponse:
    try:
        job = service.execute(
            EntityId.from_string(job_id),
            EntityId(LOCAL_USER_ID),
            name=body.name,
            description=body.description,
            timezone=body.timezone,
            cron_expression=body.cron_expression,
            interval_seconds=body.interval_seconds,
            payload=body.payload,
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return ScheduledJobResponse.from_entity(job)


@router.post("/{job_id}/pause", response_model=ScheduledJobResponse)
async def pause_scheduled_job(
    job_id: str,
    service: PauseScheduledJobUseCase = Depends(get_pause_scheduled_job_use_case),
) -> ScheduledJobResponse:
    try:
        job = service.execute(
            EntityId.from_string(job_id), EntityId(LOCAL_USER_ID)
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return ScheduledJobResponse.from_entity(job)


@router.post("/{job_id}/resume", response_model=ScheduledJobResponse)
async def resume_scheduled_job(
    job_id: str,
    service: ResumeScheduledJobUseCase = Depends(get_resume_scheduled_job_use_case),
) -> ScheduledJobResponse:
    try:
        job = service.execute(
            EntityId.from_string(job_id), EntityId(LOCAL_USER_ID)
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return ScheduledJobResponse.from_entity(job)


@router.delete("/{job_id}", response_model=ScheduledJobResponse)
async def cancel_scheduled_job(
    job_id: str,
    service: CancelScheduledJobUseCase = Depends(get_cancel_scheduled_job_use_case),
) -> ScheduledJobResponse:
    """Cancel a job.

    DELETE maps to cancel rather than to row deletion on purpose: the execution
    history is the answer to "did this ever run?", and destroying it would make
    that unanswerable.
    """
    try:
        job = service.execute(
            EntityId.from_string(job_id), EntityId(LOCAL_USER_ID)
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return ScheduledJobResponse.from_entity(job)


@router.get("/{job_id}/executions", response_model=list[JobExecutionResponse])
async def list_job_executions(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    service: ListJobExecutionsUseCase = Depends(get_list_job_executions_use_case),
) -> list[JobExecutionResponse]:
    try:
        executions = service.execute(
            EntityId.from_string(job_id), EntityId(LOCAL_USER_ID), limit
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return [JobExecutionResponse.from_entity(item) for item in executions]


@router.get("/executions/{execution_id}", response_model=JobExecutionResponse)
async def get_job_execution(
    execution_id: str,
    service: GetJobExecutionUseCase = Depends(get_get_job_execution_use_case),
) -> JobExecutionResponse:
    try:
        execution = service.execute(
            EntityId.from_string(execution_id), EntityId(LOCAL_USER_ID)
        )
    except AlwaysOnError as error:
        _raise_for(error)
        raise
    return JobExecutionResponse.from_entity(execution)