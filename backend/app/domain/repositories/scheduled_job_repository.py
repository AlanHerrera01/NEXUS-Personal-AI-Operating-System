from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.scheduled_job import ScheduledJob
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus


class ScheduledJobRepository(ABC):
    """Persistence for :class:`ScheduledJob`.

    The interesting method is :meth:`try_advance_schedule`. Advancing a job's
    ``next_run_at`` is the step that decides "has this occurrence been handled",
    so it must not be a read-then-write: with N workers polling, all N will read
    the same due job and all N would dispatch it. The SQL implementation makes
    the write conditional on the row still holding the value the worker read, so
    exactly one worker's update affects a row and the losers see ``False``.
    """

    @abstractmethod
    def save(self, job: ScheduledJob) -> ScheduledJob:
        """Insert or update the job and return the stored state."""

    @abstractmethod
    def get_by_id(self, job_id: EntityId) -> ScheduledJob | None:
        """Return the job regardless of who owns it."""

    @abstractmethod
    def list_by_user(
        self,
        user_id: EntityId,
        status: ScheduledJobStatus | None = None,
        limit: int = 100,
    ) -> list[ScheduledJob]:
        """Jobs owned by ``user_id``, newest first."""

    @abstractmethod
    def list_due(self, now: datetime, limit: int = 50) -> list[ScheduledJob]:
        """Active clock-based jobs whose ``next_run_at`` is at or before ``now``."""

    @abstractmethod
    def count_active_for_user(self, user_id: EntityId) -> int:
        """Count of ACTIVE jobs, used to enforce the per-user quota."""

    @abstractmethod
    def try_advance_schedule(
        self,
        job_id: EntityId,
        expected_next_run_at: datetime,
        new_next_run_at: datetime | None,
    ) -> bool:
        """Compare-and-set on ``next_run_at``.

        Returns ``True`` only for the caller whose write won the race. ``False``
        means another worker already handled that occurrence, and the caller
        must abandon it without dispatching.
        """