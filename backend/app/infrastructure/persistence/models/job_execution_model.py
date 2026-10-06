import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class JobExecutionModel(Base):
    """One attempt to fire a scheduled job.

    ``idempotency_key`` is the unique constraint that makes dispatch effectively
    exactly-once across processes. It is 300 characters to comfortably hold
    ``schedule:<uuid>:<iso8601>`` and ``event:<uuid>:<uuid>`` with room to spare.
    """

    __tablename__ = "job_executions"
    __table_args__ = (
        Index("ix_job_executions_job_id", "scheduled_job_id"),
        # Used by the approval reconciliation hook to find the execution parked
        # on a human decision for a given run.
        Index("ix_job_executions_agent_run_id", "agent_run_id"),
        Index("ix_job_executions_user_id", "user_id"),
        # Used by the recovery sweep, which only ever asks "give me RUNNING".
        Index("ix_job_executions_status", "status"),
        Index("ix_job_executions_user_status", "user_id", "status"),
        # Named explicitly, and identically to the migration. An inline
        # ``unique=True`` would leave Postgres to invent the name, and the next
        # autogenerate would then report a spurious difference.
        UniqueConstraint(
            "idempotency_key", name="uq_job_executions_idempotency_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scheduled_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trigger_events.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result_summary: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )