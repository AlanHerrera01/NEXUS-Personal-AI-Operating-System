"""One attempt to run a :class:`ScheduledJob`.

This is a thin record on purpose. It does not duplicate run state: the agent
run owns the reasoning lifecycle, and this owns only the questions the run
cannot answer for itself -- was this occurrence already claimed, what triggered
it, did the worker die halfway, and is a human still holding it open.

The ``idempotency_key`` is the load-bearing field. Every dispatcher, from any
worker, derives it deterministically from ``(scheduled_job_id,
scheduled_for)`` or ``(scheduled_job_id, trigger_event_id)`` and the database
carries a unique constraint on it. Two workers racing on the same occurrence
therefore produce one row: the loser's insert violates the constraint and it
treats the occurrence as already handled. That is what makes at-least-once
dispatch collapse into effectively-once without a distributed lock.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.job_execution_status import (
    ALLOWED_TRANSITIONS,
    JobExecutionStatus,
)


class JobExecutionError(ValueError):
    """The execution cannot exist in the state its fields describe."""


@dataclass
class JobExecution:
    """A single attempt to fire a scheduled job."""

    scheduled_job_id: EntityId
    user_id: EntityId
    idempotency_key: str
    scheduled_for: datetime
    id: EntityId = field(default_factory=EntityId.new)
    agent_run_id: EntityId | None = None
    trigger_event_id: EntityId | None = None
    status: JobExecutionStatus = JobExecutionStatus.QUEUED
    attempt: int = 1
    result_summary: str | None = None
    error_message: str | None = None
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.idempotency_key, "idempotency_key")
        if len(self.idempotency_key) > 300:
            raise JobExecutionError("idempotency_key exceeds 300 characters")
        if self.scheduled_for.tzinfo is None:
            raise JobExecutionError("scheduled_for must be timezone-aware")
        if self.attempt < 1:
            raise JobExecutionError("attempt must be at least 1")
        try:
            self.status = JobExecutionStatus(self.status)
        except ValueError as error:
            raise JobExecutionError(f"invalid execution status: {self.status}") from error

    # -- lifecycle -------------------------------------------------------

    def transition_to(self, status: JobExecutionStatus) -> "JobExecution":
        try:
            target = JobExecutionStatus(status)
        except ValueError as error:
            raise JobExecutionError(f"invalid execution status: {status}") from error
        if target is self.status:
            return self
        allowed = ALLOWED_TRANSITIONS[self.status]
        if target not in allowed:
            raise JobExecutionError(
                f"invalid job execution transition: {self.status.value} -> {target.value}"
            )
        self.status = target
        self.updated_at = utc_now()
        return self

    def claim(self, now: datetime | None = None) -> "JobExecution":
        """Take ownership of this occurrence.

        Only QUEUED may be claimed. A worker that finds an already-claimed row
        stops there, which is what makes the claim the unit of concurrency
        control rather than the scheduler loop itself.
        """
        moment = now or utc_now()
        self.claimed_at = moment
        self.updated_at = moment
        return self.transition_to(JobExecutionStatus.RUNNING)

    def attach_run(self, agent_run_id: EntityId) -> "JobExecution":
        """Link the agent run this execution created."""
        if self.agent_run_id is not None and self.agent_run_id != agent_run_id:
            raise JobExecutionError("execution is already linked to a different run")
        self.agent_run_id = agent_run_id
        self.updated_at = utc_now()
        return self

    def mark_running(self) -> "JobExecution":
        self.started_at = utc_now()
        self.updated_at = self.started_at
        return self

    def mark_waiting_permission(self) -> "JobExecution":
        """Suspend on a human decision.

        Deliberately does not set ``completed_at``: the execution is still open
        and a restart must find it here and wait, not retry.
        """
        return self.transition_to(JobExecutionStatus.WAITING_PERMISSION)

    def mark_completed(self, summary: str | None = None) -> "JobExecution":
        if summary:
            self.result_summary = summary[:2_000]
        self.completed_at = utc_now()
        self.updated_at = self.completed_at
        return self.transition_to(JobExecutionStatus.COMPLETED)

    def mark_failed(self, reason: str) -> "JobExecution":
        self.error_message = reason[:2_000] if reason else "unspecified failure"
        self.completed_at = utc_now()
        self.updated_at = self.completed_at
        return self.transition_to(JobExecutionStatus.FAILED)

    def mark_skipped(self, reason: str) -> "JobExecution":
        """Record a deliberate non-execution, e.g. a missed occurrence."""
        self.error_message = reason[:2_000] if reason else None
        self.completed_at = utc_now()
        self.updated_at = self.completed_at
        return self.transition_to(JobExecutionStatus.SKIPPED)

    def mark_cancelled(self, reason: str | None = None) -> "JobExecution":
        if reason:
            self.error_message = reason[:2_000]
        self.completed_at = utc_now()
        self.updated_at = self.completed_at
        return self.transition_to(JobExecutionStatus.CANCELLED)

    # -- queries ---------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    def is_owned_by(self, user_id: EntityId) -> bool:
        return self.user_id == user_id

    def assert_owned_by(self, user_id: EntityId) -> None:
        if not self.is_owned_by(user_id):
            raise PermissionError("job execution belongs to another user")

    def describe(self) -> dict[str, Any]:
        """Audit-friendly summary. Carries no payload and no arguments."""
        return {
            "id": str(self.id),
            "scheduled_job_id": str(self.scheduled_job_id),
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "trigger_event_id": (
                str(self.trigger_event_id) if self.trigger_event_id else None
            ),
            "status": self.status.value,
            "scheduled_for": self.scheduled_for.isoformat(),
            "attempt": self.attempt,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
        }