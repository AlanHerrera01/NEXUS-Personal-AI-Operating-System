from abc import ABC, abstractmethod
from collections.abc import Collection

from app.domain.ports.tool import Tool, ToolDefinition


class ToolRegistry(ABC):
    """Single source of truth for tool registration and discovery."""

    @abstractmethod
    def register(self, tool: Tool) -> Tool:
        raise NotImplementedError

    @abstractmethod
    def unregister(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get(self, name: str) -> Tool | None:
        raise NotImplementedError

    @abstractmethod
    def definitions(self) -> list[ToolDefinition]:
        raise NotImplementedError

    @abstractmethod
    def list_available(self, skill_names: Collection[str] | None = None) -> list[ToolDefinition]:
        raise NotImplementedError

    def definitions_for_skill(self, skill_name: str) -> list[ToolDefinition]:
        return self.list_available([skill_name])
