from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class SkillModel(Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
