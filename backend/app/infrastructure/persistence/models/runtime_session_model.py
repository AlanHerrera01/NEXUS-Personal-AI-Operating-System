import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class RuntimeSessionModel(Base):
    """One sandboxed runtime, owned by exactly one AgentRun.

    ``agent_run_id`` carries the isolation boundary, so it is indexed and
    cascades with the run. The serialized ``policy`` column is what the runtime
    was actually created with; it is stored so a resumed run can be checked
    against the policy it was granted rather than the policy it would get now.
    """

    __tablename__ = "runtime_sessions"
    __table_args__ = (
        Index("ix_runtime_sessions_agent_run_id", "agent_run_id"),
        Index("ix_runtime_sessions_user_id", "user_id"),
        Index("ix_runtime_sessions_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="LOCAL")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    sandbox_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    workspace_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    policy: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)