class MCPConnectionError(Exception):
    """Raised when MCP connection fails."""
    pass


class MCPExecutionError(Exception):
    """Raised when MCP tool execution fails."""
    pass


class MCPDiscoveryError(Exception):
    """Raised when MCP tool discovery fails."""
    pass


class MCPValidationError(Exception):
    """Raised when MCP input/output validation fails."""
    pass
