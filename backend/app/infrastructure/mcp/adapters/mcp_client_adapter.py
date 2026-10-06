import anyio
from typing import Any

from mcp import Client
from mcp.client.transports import StdioServerParameters

from app.domain.entities.mcp_server import MCPServer
from app.domain.ports.mcp_client import MCPClientPort
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_server_status import MCPServerStatus
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.infrastructure.mcp.exceptions import MCPConnectionError, MCPExecutionError


class MCPClientAdapter(MCPClientPort):
    """Adapter for MCP SDK client. Implements the domain port."""
    
    def __init__(
        self,
        connection_timeout: float = 30.0,
        tool_timeout: float = 60.0,
    ) -> None:
        self.connection_timeout = connection_timeout
        self.tool_timeout = tool_timeout
        self._active_clients: dict[EntityId, Any] = {}  # Store client contexts
    
    async def connect(self, server: MCPServer) -> None:
        """Connect to an MCP server."""
        if server.id in self._active_clients:
            return  # Already connected
        
        try:
            # Store the server config for later use
            self._active_clients[server.id] = {
                "server": server,
                "connected": True,
            }
        except Exception as e:
            raise MCPConnectionError(f"Failed to connect to MCP server {server.name}: {e}")
    
    async def disconnect(self, server_id: EntityId) -> None:
        """Disconnect from an MCP server."""
        if server_id in self._active_clients:
            del self._active_clients[server_id]
    
    async def list_tools(self, server_id: EntityId) -> list[dict[str, Any]]:
        """List available tools from an MCP server."""
        connection = self._active_clients.get(server_id)
        if not connection:
            raise MCPConnectionError(f"No active connection for server {server_id}")
        
        server = connection["server"]
        
        try:
            async with self._get_client(server) as client:
                result = await client.list_tools()
                return [
                    {
                        "name": tool.name,
                        "title": tool.title,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                    for tool in result.tools
                ]
        except Exception as e:
            raise MCPExecutionError(f"Failed to list tools: {e}")
    
    async def call_tool(
        self,
        server_id: EntityId,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool on an MCP server."""
        connection = self._active_clients.get(server_id)
        if not connection:
            raise MCPConnectionError(f"No active connection for server {server_id}")
        
        server = connection["server"]
        
        try:
            async with self._get_client(server) as client:
                result = await client.call_tool(tool_name, arguments)
                return {
                    "content": result.content,
                    "structured_content": result.structured_content,
                    "is_error": result.is_error,
                }
        except Exception as e:
            raise MCPExecutionError(f"Failed to call tool {tool_name}: {e}")
    
    async def get_server_info(self, server_id: EntityId) -> dict[str, Any] | None:
        """Get server information."""
        connection = self._active_clients.get(server_id)
        if not connection:
            return None
        
        server = connection["server"]
        
        try:
            async with self._get_client(server) as client:
                return {
                    "name": client.server_info.name if client.server_info else None,
                    "version": client.server_info.version if client.server_info else None,
                    "protocol_version": client.protocol_version,
                    "instructions": client.instructions,
                    "capabilities": {
                        "tools": client.server_capabilities.tools is not None,
                        "resources": client.server_capabilities.resources is not None,
                        "prompts": client.server_capabilities.prompts is not None,
                    },
                }
        except Exception:
            return None
    
    async def _get_client(self, server: MCPServer):
        """Get an MCP client for the server."""
        if server.transport_type == MCPTransportType.STREAMABLE_HTTP:
            return Client(server.endpoint)
        elif server.transport_type == MCPTransportType.STDIO:
            command = server.configuration.get("command", [])
            env = server.configuration.get("env", {})
            
            params = StdioServerParameters(
                command=command,
                env=env,
            )
            
            return Client(params)
        else:
            raise MCPConnectionError(f"Unsupported transport type: {server.transport_type}")
