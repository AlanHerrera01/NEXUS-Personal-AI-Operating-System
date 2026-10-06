import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base


class AgentRunModel(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_agent_id", "agent_id"),
        Index("ix_agent_runs_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    # The owner of the run. A run is created on behalf of someone, and "whose run
    # is this" has to be answerable without walking back to the agent -- an agent
    # can be shared, a run cannot.
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, default=None, index=True)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="CREATED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    agent = relationship("AgentModel", back_populates="runs")
    plans = relationship("ExecutionPlanModel", back_populates="agent_run", cascade="all, delete-orphan")
    actions = relationship("AgentActionModel", back_populates="agent_run", cascade="all, delete-orphan")
