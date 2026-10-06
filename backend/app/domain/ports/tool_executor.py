from abc import ABC, abstractmethod

from app.domain.ports.tool import ToolContext, ToolObservation


class ToolExecutor(ABC):
    @abstractmethod
    async def execute(self, tool_name: str, arguments: dict, context: ToolContext) -> ToolObservation:
        raise NotImplementedError
