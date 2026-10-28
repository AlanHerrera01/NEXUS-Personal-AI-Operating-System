from abc import ABC, abstractmethod

from app.domain.ports.tool import Tool
from app.domain.value_objects.entity_id import EntityId


class MCPToolProviderPort(ABC):
    """Discovers MCP-backed tools for one owner.

    The provider is deliberately separate from the static skill catalog: the
    tools it returns depend on servers that were registered at runtime and on
    whether those servers are reachable at the moment of the run.
    """

    @abstractmethod
    async def tools_for_owner(self, owner_id: EntityId) -> list[Tool]:
        raise NotImplementedError
