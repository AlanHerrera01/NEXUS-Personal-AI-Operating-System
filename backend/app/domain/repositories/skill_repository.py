from abc import ABC, abstractmethod

from app.domain.entities.skill import Skill


class SkillRepository(ABC):
    @abstractmethod
    def save(self, skill: Skill) -> Skill:
        raise NotImplementedError

    @abstractmethod
    def get_by_name(self, name: str) -> Skill | None:
        raise NotImplementedError
