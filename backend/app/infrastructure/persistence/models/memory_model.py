import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class MemoryModel(Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_agent_id", "agent_id"),
        Index("ix_memories_agent_type", "agent_id", "memory_type"),
        # Every read path filters on the owner, so the owner leads the index that
        # serves them. Without it, "list this user's memories" degrades to a scan
        # of every row in the table -- which is both slow and, on a shared
        # deployment, the query where a missing owner filter would be visible.
        Index("ix_memories_user_created", "user_id", "created_at"),
        Index("ix_memories_user_agent", "user_id", "agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    # Nullable only because rows predate ownership. The firewall refuses to write a
    # memory without an owner, so in practice every row has one; the migration
    # backfills existing rows to the local operator and keeps them nullable so a
    # partially-owned legacy table still reads.
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, default=None)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    persistence: Mapped[str] = mapped_column(String(32), nullable=False, default="SAVE")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="SYSTEM")
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
