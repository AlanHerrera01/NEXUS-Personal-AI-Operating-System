import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base


class ExecutionPlanModel(Base):
    __tablename__ = "execution_plans"
    __table_args__ = (Index("ix_execution_plans_agent_run_id", "agent_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent_run = relationship("AgentRunModel", back_populates="plans")
    steps = relationship("PlanStepModel", back_populates="plan", cascade="all, delete-orphan", order_by="PlanStepModel.step_order")
