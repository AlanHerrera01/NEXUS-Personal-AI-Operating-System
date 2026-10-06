from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.job_execution import JobExecution
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.job_execution_status import JobExecutionStatus


class JobExecutionRepository(ABC):
    """Persistence for :class:`JobExecution`.

    ``idempotency_key`` carries a unique constraint in the database. Two workers
    that independently decide to handle the same occurrence both try to insert
    the same key; one commits and the other hits the constraint. That is the
    intended mechanism for collapsing at-least-once dispatch, and it is why
    :meth:`create_if_absent` returns an existing row instead of raising.

    :meth:`try_claim` is a second compare-and-set, and it exists for a different
    race: the process that inserted an execution can die before running it, and
    another worker may pick it up later. Only one of them may move it to
    RUNNING.
    """

    @abstractmethod
    def save(self, execution: JobExecution) -> JobExecution:
        """Insert or update the execution and return the stored state."""

    @abstractmethod
    def create_if_absent(self, execution: JobExecution) -> tuple[JobExecution, bool]:
        """Insert unless ``idempotency_key`` already exists.

        Returns ``(execution, True)`` when this call created it and
        ``(existing, False)`` when the key was already taken. Must not raise on
        a duplicate key -- a duplicate is the expected steady state under
        concurrent dispatch, not an error.
        """

    @abstractmethod
    def get_by_id(self, execution_id: EntityId) -> JobExecution | None: ...

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> JobExecution | None: ...

    @abstractmethod
    def get_open_by_run(self, agent_run_id: EntityId) -> JobExecution | None:
        """The non-terminal execution driving ``agent_run_id``, if there is one.

        Used by the approval reconciliation hook to find the job execution that
        is parked on a human decision. Manual runs have no execution and return
        ``None``, which is how the hook distinguishes the two cases.
        """

    @abstractmethod
    def try_claim(self, execution_id: EntityId, now: datetime) -> bool:
        """Atomically move a QUEUED execution to RUNNING.

        Returns ``True`` only for the caller that won the transition.
        """

    @abstractmethod
    def list_by_job(
        self, scheduled_job_id: EntityId, limit: int = 50
    ) -> list[JobExecution]:
        """History for one job, newest first."""

    @abstractmethod
    def list_by_user(
        self, user_id: EntityId, limit: int = 100
    ) -> list[JobExecution]:
        """History across all of a user's jobs, newest first."""

    @abstractmethod
    def list_by_status(
        self,
        status: JobExecutionStatus,
        limit: int = 100,
    ) -> list[JobExecution]:
        """Executions in a given state, used by the recovery sweep."""

    @abstractmethod
    def count_by_user_status(
        self, user_id: EntityId, status: JobExecutionStatus
    ) -> int:
        """Count a user's executions currently in ``status``, with no time window.

        This is what the per-user concurrency limit needs. It has to count every
        execution that is *right now* RUNNING regardless of when it started: a run
        that began an hour ago is still occupying a concurrency slot, so bounding
        the query by recency would let the limit be exceeded by long-running work.
        """

    @abstractmethod
    def count_by_user_since(
        self, user_id: EntityId, since: datetime, status: JobExecutionStatus
    ) -> int:
        """Count executions in a status created since ``since``.

        A genuinely time-windowed query, used for the event ingress rate limit.
        Deliberately not used for concurrency limits -- see
        :meth:`count_by_user_status` for why those differ.
        """