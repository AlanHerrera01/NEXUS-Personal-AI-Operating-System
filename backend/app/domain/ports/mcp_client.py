from abc import ABC, abstractmethod
from typing import Any

from app.domain.entities.mcp_server import MCPServer
from app.domain.value_objects.entity_id import EntityId


class MCPClientPort(ABC):
    """Port for MCP client operations. Domain depends on this abstraction."""
    
    @abstractmethod
    async def connect(self, server: MCPServer) -> None:
        """Connect to an MCP server."""
        raise NotImplementedError
    
    @abstractmethod
    async def disconnect(self, server_id: EntityId) -> None:
        """Disconnect from an MCP server."""
        raise NotImplementedError
    
    @abstractmethod
    async def list_tools(self, server_id: EntityId) -> list[dict[str, Any]]:
        """List available tools from an MCP server."""
        raise NotImplementedError
    
    @abstractmethod
    async def call_tool(
        self,
        server_id: EntityId,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool on an MCP server."""
        raise NotImplementedError
    
    @abstractmethod
    async def get_server_info(self, server_id: EntityId) -> dict[str, Any] | None:
        """Get server information."""
        raise NotImplementedError
