from typing import Any

from app.domain.entities.mcp_server import MCPServer
from app.domain.repositories.mcp_server_repository import MCPServerRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_server_status import MCPServerStatus


class MCPServerRegistry:
    """Registry for managing MCP servers."""
    
    def __init__(self, repository: MCPServerRepository) -> None:
        self.repository = repository
    
    def register(
        self,
        name: str,
        description: str,
        transport_type: str,
        endpoint: str,
        configuration: dict[str, Any] | None = None,
        owner_id: EntityId | None = None,
        trust_level: str = "default",
    ) -> MCPServer:
        """Register a new MCP server."""
        from app.domain.value_objects.mcp_transport_type import MCPTransportType
        
        server = MCPServer(
            name=name,
            description=description,
            transport_type=MCPTransportType(transport_type),
            endpoint=endpoint,
            configuration=configuration or {},
            owner_id=owner_id,
            trust_level=trust_level,
        )
        self.repository.save(server)
        return server
    
    def unregister(self, server_id: EntityId) -> None:
        """Unregister an MCP server."""
        self.repository.delete(server_id)
    
    def get_server(self, server_id: EntityId) -> MCPServer | None:
        """Get a server by ID."""
        return self.repository.get_by_id(server_id)
    
    def get_server_by_name(self, name: str) -> MCPServer | None:
        """Get a server by name."""
        return self.repository.get_by_name(name)
    
    def list_servers(self) -> list[MCPServer]:
        """List all servers."""
        return self.repository.list_all()
    
    def list_enabled_servers(self) -> list[MCPServer]:
        """List enabled servers."""
        return self.repository.list_enabled()
    
    def list_servers_for_owner(self, owner_id: EntityId) -> list[MCPServer]:
        """List the servers registered by one owner."""
        return self.repository.list_for_owner(owner_id)
    
    def save_server(self, server: MCPServer) -> MCPServer:
        """Persist a server whose fields were changed directly.

        The update route edits several fields at once (description, enabled and
        configuration) and the entity exposes the mutators for each; this is the
        single write that records the result.
        """
        self.repository.save(server)
        return server
    
    def enable_server(self, server_id: EntityId) -> MCPServer | None:
        """Enable a server."""
        server = self.repository.get_by_id(server_id)
        if server:
            server.enable()
            self.repository.save(server)
        return server
    
    def disable_server(self, server_id: EntityId) -> MCPServer | None:
        """Disable a server."""
        server = self.repository.get_by_id(server_id)
        if server:
            server.disable()
            self.repository.save(server)
        return server
    
    def update_server_status(self, server_id: EntityId, status: MCPServerStatus) -> None:
        """Update server status."""
        server = self.repository.get_by_id(server_id)
        if server:
            server.set_status(status)
            self.repository.save(server)
    
    def update_configuration(self, server_id: EntityId, configuration: dict[str, Any]) -> None:
        """Update server configuration."""
        server = self.repository.get_by_id(server_id)
        if server:
            server.update_configuration(configuration)
            self.repository.save(server)
