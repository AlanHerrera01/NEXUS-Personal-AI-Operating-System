from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_server_status import MCPServerStatus
from app.domain.value_objects.mcp_transport_type import MCPTransportType


@dataclass
class MCPServer:
    """Represents a configured MCP Server that NEXUS can connect to."""

    # The required fields come first. ``id`` used to sit above them with a
    # default_factory, which makes Python refuse to import this module at all
    # ("non-default argument 'name' follows default argument 'id'") -- so every
    # module that transitively imports MCPServer was unimportable, including the
    # ORM model that produces the SAWarning about the reserved name ``metadata``.
    # Dataclass field order is load-bearing; defaults must come last.
    name: str
    description: str
    transport_type: MCPTransportType
    endpoint: str
    configuration: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    trust_level: str = "default"  # default, trusted, untrusted
    owner_id: EntityId | None = None
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_connected_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: EntityId = field(default_factory=EntityId.new)
    
    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.description, "description")
        require_text(self.endpoint, "endpoint")
    
    def enable(self) -> None:
        """Enable the server."""
        self.enabled = True
        self.updated_at = utc_now()
    
    def disable(self) -> None:
        """Disable the server."""
        self.enabled = False
        self.status = MCPServerStatus.DISCONNECTED
        self.updated_at = utc_now()
    
    def set_status(self, status: MCPServerStatus) -> None:
        """Update the server status."""
        self.status = status
        self.updated_at = utc_now()
        if status == MCPServerStatus.READY:
            self.last_connected_at = utc_now()
    
    def is_available(self) -> bool:
        """Check if the server is available for use."""
        return self.enabled and self.status == MCPServerStatus.READY
    
    def update_configuration(self, configuration: dict[str, Any]) -> None:
        """Update the server configuration."""
        self.configuration = configuration
        self.updated_at = utc_now()
