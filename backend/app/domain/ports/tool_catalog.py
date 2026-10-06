from abc import ABC, abstractmethod

from app.domain.ports.tool import ToolDefinition


class ToolCatalog(ABC):
    """Read-only view of the tools an agent may be offered for a request."""

    @abstractmethod
    def available_definitions(self, request: str) -> list[ToolDefinition]:
        raise NotImplementedError
