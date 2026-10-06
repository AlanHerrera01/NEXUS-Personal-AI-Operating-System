import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base


class AgentActionModel(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (Index("ix_agent_actions_agent_run_id", "agent_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action_name: Mapped[str] = mapped_column(String(200), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPOSED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=True)
    permission_decision: Mapped[str] = mapped_column(String(16), nullable=True)
    policy_result: Mapped[str] = mapped_column(String(200), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    agent_run = relationship("AgentRunModel", back_populates="actions")
