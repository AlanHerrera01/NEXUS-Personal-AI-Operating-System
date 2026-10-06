from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.domain.ports.tool import Tool
from app.domain.value_objects.skill_permission import SkillPermission


@dataclass(frozen=True)
class SkillDefinition:
    """Describes a capability. Purely descriptive: no execution logic."""

    name: str
    description: str
    version: str = "1.0.0"
    enabled: bool = True
    category: str | None = None
    keywords: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("skill name must not be empty")

    def matches(self, request: str) -> bool:
        haystack = request.lower()
        terms = (self.name, *self.keywords)
        return any(term and term.lower() in haystack for term in terms)

    def __hash__(self) -> int:
        return hash((self.name, self.version))


class Skill(ABC):
    """A capability that groups the tools implementing it."""

    @abstractmethod
    def definition(self) -> SkillDefinition:
        raise NotImplementedError

    @abstractmethod
    def tools(self) -> list[Tool]:
        raise NotImplementedError

    def permissions(self) -> tuple[SkillPermission, ...]:
        """Extension point for per-skill grants; empty means "no extra rules"."""
        return ()


class SkillCatalog(ABC):
    """Read-only view over the registered skills."""

    @abstractmethod
    def definitions(self) -> list[SkillDefinition]:
        raise NotImplementedError

    @abstractmethod
    def get(self, name: str) -> Skill | None:
        raise NotImplementedError

    @abstractmethod
    def is_enabled(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def tools_for(self, skill_name: str) -> list[Tool]:
        raise NotImplementedError

    @abstractmethod
    def permissions(self) -> list[SkillPermission]:
        raise NotImplementedError
