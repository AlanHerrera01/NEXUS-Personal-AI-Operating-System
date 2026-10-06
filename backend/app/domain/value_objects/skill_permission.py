from dataclasses import dataclass, field

from app.domain.entities._common import require_text


@dataclass(frozen=True)
class SkillPermission:
    """Extension point for per-skill grants such as ``CalendarSkill -> READ``."""

    skill_name: str
    actions: frozenset[str] = field(default_factory=frozenset)
    granted: bool = True

    def __post_init__(self) -> None:
        require_text(self.skill_name, "skill_name")

    def allows(self, action: str) -> bool:
        if not self.granted:
            return False
        if not self.actions:
            return True
        return action in self.actions or "*" in self.actions
