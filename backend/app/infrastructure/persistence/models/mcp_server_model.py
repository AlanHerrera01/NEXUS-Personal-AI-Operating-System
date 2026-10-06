from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class MCPServerModel(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    transport_type: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    configuration: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    trust_level: Mapped[str] = mapped_column(String(50), nullable=False, default="default")
    owner_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DISCONNECTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False, onupdate="now()")
    last_connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
