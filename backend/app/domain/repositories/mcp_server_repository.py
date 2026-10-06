from abc import ABC, abstractmethod

from app.domain.entities.mcp_server import MCPServer
from app.domain.value_objects.entity_id import EntityId


class MCPServerRepository(ABC):
    """Repository for MCP Server persistence."""
    
    @abstractmethod
    def save(self, server: MCPServer) -> None:
        """Save an MCP server."""
        raise NotImplementedError
    
    @abstractmethod
    def get_by_id(self, server_id: EntityId) -> MCPServer | None:
        """Get an MCP server by ID."""
        raise NotImplementedError
    
    @abstractmethod
    def get_by_name(self, name: str) -> MCPServer | None:
        """Get an MCP server by name."""
        raise NotImplementedError
    
    @abstractmethod
    def list_all(self) -> list[MCPServer]:
        """List all MCP servers."""
        raise NotImplementedError
    
    @abstractmethod
    def list_enabled(self) -> list[MCPServer]:
        """List enabled MCP servers."""
        raise NotImplementedError
    
    @abstractmethod
    def delete(self, server_id: EntityId) -> None:
        """Delete an MCP server."""
        raise NotImplementedError
