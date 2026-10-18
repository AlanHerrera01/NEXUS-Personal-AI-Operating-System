"""Provider for the MCP server registry.

The registry is a thin wrapper over the repository; this module is the single
seam where the request-scoped session becomes one, so the route never touches
the session itself.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.mcp.mcp_server_registry import MCPServerRegistry
from app.infrastructure.persistence.repositories.mcp_server_repository import (
    SqlMCPServerRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def mcp_registry_dependency(
    session: Session = Depends(session_dependency),
) -> MCPServerRegistry:
    return MCPServerRegistry(SqlMCPServerRepository(session))
