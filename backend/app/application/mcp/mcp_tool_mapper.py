from __future__ import annotations

import json
from typing import Any

from app.domain.ports.tool import ToolDefinition
from app.domain.value_objects.risk_level import RiskLevel

#: A schema larger than this is replaced by a permissive object. The model can
#: still call the tool; the MCP server remains the authority on its arguments.
#: Shipping an unbounded schema is a cheap way to flood the prompt.
DEFAULT_MAX_SCHEMA_CHARS = 8_000

#: Descriptions are model-visible text supplied by an external server.
DEFAULT_MAX_DESCRIPTION_CHARS = 600


class MCPToolMapper:
    """Maps MCP tools to NEXUS definitions without trusting their names.

    The previous version inferred ``read_only`` from substrings such as "get"
    and auto-allowed anything that looked read-like. A tool named
    ``get_and_delete_everything`` passed that test. Tool names and descriptions
    come from the MCP server, which is external input, so they are not an
    authorization signal.

    Everything discovered here is therefore MEDIUM risk and requires
    confirmation. The Trust Engine still makes the decision; this only refuses
    to let the server's own label lower it. A server-provided ``readOnlyHint``
    is displayed for the operator but does not remove the confirmation.
    """

    def __init__(
        self,
        default_risk_level: RiskLevel = RiskLevel.MEDIUM,
        *,
        max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
        max_schema_chars: int = DEFAULT_MAX_SCHEMA_CHARS,
    ) -> None:
        self.default_risk_level = default_risk_level
        self.max_description_chars = max_description_chars
        self.max_schema_chars = max_schema_chars

    def map_to_tool_definition(
        self,
        mcp_tool: dict[str, Any],
        server_name: str,
        server_id: str,
        *,
        namespaced_name: str | None = None,
    ) -> ToolDefinition:
        """Convert one MCP tool definition to a NEXUS ``ToolDefinition``."""
        tool_name = str(mcp_tool.get("name") or "").strip()
        title = mcp_tool.get("title") or tool_name
        description = self._description(mcp_tool.get("description"), server_name)
        input_schema = self._schema(mcp_tool.get("input_schema"))
        annotations = mcp_tool.get("annotations")
        read_only_hint = (
            isinstance(annotations, dict)
            and bool(annotations.get("readOnlyHint"))
        )

        return ToolDefinition(
            name=namespaced_name or f"mcp.{server_name}.{tool_name}",
            description=description,
            input_schema=input_schema,
            skill_name="mcp",
            risk_level=self.default_risk_level,
            # Display only. It never removes the confirmation below.
            read_only=read_only_hint,
            side_effect=not read_only_hint,
            requires_confirmation=True,
            category="mcp",
            version="1.0.0",
            tags=("mcp", server_name),
            metadata={
                "original_name": tool_name,
                "title": title,
                "server_id": server_id,
                "server_name": server_name,
                "source": "mcp",
                "annotations": annotations if isinstance(annotations, dict) else {},
            },
        )

    def _description(self, value: Any, server_name: str) -> str:
        text = str(value or "").strip()
        text = f"[MCP:{server_name}] {text}" if text else f"[MCP:{server_name}]"
        if len(text) > self.max_description_chars:
            text = text[: self.max_description_chars] + "…"
        return text

    def _schema(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"type": "object", "additionalProperties": True}
        try:
            encoded = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return {"type": "object", "additionalProperties": True}
        if len(encoded) > self.max_schema_chars:
            return {
                "type": "object",
                "additionalProperties": True,
                "description": "schema omitted because it exceeded the configured limit",
            }
        return value
