"""The adapter branch table must match the transports the form offers.

These tests do not open a connection. They assert that each registrable
transport builds an SDK client, because a stored row with no branch would only
fail later, inside an agent run, with a much less useful error.
"""

from __future__ import annotations

import pytest

# The MCP SDK is an optional runtime dependency for local development: the
# registration API does not import it, so the rest of the suite can run without
# it. Skip the adapter tests rather than failing collection.
pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from app.domain.entities.mcp_server import MCPServer
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.infrastructure.mcp.adapters.mcp_client_adapter import MCPClientAdapter, _headers
from app.infrastructure.mcp.exceptions import MCPConnectionError


def _server(
    transport: MCPTransportType,
    configuration: dict | None = None,
    *,
    endpoint: str = "https://example.invalid/mcp",
) -> MCPServer:
    return MCPServer(
        name=f"{transport.value}-server",
        description="Adapter transport test.",
        transport_type=transport,
        endpoint=endpoint,
        configuration=configuration or {},
    )


@pytest.fixture
def adapter() -> MCPClientAdapter:
    return MCPClientAdapter(tool_timeout=12.5)


def test_stdio_splits_argv_and_passes_env(adapter: MCPClientAdapter) -> None:
    client = adapter._get_client(
        _server(
            MCPTransportType.STDIO,
            {
                "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
                "env": {"LOG_LEVEL": "debug"},
            },
            endpoint="npx",
        )
    )

    assert isinstance(client, Client)
    assert isinstance(client.server, StdioServerParameters)
    assert client.server.command == "npx"
    assert client.server.args == ["-y", "@modelcontextprotocol/server-filesystem"]
    assert client.server.env == {"LOG_LEVEL": "debug"}
    assert client.read_timeout_seconds == 12.5


def test_sse_builds_a_transport_with_headers(adapter: MCPClientAdapter) -> None:
    client = adapter._get_client(
        _server(
            MCPTransportType.SSE,
            {"headers": {"Authorization": "Bearer test-token"}},
            endpoint="https://example.invalid/sse",
        )
    )

    assert isinstance(client, Client)
    # A transport is an async context manager; a string would be a URL the SDK
    # resolves on its own and would silently drop the stored headers.
    assert hasattr(client.server, "__aenter__")


def test_streamable_http_builds_a_transport_with_headers(
    adapter: MCPClientAdapter,
) -> None:
    client = adapter._get_client(
        _server(
            MCPTransportType.STREAMABLE_HTTP,
            {"headers": {"Authorization": "Bearer test-token"}},
            endpoint="https://example.invalid/mcp",
        )
    )

    assert isinstance(client, Client)
    assert hasattr(client.server, "__aenter__")


def test_stdio_without_a_command_is_refused(adapter: MCPClientAdapter) -> None:
    with pytest.raises(MCPConnectionError, match="configuration.command"):
        adapter._get_client(_server(MCPTransportType.STDIO, {}, endpoint="npx"))


def test_invalid_headers_are_refused(adapter: MCPClientAdapter) -> None:
    with pytest.raises(MCPConnectionError, match="configuration.headers"):
        adapter._get_client(
            _server(MCPTransportType.SSE, {"headers": {"Authorization": 1}})
        )


def test_header_env_reference_is_resolved_at_connect_time(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TEST_TOKEN", "resolved-value")
    headers = _headers(
        _server(
            MCPTransportType.STREAMABLE_HTTP,
            {"headers": {"Authorization": "Bearer ${MCP_TEST_TOKEN}"}},
        )
    )

    assert headers == {"Authorization": "Bearer resolved-value"}


def test_missing_header_env_reference_is_refused(monkeypatch) -> None:
    monkeypatch.delenv("MCP_TEST_TOKEN", raising=False)
    with pytest.raises(MCPConnectionError, match="MCP_TEST_TOKEN"):
        _headers(
            _server(
                MCPTransportType.STREAMABLE_HTTP,
                {"headers": {"Authorization": "Bearer ${MCP_TEST_TOKEN}"}},
            )
        )
