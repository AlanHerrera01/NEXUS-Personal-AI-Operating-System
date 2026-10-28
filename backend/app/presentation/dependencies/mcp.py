"""Provider for the MCP server registry.

The registry is a thin wrapper over the repository; this module is the single
seam where the request-scoped session becomes one, so the route never touches
the session itself.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.mcp.mcp_server_registry import MCPServerRegistry
from app.application.mcp.mcp_tool_provider import MCPToolProvider
from app.config.settings import Settings, get_settings
from app.infrastructure.mcp.adapters.mcp_client_adapter import MCPClientAdapter
from app.infrastructure.persistence.repositories.mcp_server_repository import (
    SqlMCPServerRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def mcp_registry_dependency(
    session: Session = Depends(session_dependency),
) -> MCPServerRegistry:
    return MCPServerRegistry(SqlMCPServerRepository(session))


def build_mcp_tool_provider(
    session: Session, settings: Settings | None = None
) -> MCPToolProvider:
    """Wire discovery against one session.

    The adapter is created per provider, and the provider per orchestrator, so
    the active-client table is scoped to the work that discovered it rather than
    shared across users.
    """
    resolved = settings or get_settings()
    return MCPToolProvider(
        MCPServerRegistry(SqlMCPServerRepository(session)),
        MCPClientAdapter(
            connection_timeout=resolved.mcp_connect_timeout_seconds,
            tool_timeout=resolved.mcp_tool_timeout_seconds,
        ),
        resolved,
    )


def mcp_tool_provider_dependency(
    session: Session = Depends(session_dependency),
) -> MCPToolProvider:
    return build_mcp_tool_provider(session)
