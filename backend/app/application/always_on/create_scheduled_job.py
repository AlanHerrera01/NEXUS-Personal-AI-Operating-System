"""Creates a scheduled job, refusing every schedule it will not honour.

Validation happens here rather than in the entity because most of it needs a
reference time and configuration the entity has no business knowing: the
per-user quota, the floor on interval length, the agent's existence. The entity
still re-validates everything it can on its own, so a job built by a mapper or a
test cannot skip these checks -- it just cannot repeat the ones that need a
clock.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.always_on.errors import (
    IntervalTooShort,
    InvalidSchedule,
    JobQuotaExceeded,
)
from app.domain.entities._common import utc_now
from app.domain.entities.scheduled_job import ScheduledJob, ScheduledJobError
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.cron_expression import CronExpression, CronExpressionError
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType


@dataclass
class CreateScheduledJobUseCase:
    agent_repository: AgentRepository
    scheduled_job_repository: ScheduledJobRepository
    max_active_jobs_per_user: int = 20
    min_interval_seconds: int = 300

    def execute(
        self,
        *,
        user_id: EntityId,
        agent_id: EntityId,
        name: str,
        trigger_type: ScheduledTriggerType | str,
        now: datetime | None = None,
        description: str = "",
        timezone: str = "UTC",
        cron_expression: str | None = None,
        interval_seconds: int | None = None,
        run_at: datetime | None = None,
        payload: dict | None = None,
    ) -> ScheduledJob:
        moment = now or utc_now()
        trigger = ScheduledTriggerType(trigger_type)

        # Scoped to the requesting owner: scheduling a job against an agent you
        # do not own would create a recurring, unattended path into it.
        agent = self.agent_repository.get_by_id(agent_id, user_id)
        if agent is None:
            raise ValueError("agent not found")
        if agent.status is not AgentStatus.ACTIVE:
            # Scheduling work for an agent that cannot start runs would produce a
            # job that fails on every single fire.
            raise ValueError("inactive agents cannot have scheduled jobs")

        active = self.scheduled_job_repository.count_active_for_user(user_id)
        if active >= self.max_active_jobs_per_user:
            raise JobQuotaExceeded(active, self.max_active_jobs_per_user)

        zone = self._resolve_timezone(timezone)
        job = self._build(
            user_id=user_id,
            agent_id=agent_id,
            name=name,
            description=description,
            trigger=trigger,
            zone_name=zone.key,
            cron_expression=cron_expression,
            interval_seconds=interval_seconds,
            run_at=run_at,
            payload=payload or {},
        )
        job.schedule_from(moment)

        if trigger is ScheduledTriggerType.ONCE:
            # schedule_from deliberately leaves a one-shot's time alone, so this
            # comparison is against the instant the caller actually asked for.
            assert job.next_run_at is not None
            if job.next_run_at <= moment:
                raise InvalidSchedule("run_at must be in the future")

        return self.scheduled_job_repository.save(job)

    # -- internals -------------------------------------------------------

    def _resolve_timezone(self, timezone: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise InvalidSchedule(f"unknown IANA timezone: {timezone!r}") from error

    def _build(
        self,
        *,
        user_id: EntityId,
        agent_id: EntityId,
        name: str,
        description: str,
        trigger: ScheduledTriggerType,
        zone_name: str,
        cron_expression: str | None,
        interval_seconds: int | None,
        run_at: datetime | None,
        payload: dict,
    ) -> ScheduledJob:
        if trigger is ScheduledTriggerType.CRON:
            if not cron_expression:
                raise InvalidSchedule("CRON jobs require cron_expression")
            try:
                CronExpression(cron_expression, zone_name)
            except CronExpressionError as error:
                raise InvalidSchedule(str(error)) from error
            next_run_at = None

        elif trigger is ScheduledTriggerType.INTERVAL:
            if interval_seconds is None:
                raise InvalidSchedule("INTERVAL jobs require interval_seconds")
            if interval_seconds < self.min_interval_seconds:
                # Without a floor, a 1-second interval is a denial-of-service
                # button that spends LLM calls and opens agent runs forever.
                raise IntervalTooShort(interval_seconds, self.min_interval_seconds)
            next_run_at = None

        elif trigger is ScheduledTriggerType.ONCE:
            if run_at is None:
                raise InvalidSchedule("ONCE jobs require run_at")
            if run_at.tzinfo is None:
                raise InvalidSchedule("run_at must be timezone-aware")
            next_run_at = run_at

        else:  # EVENT
            if not payload.get("event_type") and not payload.get("event_types"):
                raise InvalidSchedule(
                    "EVENT jobs require payload.event_type or payload.event_types"
                )
            next_run_at = None

        try:
            return ScheduledJob(
                user_id=user_id,
                agent_id=agent_id,
                name=name,
                description=description,
                trigger_type=trigger,
                timezone=zone_name,
                cron_expression=cron_expression if trigger is ScheduledTriggerType.CRON else None,
                interval_seconds=(
                    interval_seconds if trigger is ScheduledTriggerType.INTERVAL else None
                ),
                payload=payload,
                next_run_at=next_run_at,
            )
        except ScheduledJobError as error:
            raise InvalidSchedule(str(error)) from error