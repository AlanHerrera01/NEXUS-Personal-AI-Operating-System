from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class RuntimeSettingsModel(Base):
    """The single row of runtime overrides.

    Every tunable column is nullable, and ``NULL`` means "no override here" --
    the environment value applies. That is why the columns are not ``NOT NULL``
    with defaults: a default would silently bake a value in and there would be no
    way to tell an override from an inherited default.

    A deployment has one effective configuration, so this table is expected to
    hold exactly one row keyed by a constant id. It is a table rather than a file
    so the write is transactional and survives a restart the same way every other
    durable fact in NEXUS does.
    """

    __tablename__ = "runtime_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    notifications_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
