"""SQLAlchemy adapter for :class:`ScheduledJob`.

Follows the established repository pattern in this codebase: the session is
injected, :meth:`save` commits and returns the re-read row, and every timezone
is stored as UTC in a ``DateTime(timezone=True)`` column. The job's own timezone
is a *string* alongside it and is only used when computing the next fire time, so
changing the zone never rewrites history.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.domain.entities.scheduled_job import ScheduledJob
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType
from app.infrastructure.persistence.mappers.datetime_normaliser import ensure_utc
from app.infrastructure.persistence.models import ScheduledJobModel


class SqlAlchemyScheduledJobRepository(ScheduledJobRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, job: ScheduledJob) -> ScheduledJob:
        model = self.session.get(ScheduledJobModel, job.id.value)
        if model is None:
            model = ScheduledJobModel(id=job.id.value)
            self.session.add(model)

        model.user_id = job.user_id.value
        model.agent_id = job.agent_id.value
        model.name = job.name
        model.description = job.description
        model.trigger_type = job.trigger_type.value
        model.timezone = job.timezone
        model.cron_expression = job.cron_expression
        model.interval_seconds = job.interval_seconds
        model.payload = dict(job.payload)
        model.status = job.status.value
        model.next_run_at = job.next_run_at
        model.last_run_at = job.last_run_at
        model.last_error = job.last_error
        model.created_at = job.created_at
        # Written explicitly rather than relying on onupdate=func.now(), so the
        # stored timestamp always matches the entity the caller is holding.
        model.updated_at = job.updated_at

        self.session.commit()
        stored = self.session.get(ScheduledJobModel, job.id.value)
        return self._to_entity(stored)

    def get_by_id(self, job_id: EntityId) -> ScheduledJob | None:
        model = self.session.get(ScheduledJobModel, job_id.value)
        return self._to_entity(model) if model else None

    def list_by_user(
        self,
        user_id: EntityId,
        status: ScheduledJobStatus | None = None,
        limit: int = 100,
    ) -> list[ScheduledJob]:
        statement = select(ScheduledJobModel).where(
            ScheduledJobModel.user_id == user_id.value
        )
        if status is not None:
            statement = statement.where(ScheduledJobModel.status == status.value)
        models = self.session.scalars(
            statement.order_by(ScheduledJobModel.created_at.desc()).limit(limit)
        ).all()
        return [self._to_entity(model) for model in models]

    def list_due(self, now, limit: int = 50) -> list[ScheduledJob]:
        """Active clock jobs whose ``next_run_at`` has arrived.

        EVENT jobs are excluded in the query rather than filtered in Python: they
        hold a null ``next_run_at`` and would never match the predicate anyway,
        but stating the intent keeps the two cases from being conflated later.
        """
        clock_types = [
            trigger.value
            for trigger in ScheduledTriggerType
            if trigger.is_clock_based
        ]
        statement = (
            select(ScheduledJobModel)
            .where(
                ScheduledJobModel.status == ScheduledJobStatus.ACTIVE.value,
                ScheduledJobModel.next_run_at.is_not(None),
                ScheduledJobModel.next_run_at <= now,
                ScheduledJobModel.trigger_type.in_(clock_types),
            )
            .order_by(ScheduledJobModel.next_run_at.asc())
            .limit(limit)
        )
        models = self.session.scalars(statement).all()
        return [self._to_entity(model) for model in models]

    def count_active_for_user(self, user_id: EntityId) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(ScheduledJobModel)
                .where(
                    ScheduledJobModel.user_id == user_id.value,
                    ScheduledJobModel.status == ScheduledJobStatus.ACTIVE.value,
                )
            )
            or 0
        )

    def try_advance_schedule(
        self,
        job_id: EntityId,
        expected_next_run_at,
        new_next_run_at,
    ) -> bool:
        """Compare-and-set on ``next_run_at``.

        The ``expected`` value is part of the WHERE clause rather than checked in
        Python, which is the entire point: two workers polling the same due job
        both read the same timestamp, and only the first UPDATE matches a row.
        The loser gets ``rowcount == 0`` and abandons the occurrence without
        dispatching it.
        """
        statement = (
            update(ScheduledJobModel)
            .where(
                ScheduledJobModel.id == job_id.value,
                ScheduledJobModel.next_run_at == expected_next_run_at,
            )
            .values(next_run_at=new_next_run_at, updated_at=func.now())
        )
        result = self.session.execute(statement)
        self.session.commit()
        return result.rowcount == 1

    # -- mapping ---------------------------------------------------------

    def _to_entity(self, model: ScheduledJobModel) -> ScheduledJob:
        return ScheduledJob(
            id=EntityId(model.id),
            user_id=EntityId(model.user_id),
            agent_id=EntityId(model.agent_id),
            name=model.name,
            description=model.description or "",
            trigger_type=ScheduledTriggerType(model.trigger_type),
            timezone=model.timezone,
            cron_expression=model.cron_expression,
            interval_seconds=model.interval_seconds,
            payload=dict(model.payload or {}),
            status=ScheduledJobStatus(model.status),
            next_run_at=ensure_utc(model.next_run_at),
            last_run_at=ensure_utc(model.last_run_at),
            last_error=model.last_error,
            created_at=ensure_utc(model.created_at),
            updated_at=ensure_utc(model.updated_at),
        )