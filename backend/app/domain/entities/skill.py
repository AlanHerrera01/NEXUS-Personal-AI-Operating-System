from dataclasses import dataclass

from app.domain.entities._common import require_text
from app.domain.value_objects.risk_level import RiskLevel


@dataclass
class Skill:
    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    enabled: bool = True

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.description, "description")
