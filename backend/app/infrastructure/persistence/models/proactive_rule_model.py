import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base


class ProactiveRuleModel(Base):
    """A user-authored condition under which NEXUS may speak first.

    ``condition`` and ``action`` are stored as native JSON rather than as text
    because they are read and written whole and never queried into. Both are
    bounded by the entity to a few kilobytes and to closed vocabularies.
    """

    __tablename__ = "proactive_rules"
    __table_args__ = (
        Index("ix_proactive_rules_user_id", "user_id"),
        # Every evaluation pass asks for "this user's enabled rules".
        Index("ix_proactive_rules_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    action: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3_600)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    agent = relationship("AgentModel")