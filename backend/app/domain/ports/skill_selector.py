from abc import ABC, abstractmethod

from app.domain.ports.skill import SkillDefinition


class SkillSelector(ABC):
    """Chooses which skills are relevant for a user request."""

    @abstractmethod
    def select(self, request: str, available: list[SkillDefinition]) -> list[SkillDefinition]:
        raise NotImplementedError
