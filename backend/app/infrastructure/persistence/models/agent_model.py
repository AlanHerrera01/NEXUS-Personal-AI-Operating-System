import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.database import Base


class AgentModel(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable only because the column postdates the rows: the migration backfills
    # existing agents to the local operator. Nothing may create an agent without
    # an owner -- see CreateAgent and migration 0008.
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, default=None, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    runs = relationship("AgentRunModel", back_populates="agent", cascade="all, delete-orphan")
    tasks = relationship("TaskModel", back_populates="agent")
