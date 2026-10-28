from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from app.application.mcp.mcp_server_registry import MCPServerRegistry
from app.application.mcp.mcp_tool_mapper import MCPToolMapper
from app.application.security.ssrf import SsrfBlocked, validate_resolution
from app.config.settings import Settings, get_settings
from app.domain.entities.mcp_server import MCPServer
from app.domain.ports.mcp_client import MCPClientPort
from app.domain.ports.mcp_tool_provider import MCPToolProviderPort
from app.domain.ports.tool import (
    RESERVED_ARGUMENT_NAMES,
    Tool,
    ToolContext,
    ToolDefinition,
    ToolResult,
)
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_server_status import MCPServerStatus
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.mcp.exceptions import MCPConnectionError, MCPExecutionError

logger = logging.getLogger("nexus.mcp.provider")

EndpointValidator = Callable[[str], Awaitable[Any]]

#: How many servers are contacted at once during one run. A chat request should
#: not fan out to an unbounded number of user-registered endpoints.
_DISCOVERY_CONCURRENCY = 4

#: Tool names are sent to the model and some providers cap them at 64 chars.
_MAX_TOOL_NAME = 64


class MCPToolProxy(Tool):
    """One discovered MCP tool, executed through the registered server."""

    def __init__(
        self,
        *,
        definition: ToolDefinition,
        adapter: MCPClientPort,
        server_id: EntityId,
        server_name: str,
        original_name: str,
        owner_id: EntityId,
        timeout_seconds: float,
        max_output_chars: int,
    ) -> None:
        self._definition = definition
        self.adapter = adapter
        self.server_id = server_id
        self.server_name = server_name
        self.original_name = original_name
        self.owner_id = owner_id
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        # The tool is only injected for its owner. Checking again here means a
        # registry leak or a reused orchestrator cannot call someone else's
        # server with a different user's identity.
        if context.user_id is None or context.user_id != self.owner_id:
            return self._failure(
                ToolErrorCode.TOOL_EXECUTION_FAILED,
                "MCP tool is not owned by the acting user",
            )

        payload = arguments if isinstance(arguments, dict) else {}
        forbidden = sorted(RESERVED_ARGUMENT_NAMES.intersection(payload))
        if forbidden:
            return self._failure(
                ToolErrorCode.FORBIDDEN_ARGUMENTS,
                "arguments not allowed: " + ", ".join(forbidden),
            )

        try:
            raw = await asyncio.wait_for(
                self.adapter.call_tool(self.server_id, self.original_name, payload),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return self._failure(
                ToolErrorCode.TOOL_TIMEOUT,
                f"MCP tool {self.original_name} timed out",
            )
        except (MCPConnectionError, MCPExecutionError) as error:
            return self._failure(ToolErrorCode.TOOL_EXECUTION_FAILED, str(error))
        except Exception as error:  # noqa: BLE001 - a tool result, not a crash
            logger.exception("MCP tool %s raised", self.original_name)
            return self._failure(ToolErrorCode.TOOL_EXECUTION_FAILED, str(error))

        data = self._bounded_payload(raw)
        if raw.get("is_error"):
            return ToolResult(
                success=False,
                tool_name=self._definition.name,
                data=data,
                error_code=str(ToolErrorCode.TOOL_EXECUTION_FAILED),
                error_message=self._error_text(raw) or "MCP tool returned an error",
                metadata=self._metadata(),
            )
        return ToolResult(
            success=True,
            tool_name=self._definition.name,
            data=data,
            metadata=self._metadata(),
        )

    def _failure(self, code: ToolErrorCode, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool_name=self._definition.name,
            error_code=str(code),
            error_message=message,
            metadata=self._metadata(),
        )

    def _metadata(self) -> dict[str, Any]:
        return {
            "source": "mcp",
            "server_id": str(self.server_id),
            "server_name": self.server_name,
            "mcp_tool": self.original_name,
        }

    def _bounded_payload(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "content": raw.get("content"),
            "structured_content": raw.get("structured_content"),
            "is_error": bool(raw.get("is_error")),
        }
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(payload)
        if len(text) <= self.max_output_chars:
            return payload
        return {
            "truncated": True,
            "original_chars": len(text),
            "content": text[: self.max_output_chars],
        }

    @staticmethod
    def _error_text(raw: dict[str, Any]) -> str | None:
        content = raw.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
        return None


class MCPToolProvider(MCPToolProviderPort):
    """Discovers enabled, owner-scoped MCP tools and returns executable proxies."""

    def __init__(
        self,
        registry: MCPServerRegistry,
        adapter: MCPClientPort,
        settings: Settings | None = None,
        mapper: MCPToolMapper | None = None,
        *,
        endpoint_validator: EndpointValidator | None = None,
    ) -> None:
        self.registry = registry
        self.adapter = adapter
        self.settings = settings or get_settings()
        self.mapper = mapper or MCPToolMapper(
            max_description_chars=self.settings.mcp_max_description_chars,
            max_schema_chars=self.settings.mcp_max_schema_chars,
        )
        self.endpoint_validator = endpoint_validator or validate_resolution

    async def tools_for_owner(self, owner_id: EntityId) -> list[Tool]:
        servers = [
            server
            for server in self.registry.list_servers_for_owner(owner_id)
            if server.enabled and server.transport_type is not MCPTransportType.IN_PROCESS
        ]
        if not servers:
            return []

        semaphore = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

        async def discover_one(server: MCPServer):
            async with semaphore:
                try:
                    return server, await self._discover(server)
                except Exception as error:  # noqa: BLE001 - one bad server is not the run
                    logger.warning(
                        "MCP discovery failed for server %s: %s", server.name, error
                    )
                    return server, []

        discovered = await asyncio.gather(
            *(discover_one(server) for server in servers)
        )

        used_names: set[str] = set()
        tools: list[Tool] = []
        for server, raw_tools in discovered:
            for raw_tool in raw_tools:
                if len(tools) >= self.settings.mcp_max_total_tools:
                    return tools
                original_name = str(raw_tool.get("name") or "").strip()
                if not original_name:
                    continue
                namespaced = self._unique_tool_name(server, original_name, used_names)
                definition = self.mapper.map_to_tool_definition(
                    raw_tool,
                    server.name,
                    str(server.id),
                    namespaced_name=namespaced,
                )
                tools.append(
                    MCPToolProxy(
                        definition=definition,
                        adapter=self.adapter,
                        server_id=server.id,
                        server_name=server.name,
                        original_name=original_name,
                        owner_id=owner_id,
                        timeout_seconds=self.settings.mcp_tool_timeout_seconds,
                        max_output_chars=self.settings.mcp_max_output_chars,
                    )
                )
        return tools

    async def test_connection(self, server: MCPServer) -> dict[str, Any]:
        """Open a real connection and list the server's tools.

        This is what the panel's "test connection" button calls. A failed
        connection is a result, not an exception: the caller needs the reason
        to show it next to the row and the row stays registered.
        """
        try:
            raw_tools = await self._discover(server)
        except Exception as error:  # noqa: BLE001 - report, do not 500
            return {
                "ok": False,
                "server_id": str(server.id),
                "server_name": server.name,
                "status": server.status.value,
                "tools": [],
                "tool_count": 0,
                "error": str(error) or error.__class__.__name__,
                "connected_at": (
                    server.last_connected_at.isoformat()
                    if server.last_connected_at
                    else None
                ),
            }
        finally:
            try:
                await self.adapter.disconnect(server.id)
            except Exception:  # noqa: BLE001 - cleanup is best-effort
                logger.exception("failed to close MCP connection for %s", server.name)

        tools = [
            {
                "name": str(raw.get("name") or ""),
                "title": raw.get("title"),
                "description": raw.get("description"),
                "input_schema": raw.get("input_schema") or {},
            }
            for raw in raw_tools[: self.settings.mcp_max_tools_per_server]
        ]
        return {
            "ok": True,
            "server_id": str(server.id),
            "server_name": server.name,
            "status": server.status.value,
            "tools": tools,
            "tool_count": len(tools),
            "error": None,
            "connected_at": (
                server.last_connected_at.isoformat()
                if server.last_connected_at
                else None
            ),
        }

    async def _discover(self, server: MCPServer) -> list[dict[str, Any]]:
        try:
            self._ensure_transport_allowed(server)
            await self._ensure_endpoint_allowed(server)
            await self.adapter.connect(server)
            raw_tools = await asyncio.wait_for(
                self.adapter.list_tools(server.id),
                timeout=self.settings.mcp_connect_timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            self._mark(server, MCPServerStatus.ERROR)
            await self._disconnect(server)
            raise MCPConnectionError(
                f"MCP server {server.name} did not answer within "
                f"{self.settings.mcp_connect_timeout_seconds:g}s"
            ) from error
        except Exception:
            self._mark(server, MCPServerStatus.ERROR)
            await self._disconnect(server)
            raise

        self._mark(server, MCPServerStatus.READY)
        return raw_tools[: self.settings.mcp_max_tools_per_server]

    def _ensure_transport_allowed(self, server: MCPServer) -> None:
        if server.transport_type is MCPTransportType.STDIO:
            if not self.settings.mcp_allow_stdio:
                raise MCPConnectionError(
                    "stdio MCP servers are disabled; set MCP_ALLOW_STDIO=true and "
                    "add the exact executable to MCP_ALLOWED_STDIO_COMMANDS, or use "
                    "an HTTP/SSE endpoint"
                )
            command = server.configuration.get("command")
            executable = (
                command[0]
                if isinstance(command, list) and command and isinstance(command[0], str)
                else ""
            )
            allowed = {
                item.strip()
                for item in self.settings.mcp_allowed_stdio_commands.split(",")
                if item.strip()
            }
            if not executable or executable not in allowed:
                raise MCPConnectionError(
                    f"stdio executable {executable or '(missing)'} is not in "
                    "MCP_ALLOWED_STDIO_COMMANDS"
                )
            return

        if server.transport_type is MCPTransportType.IN_PROCESS:
            raise MCPConnectionError("in-process MCP servers cannot be registered")

        if not server.endpoint.lower().startswith(("http://", "https://")):
            raise MCPConnectionError("remote MCP servers need an http(s) endpoint")

    async def _ensure_endpoint_allowed(self, server: MCPServer) -> None:
        if server.transport_type is MCPTransportType.STDIO:
            return

        parts = urlsplit(server.endpoint)
        host = (parts.hostname or "").lower()
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as error:
            raise MCPConnectionError("MCP endpoint has an invalid port") from error

        if self._private_host_allowed(host, port):
            # Explicitly trusted local endpoint. The operator named it, so the
            # guard that exists to stop model-registered URLs from reaching the
            # private network does not apply.
            return

        try:
            await asyncio.wait_for(
                self.endpoint_validator(server.endpoint),
                timeout=self.settings.mcp_connect_timeout_seconds,
            )
        except SsrfBlocked as error:
            raise MCPConnectionError(f"MCP endpoint blocked: {error.reason}") from error
        except asyncio.TimeoutError as error:
            raise MCPConnectionError(
                "MCP endpoint could not be validated in time"
            ) from error
        except MCPConnectionError:
            raise
        except Exception as error:  # noqa: BLE001 - normalize to a connection error
            raise MCPConnectionError(
                f"MCP endpoint could not be validated: {error}"
            ) from error

    def _private_host_allowed(self, host: str, port: int) -> bool:
        entries = {
            item.strip().lower()
            for item in self.settings.mcp_allowed_private_hosts.split(",")
            if item.strip()
        }
        return host in entries or f"{host}:{port}" in entries

    def _unique_tool_name(
        self, server: MCPServer, original_name: str, used: set[str]
    ) -> str:
        server_slug = _slug(server.name, 24) or "server"
        tool_slug = _slug(original_name, 30) or "tool"
        candidate = f"mcp.{server_slug}.{tool_slug}"
        if len(candidate) > _MAX_TOOL_NAME:
            digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:8]
            candidate = candidate[: _MAX_TOOL_NAME - 9] + "." + digest
        if candidate in used:
            digest = hashlib.sha1(
                f"{server.id}:{original_name}".encode("utf-8")
            ).hexdigest()[:8]
            candidate = candidate[: _MAX_TOOL_NAME - 9] + "." + digest
        used.add(candidate)
        return candidate

    def _mark(self, server: MCPServer, status: MCPServerStatus) -> None:
        try:
            server.set_status(status)
            self.registry.save_server(server)
        except Exception:  # noqa: BLE001 - status is telemetry, not the run
            logger.exception("failed to record MCP status for %s", server.name)

    async def _disconnect(self, server: MCPServer) -> None:
        try:
            await self.adapter.disconnect(server.id)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            logger.exception("failed to close MCP connection for %s", server.name)


def _slug(value: str, limit: int) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", (value or "").lower()).strip("_")
    return slug[:limit].strip("_")
