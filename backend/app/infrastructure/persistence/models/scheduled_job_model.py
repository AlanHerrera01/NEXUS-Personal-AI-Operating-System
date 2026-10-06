import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base


class ScheduledJobModel(Base):
    """A user's standing instruction to create an agent run on a schedule.

    ``user_id`` deliberately has no foreign key. There is no users table in this
    schema yet (see the authentication gap noted in the Phase 12 docs), and a
    fabricated FK to a table that does not exist would be worse than an honest
    unconstrained column. It is indexed because every user-scoped read filters
    on it.
    """

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        Index("ix_scheduled_jobs_user_id", "user_id"),
        # The dispatcher's hot path is "active clock jobs that are due", which is
        # exactly this predicate. A composite index keeps that query off a seq
        # scan as the table grows.
        Index("ix_scheduled_jobs_due", "status", "next_run_at"),
        Index("ix_scheduled_jobs_agent_id", "agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(4_000), nullable=False, default="")
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    cron_expression: Mapped[str | None] = mapped_column(String(200), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    agent = relationship("AgentModel")