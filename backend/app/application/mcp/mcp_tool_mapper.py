from typing import Any

from app.domain.ports.tool import ToolDefinition
from app.domain.value_objects.risk_level import RiskLevel


class MCPToolMapper:
    """Maps MCP tool definitions to NEXUS ToolDefinition."""
    
    def __init__(self, default_risk_level: RiskLevel = RiskLevel.MEDIUM) -> None:
        self.default_risk_level = default_risk_level
    
    def map_to_tool_definition(
        self,
        mcp_tool: dict[str, Any],
        server_name: str,
        server_id: str,
    ) -> ToolDefinition:
        """Convert an MCP tool definition to NEXUS ToolDefinition."""
        tool_name = mcp_tool.get("name", "")
        title = mcp_tool.get("title") or tool_name
        description = mcp_tool.get("description", "")
        input_schema = mcp_tool.get("input_schema", {})
        
        # Generate a namespaced tool name
        namespaced_name = f"mcp.{server_name}.{tool_name}"
        
        # Determine risk level based on tool name
        risk_level = self._classify_risk(tool_name)
        
        # Determine other security properties
        read_only = self._is_read_only(tool_name)
        side_effect = not read_only
        requires_confirmation = risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
        
        return ToolDefinition(
            name=namespaced_name,
            description=description,
            input_schema=input_schema,
            skill_name="mcp",
            risk_level=risk_level,
            read_only=read_only,
            side_effect=side_effect,
            requires_confirmation=requires_confirmation,
            category="mcp",
            version="1.0.0",
            tags=("mcp", server_name),
            metadata={
                "original_name": tool_name,
                "title": title,
                "server_id": server_id,
                "server_name": server_name,
                "source": "mcp",
            },
        )
    
    def _classify_risk(self, tool_name: str) -> RiskLevel:
        """Classify the risk level of a tool based on its name."""
        tool_name_lower = tool_name.lower()
        
        # High-risk patterns
        high_risk_keywords = {
            "delete", "drop", "destroy", "remove", "truncate", "purge",
            "credential", "password", "secret", "token", "key", "auth",
            "shell", "exec", "execute", "run", "system", "admin",
            "overwrite", "reset", "format", "wipe",
        }
        
        for keyword in high_risk_keywords:
            if keyword in tool_name_lower:
                return RiskLevel.HIGH
        
        # Medium-risk patterns
        medium_risk_keywords = {
            "create", "update", "modify", "change", "edit", "write",
            "upload", "download", "transfer", "move", "copy",
            "calendar", "schedule", "appointment", "event",
        }
        
        for keyword in medium_risk_keywords:
            if keyword in tool_name_lower:
                return RiskLevel.MEDIUM
        
        # Default to low for read-like operations
        if any(keyword in tool_name_lower for keyword in ["get", "list", "search", "find", "read", "fetch"]):
            return RiskLevel.LOW
        
        # Default to medium for unknown
        return self.default_risk_level
    
    def _is_read_only(self, tool_name: str) -> bool:
        """Determine if a tool is read-only based on its name."""
        tool_name_lower = tool_name.lower()
        
        read_only_keywords = {
            "get", "list", "search", "find", "read", "fetch", "show",
            "describe", "info", "status", "check", "verify",
        }
        
        return any(keyword in tool_name_lower for keyword in read_only_keywords)
