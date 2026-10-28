"""Discovery, mapping and execution of MCP-backed tools.

The critical properties here are authorization, not plumbing: a discovered tool
is always MEDIUM risk and always asks for confirmation, execution is bound to
the owner who registered the server, and one unreachable server cannot fail a
run.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.application.mcp.mcp_tool_provider import MCPToolProvider
from app.application.security.ssrf import SsrfBlocked
from app.config.settings import Settings
from app.domain.entities.mcp_server import MCPServer
from app.domain.ports.mcp_client import MCPClientPort
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_server_status import MCPServerStatus
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode


class FakeRegistry:
    def __init__(self, servers: list[MCPServer]) -> None:
        self.servers = servers
        self.owners: list[EntityId] = []
        self.saved_statuses: list[MCPServerStatus] = []

    def list_servers_for_owner(self, owner_id: EntityId) -> list[MCPServer]:
        self.owners.append(owner_id)
        return [server for server in self.servers if server.owner_id == owner_id]

    def save_server(self, server: MCPServer) -> MCPServer:
        self.saved_statuses.append(server.status)
        return server


class FakeAdapter(MCPClientPort):
    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        *,
        result: dict[str, Any] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.tools = tools or []
        self.result = result or {
            "content": [{"type": "text", "text": "ok"}],
            "structured_content": None,
            "is_error": False,
        }
        self.delay = delay
        self.connected: list[EntityId] = []
        self.disconnected: list[EntityId] = []
        self.calls: list[tuple[EntityId, str, dict[str, Any]]] = []

    async def connect(self, server: MCPServer) -> None:
        self.connected.append(server.id)

    async def disconnect(self, server_id: EntityId) -> None:
        self.disconnected.append(server_id)

    async def list_tools(self, server_id: EntityId) -> list[dict[str, Any]]:
        return self.tools

    async def call_tool(
        self, server_id: EntityId, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((server_id, tool_name, arguments))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result

    async def get_server_info(self, server_id: EntityId) -> dict[str, Any] | None:
        return None


def _server(
    *,
    owner: EntityId,
    name: str = "GitHub MCP",
    transport: MCPTransportType = MCPTransportType.STREAMABLE_HTTP,
    endpoint: str = "https://example.invalid/mcp",
    configuration: dict[str, Any] | None = None,
) -> MCPServer:
    return MCPServer(
        name=name,
        description="MCP test server.",
        transport_type=transport,
        endpoint=endpoint,
        configuration=configuration or {},
        owner_id=owner,
    )


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "mcp_connect_timeout_seconds": 1.0,
        "mcp_tool_timeout_seconds": 1.0,
        "mcp_max_tools_per_server": 40,
        "mcp_max_total_tools": 80,
        "mcp_max_description_chars": 600,
        "mcp_max_schema_chars": 8000,
        "mcp_max_output_chars": 20000,
        "mcp_allow_stdio": False,
        "mcp_allowed_stdio_commands": "",
        "mcp_allowed_private_hosts": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def _noop_validator(_url: str) -> None:
    return None


def _tool(
    *,
    name: str = "get_me",
    description: str = "Return the authenticated user.",
    schema: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": name.replace("_", " ").title(),
        "description": description,
        "input_schema": schema or {"type": "object", "properties": {}},
        "annotations": annotations,
    }


def _context(owner: EntityId, *, user: EntityId | None = None) -> ToolContext:
    return ToolContext(
        agent_id=EntityId.new(),
        agent_run_id=EntityId.new(),
        user_id=user if user is not None else owner,
    )


async def test_discovery_namespaces_and_marks_every_tool_for_confirmation() -> None:
    owner = EntityId.new()
    server = _server(owner=owner)
    adapter = FakeAdapter([_tool(annotations={"readOnlyHint": True})])
    provider = MCPToolProvider(
        FakeRegistry([server]), adapter, _settings(), endpoint_validator=_noop_validator
    )

    tools = await provider.tools_for_owner(owner)

    assert len(tools) == 1
    definition = tools[0].definition()
    assert definition.name == "mcp.github_mcp.get_me"
    assert definition.skill_name == "mcp"
    assert definition.risk_level is RiskLevel.MEDIUM
    assert definition.requires_confirmation is True
    # A server's own read-only hint is displayed but does not lower the risk.
    assert definition.read_only is True
    assert definition.side_effect is False
    assert definition.metadata["original_name"] == "get_me"
    assert definition.metadata["server_id"] == str(server.id)
    assert definition.description.startswith("[MCP:GitHub MCP]")
    assert adapter.connected == [server.id]


async def test_tools_without_annotations_are_not_assumed_read_only() -> None:
    owner = EntityId.new()
    adapter = FakeAdapter([_tool(name="delete_repository")])
    provider = MCPToolProvider(
        FakeRegistry([_server(owner=owner)]),
        adapter,
        _settings(),
        endpoint_validator=_noop_validator,
    )

    [tool] = await provider.tools_for_owner(owner)

    assert tool.definition().read_only is False
    assert tool.definition().side_effect is True
    assert tool.definition().requires_confirmation is True


async def test_execution_uses_original_tool_name_and_is_owner_bound() -> None:
    owner = EntityId.new()
    other = EntityId.new()
    server = _server(owner=owner)
    adapter = FakeAdapter([_tool()])
    provider = MCPToolProvider(
        FakeRegistry([server]), adapter, _settings(), endpoint_validator=_noop_validator
    )
    [tool] = await provider.tools_for_owner(owner)

    result = await tool.execute({"state": "open"}, _context(owner))
    assert result.success is True
    assert adapter.calls == [(server.id, "get_me", {"state": "open"})]

    denied = await tool.execute({"state": "open"}, _context(owner, user=other))
    assert denied.success is False
    assert len(adapter.calls) == 1


async def test_reserved_arguments_never_reach_the_server() -> None:
    owner = EntityId.new()
    adapter = FakeAdapter([_tool()])
    provider = MCPToolProvider(
        FakeRegistry([_server(owner=owner)]),
        adapter,
        _settings(),
        endpoint_validator=_noop_validator,
    )
    [tool] = await provider.tools_for_owner(owner)

    result = await tool.execute({"user_id": str(owner)}, _context(owner))

    assert result.success is False
    assert result.error_code == str(ToolErrorCode.FORBIDDEN_ARGUMENTS)
    assert adapter.calls == []


async def test_a_slow_tool_times_out_with_a_tool_result() -> None:
    owner = EntityId.new()
    adapter = FakeAdapter([_tool()], delay=0.05)
    provider = MCPToolProvider(
        FakeRegistry([_server(owner=owner)]),
        adapter,
        _settings(mcp_tool_timeout_seconds=0.001),
        endpoint_validator=_noop_validator,
    )
    [tool] = await provider.tools_for_owner(owner)

    result = await tool.execute({}, _context(owner))

    assert result.success is False
    assert result.error_code == str(ToolErrorCode.TOOL_TIMEOUT)


async def test_an_mcp_error_result_becomes_a_failed_tool_result() -> None:
    owner = EntityId.new()
    adapter = FakeAdapter(
        [_tool()],
        result={
            "content": [{"type": "text", "text": "rate limited"}],
            "structured_content": None,
            "is_error": True,
        },
    )
    provider = MCPToolProvider(
        FakeRegistry([_server(owner=owner)]),
        adapter,
        _settings(),
        endpoint_validator=_noop_validator,
    )
    [tool] = await provider.tools_for_owner(owner)

    result = await tool.execute({}, _context(owner))

    assert result.success is False
    assert result.error_message == "rate limited"


async def test_test_connection_lists_tools_and_disconnects() -> None:
    owner = EntityId.new()
    server = _server(owner=owner)
    adapter = FakeAdapter([_tool(), _tool(name="list_repos")])
    provider = MCPToolProvider(
        FakeRegistry([server]), adapter, _settings(), endpoint_validator=_noop_validator
    )

    result = await provider.test_connection(server)

    assert result["ok"] is True
    assert result["tool_count"] == 2
    assert [tool["name"] for tool in result["tools"]] == ["get_me", "list_repos"]
    assert server.status is MCPServerStatus.READY
    assert adapter.disconnected == [server.id]


async def test_test_connection_reports_ssrf_blocks_without_connecting() -> None:
    owner = EntityId.new()
    server = _server(owner=owner)
    adapter = FakeAdapter([_tool()])

    async def blocked(_url: str) -> None:
        raise SsrfBlocked("resolves to a private address")

    provider = MCPToolProvider(
        FakeRegistry([server]), adapter, _settings(), endpoint_validator=blocked
    )

    result = await provider.test_connection(server)

    assert result["ok"] is False
    assert "blocked" in result["error"]
    assert adapter.connected == []
    assert server.status is MCPServerStatus.ERROR


async def test_stdio_is_refused_unless_enabled_and_allowlisted() -> None:
    owner = EntityId.new()
    server = _server(
        owner=owner,
        name="filesystem",
        transport=MCPTransportType.STDIO,
        endpoint="npx",
        configuration={"command": ["npx", "-y", "server-filesystem"]},
    )
    adapter = FakeAdapter([_tool()])
    provider = MCPToolProvider(
        FakeRegistry([server]), adapter, _settings(), endpoint_validator=_noop_validator
    )

    result = await provider.test_connection(server)

    assert result["ok"] is False
    assert "stdio" in result["error"].lower()
    assert adapter.connected == []


async def test_private_hosts_are_only_allowed_when_named() -> None:
    owner = EntityId.new()
    server = _server(
        owner=owner,
        endpoint="http://host.docker.internal:8082/mcp",
    )
    adapter = FakeAdapter([_tool()])
    calls: list[str] = []

    async def validator(url: str) -> None:
        calls.append(url)

    provider = MCPToolProvider(
        FakeRegistry([server]),
        adapter,
        _settings(mcp_allowed_private_hosts="host.docker.internal:8082"),
        endpoint_validator=validator,
    )

    result = await provider.test_connection(server)

    assert result["ok"] is True
    assert calls == []


async def test_one_unreachable_server_does_not_remove_the_working_one() -> None:
    owner = EntityId.new()
    broken = _server(owner=owner, name="Broken", endpoint="https://broken.invalid/mcp")
    working = _server(owner=owner, name="Working", endpoint="https://working.invalid/mcp")

    class SelectiveAdapter(FakeAdapter):
        async def list_tools(self, server_id: EntityId) -> list[dict[str, Any]]:
            if server_id == broken.id:
                raise RuntimeError("unreachable")
            return [_tool()]

    adapter = SelectiveAdapter()
    provider = MCPToolProvider(
        FakeRegistry([broken, working]),
        adapter,
        _settings(),
        endpoint_validator=_noop_validator,
    )

    tools = await provider.tools_for_owner(owner)

    assert [tool.definition().name for tool in tools] == ["mcp.working.get_me"]


async def test_total_tool_cap_is_enforced() -> None:
    owner = EntityId.new()
    adapter = FakeAdapter([_tool(name="one"), _tool(name="two")])
    provider = MCPToolProvider(
        FakeRegistry([_server(owner=owner)]),
        adapter,
        _settings(mcp_max_total_tools=1),
        endpoint_validator=_noop_validator,
    )

    tools = await provider.tools_for_owner(owner)

    assert len(tools) == 1
