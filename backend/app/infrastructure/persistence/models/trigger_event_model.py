import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class TriggerEventModel(Base):
    """An external event, stored before any job acts on it.

    Persisting the event rather than acting on it and logging afterwards is what
    makes a retried webhook delivery safe: the unique ``idempotency_key`` is
    checked at insert time, so the second delivery is recognised before any
    dispatch is attempted rather than after.
    """

    __tablename__ = "trigger_events"
    __table_args__ = (
        Index("ix_trigger_events_user_id", "user_id"),
        # The rate limiter counts a user's recent events on every ingest.
        Index("ix_trigger_events_user_received", "user_id", "received_at"),
        Index("ix_trigger_events_event_type", "event_type"),
        UniqueConstraint("idempotency_key", name="uq_trigger_events_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )