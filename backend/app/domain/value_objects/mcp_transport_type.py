from enum import StrEnum


class MCPTransportType(StrEnum):
    """Types of MCP transport protocols."""
    STREAMABLE_HTTP = "streamable_http"
    STDIO = "stdio"
    SSE = "sse"
    IN_PROCESS = "in_process"
