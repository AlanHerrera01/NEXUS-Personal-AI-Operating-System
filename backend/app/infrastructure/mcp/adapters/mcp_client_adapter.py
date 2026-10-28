from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.config.settings import get_settings
from app.domain.entities.mcp_server import MCPServer
from app.domain.ports.mcp_client import MCPClientPort
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.infrastructure.mcp.exceptions import MCPConnectionError, MCPExecutionError

#: Header values may reference a secret without storing it in the database:
#: ``Authorization=Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}``. Only simple
#: environment-variable names are accepted; the resolved value never leaves
#: this module.
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_header_value(value: str) -> str:
    """Resolve ``${NAME}`` references from the environment or settings.

    Registration stores the reference, not the secret. Resolution happens on
    every connection, so rotating a token in ``backend/.env`` takes effect on
    the next run without editing the server row.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = os.environ.get(name)
        if resolved is None:
            settings = get_settings()
            resolved = getattr(settings, name.lower(), None)
        if resolved is None or not isinstance(resolved, str) or not resolved:
            raise MCPConnectionError(
                f"MCP header references unset environment variable {name}"
            )
        return resolved

    return _ENV_REFERENCE.sub(replace, value)


def _headers(server: MCPServer) -> dict[str, str] | None:
    headers = server.configuration.get("headers")
    if headers is None:
        return None
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        raise MCPConnectionError(
            f"MCP server {server.name} has invalid configuration.headers"
        )
    return {key: _resolve_header_value(value) for key, value in headers.items()} or None


def _jsonable(value: Any) -> Any:
    """Convert SDK result objects into something the tool result can carry."""
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@asynccontextmanager
async def _streamable_http_transport(
    endpoint: str, headers: dict[str, str] | None
) -> AsyncIterator[Any]:
    """Streamable HTTP with the operator's headers.

    ``Client(url)`` builds the SDK's default transport, which has no way to
    carry the headers stored by the registration form. Supplying the client
    keeps that transport while letting authentication headers through.
    """
    client = create_mcp_http_client(headers=headers)
    async with client:
        async with streamable_http_client(endpoint, http_client=client) as streams:
            yield streams


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
        self._active_clients.pop(server_id, None)

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
                        "input_schema": _jsonable(tool.input_schema),
                        "annotations": _jsonable(
                            getattr(tool, "annotations", None)
                        ),
                    }
                    for tool in result.tools
                ]
        except MCPConnectionError:
            raise
        except Exception as e:
            raise MCPExecutionError(f"Failed to list tools: {e}") from e

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
                    "content": _jsonable(result.content),
                    "structured_content": _jsonable(result.structured_content),
                    "is_error": result.is_error,
                }
        except MCPConnectionError:
            raise
        except Exception as e:
            raise MCPExecutionError(f"Failed to call tool {tool_name}: {e}") from e

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

    def _get_client(self, server: MCPServer) -> Client:
        """Build an SDK client for the registered transport."""
        if server.transport_type == MCPTransportType.STREAMABLE_HTTP:
            return Client(
                _streamable_http_transport(server.endpoint, _headers(server)),
                read_timeout_seconds=self.tool_timeout,
            )

        if server.transport_type == MCPTransportType.SSE:
            # ``sse_client`` already owns its HTTP client and accepts headers.
            return Client(
                sse_client(server.endpoint, headers=_headers(server)),
                read_timeout_seconds=self.tool_timeout,
            )

        if server.transport_type == MCPTransportType.STDIO:
            command = server.configuration.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(part, str) and part for part in command)
            ):
                raise MCPConnectionError(
                    f"MCP server {server.name} has no valid configuration.command"
                )
            env = server.configuration.get("env")
            if env is not None and (
                not isinstance(env, dict)
                or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in env.items()
                )
            ):
                raise MCPConnectionError(
                    f"MCP server {server.name} has invalid configuration.env"
                )
            params = StdioServerParameters(
                command=command[0],
                args=command[1:],
                env=env or None,
            )
            return Client(params, read_timeout_seconds=self.tool_timeout)

        raise MCPConnectionError(
            f"Unsupported transport type: {server.transport_type}"
        )
