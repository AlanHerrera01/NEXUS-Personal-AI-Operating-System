"""SQLAlchemy adapter for :class:`JobExecution`.

The two methods that make concurrent dispatch safe are
:meth:`create_if_absent` and :meth:`try_claim`, and both are deliberately
written to swallow the *expected* concurrency outcome rather than propagate it:

* ``create_if_absent`` catches the unique-violation on ``idempotency_key`` and
  re-reads the winning row. A duplicate is the normal steady state when N
  workers find the same occurrence due, not an exceptional condition.
* ``try_claim`` is a conditional UPDATE whose ``status = 'QUEUED'`` predicate
  makes the claim atomic without an explicit row lock. The winner is decided by
  ``rowcount``, so the outcome is decided by the database rather than by which
  worker read the row first.
"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities.job_execution import JobExecution
from app.domain.repositories.job_execution_repository import JobExecutionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.job_execution_status import JobExecutionStatus
from app.infrastructure.persistence.mappers.datetime_normaliser import ensure_utc
from app.infrastructure.persistence.models import JobExecutionModel


class SqlAlchemyJobExecutionRepository(JobExecutionRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, execution: JobExecution) -> JobExecution:
        model = self.session.get(JobExecutionModel, execution.id.value)
        if model is None:
            model = JobExecutionModel(id=execution.id.value)
            self.session.add(model)
        self._write(model, execution)
        self.session.commit()
        stored = self.session.get(JobExecutionModel, execution.id.value)
        return self._to_entity(stored)

    def create_if_absent(self, execution: JobExecution) -> tuple[JobExecution, bool]:
        existing = self.get_by_idempotency_key(execution.idempotency_key)
        if existing is not None:
            return existing, False

        model = JobExecutionModel(id=execution.id.value)
        self._write(model, execution)
        self.session.add(model)
        try:
            self.session.commit()
        except IntegrityError:
            # Another process inserted the same key between our lookup and our
            # insert. Roll back and hand back the row that won.
            self.session.rollback()
            winner = self.get_by_idempotency_key(execution.idempotency_key)
            if winner is None:
                # The key exists but cannot be read back; that is a real fault,
                # not a race, and must not be reported as a duplicate.
                raise
            return winner, False
        return self._to_entity(self.session.get(JobExecutionModel, execution.id.value)), True

    def get_by_id(self, execution_id: EntityId) -> JobExecution | None:
        model = self.session.get(JobExecutionModel, execution_id.value)
        return self._to_entity(model) if model else None

    def get_by_idempotency_key(self, idempotency_key: str) -> JobExecution | None:
        model = self.session.scalar(
            select(JobExecutionModel).where(
                JobExecutionModel.idempotency_key == idempotency_key
            )
        )
        return self._to_entity(model) if model else None

    def try_claim(self, execution_id: EntityId, now: datetime) -> bool:
        statement = (
            update(JobExecutionModel)
            .where(
                JobExecutionModel.id == execution_id.value,
                JobExecutionModel.status == JobExecutionStatus.QUEUED.value,
            )
            .values(
                status=JobExecutionStatus.RUNNING.value,
                claimed_at=ensure_utc(now),
                updated_at=ensure_utc(now),
            )
        )
        result = self.session.execute(statement)
        self.session.commit()
        return result.rowcount == 1

    def get_open_by_run(self, agent_run_id: EntityId) -> JobExecution | None:
        open_statuses = [status.value for status in JobExecutionStatus if status.is_open]
        model = self.session.scalar(
            select(JobExecutionModel)
            .where(
                JobExecutionModel.agent_run_id == agent_run_id.value,
                JobExecutionModel.status.in_(open_statuses),
            )
            .order_by(JobExecutionModel.created_at.desc())
            .limit(1)
        )
        return self._to_entity(model) if model else None

    def list_by_job(
        self, scheduled_job_id: EntityId, limit: int = 50
    ) -> list[JobExecution]:
        models = self.session.scalars(
            select(JobExecutionModel)
            .where(JobExecutionModel.scheduled_job_id == scheduled_job_id.value)
            .order_by(JobExecutionModel.scheduled_for.desc())
            .limit(limit)
        ).all()
        return [self._to_entity(model) for model in models]

    def list_by_user(self, user_id: EntityId, limit: int = 100) -> list[JobExecution]:
        models = self.session.scalars(
            select(JobExecutionModel)
            .where(JobExecutionModel.user_id == user_id.value)
            .order_by(JobExecutionModel.created_at.desc())
            .limit(limit)
        ).all()
        return [self._to_entity(model) for model in models]

    def list_by_status(
        self, status: JobExecutionStatus, limit: int = 100
    ) -> list[JobExecution]:
        models = self.session.scalars(
            select(JobExecutionModel)
            .where(JobExecutionModel.status == status.value)
            .order_by(JobExecutionModel.created_at.asc())
            .limit(limit)
        ).all()
        return [self._to_entity(model) for model in models]

    def count_by_user_status(
        self, user_id: EntityId, status: JobExecutionStatus
    ) -> int:
        """Count a user's executions in ``status``.

        Deliberately unbounded by time. A run that started an hour ago is still
        holding a concurrency slot, so scoping this by recency would let a user
        exceed the limit precisely when their runs are slow. Served directly by
        ``ix_job_executions_user_status``.
        """
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(JobExecutionModel)
                .where(
                    JobExecutionModel.user_id == user_id.value,
                    JobExecutionModel.status == status.value,
                )
            )
            or 0
        )

    def count_by_user_since(
        self, user_id: EntityId, since: datetime, status: JobExecutionStatus
    ) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(JobExecutionModel)
                .where(
                    JobExecutionModel.user_id == user_id.value,
                    JobExecutionModel.status == status.value,
                    JobExecutionModel.created_at >= ensure_utc(since),
                )
            )
            or 0
        )

    # -- mapping ---------------------------------------------------------

    def _write(self, model: JobExecutionModel, execution: JobExecution) -> None:
        model.scheduled_job_id = execution.scheduled_job_id.value
        model.agent_run_id = execution.agent_run_id.value if execution.agent_run_id else None
        model.trigger_event_id = (
            execution.trigger_event_id.value if execution.trigger_event_id else None
        )
        model.user_id = execution.user_id.value
        model.idempotency_key = execution.idempotency_key
        model.status = execution.status.value
        model.scheduled_for = ensure_utc(execution.scheduled_for)
        model.attempt = execution.attempt
        model.result_summary = execution.result_summary
        model.error_message = execution.error_message
        model.claimed_at = ensure_utc(execution.claimed_at)
        model.started_at = ensure_utc(execution.started_at)
        model.completed_at = ensure_utc(execution.completed_at)
        model.created_at = ensure_utc(execution.created_at)
        model.updated_at = ensure_utc(execution.updated_at)

    def _to_entity(self, model: JobExecutionModel) -> JobExecution:
        return JobExecution(
            id=EntityId(model.id),
            scheduled_job_id=EntityId(model.scheduled_job_id),
            user_id=EntityId(model.user_id),
            agent_run_id=EntityId(model.agent_run_id) if model.agent_run_id else None,
            trigger_event_id=(
                EntityId(model.trigger_event_id) if model.trigger_event_id else None
            ),
            idempotency_key=model.idempotency_key,
            status=JobExecutionStatus(model.status),
            scheduled_for=ensure_utc(model.scheduled_for),
            attempt=model.attempt,
            result_summary=model.result_summary,
            error_message=model.error_message,
            claimed_at=ensure_utc(model.claimed_at),
            started_at=ensure_utc(model.started_at),
            completed_at=ensure_utc(model.completed_at),
            created_at=ensure_utc(model.created_at),
            updated_at=ensure_utc(model.updated_at),
        )