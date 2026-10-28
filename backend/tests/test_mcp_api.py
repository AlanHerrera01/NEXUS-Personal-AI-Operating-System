"""MCP server registration and connection testing over HTTP.

The value under test is not only "does it store a row" but the two things that
make the route safe to expose: it never lets the caller decide who owns a server
or how far it is trusted, and the test action is owner-scoped and executes
nothing.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.application.mcp.mcp_server_registry import MCPServerRegistry
from app.domain.entities.mcp_server import MCPServer
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.main import app
from app.presentation.dependencies.identity import LOCAL_USER_ID
from app.presentation.dependencies.mcp import (
    mcp_registry_dependency,
    mcp_tool_provider_dependency,
)
from app.presentation.schemas.mcp import ADAPTER_TRANSPORTS, REGISTRABLE_TRANSPORTS


class FakeMCPServerRepository:
    """In-memory stand-in for the ``mcp_servers`` table."""

    def __init__(self) -> None:
        self.servers: dict[str, MCPServer] = {}
        self.deleted: list[str] = []

    def save(self, server: MCPServer) -> None:
        self.servers[str(server.id)] = server

    def get_by_id(self, server_id: EntityId) -> MCPServer | None:
        return self.servers.get(str(server_id))

    def get_by_name(self, name: str) -> MCPServer | None:
        return next((s for s in self.servers.values() if s.name == name), None)

    def list_all(self) -> list[MCPServer]:
        return list(self.servers.values())

    def list_enabled(self) -> list[MCPServer]:
        return [s for s in self.servers.values() if s.enabled]

    def list_for_owner(self, owner_id: EntityId) -> list[MCPServer]:
        return [s for s in self.servers.values() if s.owner_id == owner_id]

    def delete(self, server_id: EntityId) -> None:
        self.deleted.append(str(server_id))
        self.servers.pop(str(server_id), None)


def _override(repository: FakeMCPServerRepository) -> None:
    app.dependency_overrides[mcp_registry_dependency] = lambda: MCPServerRegistry(
        repository
    )


class FakeProvider:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.tested: list[str] = []

    async def test_connection(self, server: MCPServer) -> dict[str, Any]:
        self.tested.append(str(server.id))
        return {
            **self.result,
            "server_id": str(server.id),
            "server_name": server.name,
        }


def _override_provider(provider: FakeProvider) -> None:
    app.dependency_overrides[mcp_tool_provider_dependency] = lambda: provider


def teardown_function() -> None:
    # Remove only the keys this module installs; ``clear()`` would wipe the
    # module-level overrides other test files register at import time.
    app.dependency_overrides.pop(mcp_registry_dependency, None)
    app.dependency_overrides.pop(mcp_tool_provider_dependency, None)


STDIO = {
    "name": "filesystem",
    "description": "Read-only access to a workspace directory.",
    "transport_type": "stdio",
    "endpoint": "npx",
    "configuration": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
    },
}


def _own(repository: FakeMCPServerRepository, **overrides) -> MCPServer:
    """A server owned by the local user, as the API would have stored it."""
    payload = {**STDIO, **overrides}
    server = MCPServer(
        name=payload["name"],
        description=payload["description"],
        transport_type=MCPTransportType(payload["transport_type"]),
        endpoint=payload["endpoint"],
        configuration=payload["configuration"],
        owner_id=EntityId(LOCAL_USER_ID),
    )
    repository.save(server)
    return server


def test_list_is_empty_and_advertises_only_registrable_transports() -> None:
    _override(FakeMCPServerRepository())

    body = TestClient(app).get("/api/v1/mcp-servers").json()

    assert body["items"] == []
    assert body["registered"] == 0
    # ``in_process`` is not a form's business, so it is not offered.
    assert body["transports"] == ["stdio", "sse", "streamable_http"]


def test_every_registrable_transport_has_an_adapter_branch() -> None:
    # The form and the registry must not drift: offering a transport the
    # adapter cannot build turns a registration into a delayed failure.
    assert set(REGISTRABLE_TRANSPORTS) <= set(ADAPTER_TRANSPORTS)


def test_register_stores_configuration_and_ignores_client_supplied_trust() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)

    response = TestClient(app).post(
        "/api/v1/mcp-servers",
        json={**STDIO, "trust_level": "trusted", "owner_id": "someone-else"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "filesystem"
    assert body["configuration"]["command"][0] == "npx"
    assert body["enabled"] is True
    assert body["status"] == "DISCONNECTED"
    assert body["transport_supported"] is True
    # Neither of these is readable from the request body.
    assert body["trust_level"] == "default"
    assert body["owner_id"] == str(LOCAL_USER_ID)


def test_register_rejects_stdio_without_a_command() -> None:
    _override(FakeMCPServerRepository())

    response = TestClient(app).post(
        "/api/v1/mcp-servers", json={**STDIO, "configuration": {}}
    )

    assert response.status_code == 422
    assert "command" in response.json()["detail"]


def test_register_rejects_an_oversized_configuration() -> None:
    _override(FakeMCPServerRepository())

    response = TestClient(app).post(
        "/api/v1/mcp-servers",
        json={**STDIO, "configuration": {"command": ["npx"], "env": {"BIG": "x" * 9000}}},
    )

    assert response.status_code == 422
    assert "bytes" in response.json()["detail"]


def test_register_rejects_a_duplicate_name() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    client = TestClient(app)

    assert client.post("/api/v1/mcp-servers", json=STDIO).status_code == 201
    second = client.post("/api/v1/mcp-servers", json=STDIO)

    assert second.status_code == 409
    assert repository.servers.__len__() == 1


def test_register_requires_an_http_endpoint_for_remote_transports() -> None:
    _override(FakeMCPServerRepository())

    response = TestClient(app).post(
        "/api/v1/mcp-servers",
        json={
            "name": "remote",
            "description": "Remote MCP endpoint.",
            "transport_type": "streamable_http",
            "endpoint": "ftp://example.invalid/mcp",
            "configuration": {},
        },
    )

    assert response.status_code == 422


def test_sse_registers_and_is_reported_as_supported() -> None:
    _override(FakeMCPServerRepository())

    response = TestClient(app).post(
        "/api/v1/mcp-servers",
        json={
            "name": "sse-server",
            "description": "Legacy SSE transport with an adapter branch.",
            "transport_type": "sse",
            "endpoint": "https://example.invalid/sse",
            "configuration": {},
        },
    )

    assert response.status_code == 201
    # The adapter builds an SSE client for this row, so the API does not warn
    # that the transport is stored but unreachable.
    assert response.json()["transport_supported"] is True


def test_list_only_returns_the_callers_own_servers() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    _own(repository)
    repository.save(
        MCPServer(
            name="someone-elses",
            description="Not this caller's server.",
            transport_type=MCPTransportType.STDIO,
            endpoint="npx",
            configuration={"command": ["npx"]},
            owner_id=EntityId.new(),
        )
    )

    body = TestClient(app).get("/api/v1/mcp-servers").json()

    assert [item["name"] for item in body["items"]] == ["filesystem"]
    assert body["registered"] == 1


def test_patch_toggles_enabled_and_checks_configuration_against_the_transport() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    server = _own(repository)
    client = TestClient(app)

    disabled = client.patch(f"/api/v1/mcp-servers/{server.id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    # The transport is immutable, so a new configuration must still fit it.
    bad = client.patch(
        f"/api/v1/mcp-servers/{server.id}", json={"configuration": {"command": []}}
    )
    assert bad.status_code == 422

    good = client.patch(
        f"/api/v1/mcp-servers/{server.id}",
        json={"configuration": {"command": ["uvx", "mcp-server-git"]}},
    )
    assert good.status_code == 200
    assert good.json()["configuration"]["command"] == ["uvx", "mcp-server-git"]


def test_delete_is_owner_scoped_and_404s_for_an_unknown_id() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    foreign = MCPServer(
        name="foreign",
        description="Someone else's server.",
        transport_type=MCPTransportType.STDIO,
        endpoint="npx",
        configuration={"command": ["npx"]},
        owner_id=EntityId.new(),
    )
    repository.save(foreign)
    client = TestClient(app)

    assert client.delete(f"/api/v1/mcp-servers/{foreign.id}").status_code == 404
    assert client.delete(f"/api/v1/mcp-servers/{EntityId.new().value}").status_code == 404
    assert repository.deleted == []


def test_delete_removes_the_callers_own_server() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    server = _own(repository)
    client = TestClient(app)

    response = client.delete(f"/api/v1/mcp-servers/{server.id}")

    assert response.status_code == 204
    assert repository.deleted == [str(server.id)]
    assert client.get("/api/v1/mcp-servers").json()["registered"] == 0


def test_test_connection_returns_discovered_tools_for_an_owned_server() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    server = _own(repository)
    provider = FakeProvider(
        {
            "ok": True,
            "status": "READY",
            "tools": [
                {
                    "name": "get_me",
                    "title": "Get me",
                    "description": "Return the authenticated user.",
                    "input_schema": {"type": "object"},
                }
            ],
            "tool_count": 1,
            "error": None,
            "connected_at": "2026-10-20T12:00:00",
        }
    )
    _override_provider(provider)

    response = TestClient(app).post(f"/api/v1/mcp-servers/{server.id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["server_name"] == "filesystem"
    assert body["tool_count"] == 1
    assert body["tools"][0]["name"] == "get_me"
    assert provider.tested == [str(server.id)]


def test_test_connection_reports_a_failed_connection_without_an_http_error() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    server = _own(repository)
    provider = FakeProvider(
        {
            "ok": False,
            "status": "ERROR",
            "tools": [],
            "tool_count": 0,
            "error": "MCP header references unset environment variable GITHUB_PERSONAL_ACCESS_TOKEN",
            "connected_at": None,
        }
    )
    _override_provider(provider)

    response = TestClient(app).post(f"/api/v1/mcp-servers/{server.id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in body["error"]


def test_test_connection_is_owner_scoped() -> None:
    repository = FakeMCPServerRepository()
    _override(repository)
    foreign = MCPServer(
        name="foreign",
        description="Someone else's server.",
        transport_type=MCPTransportType.STDIO,
        endpoint="npx",
        configuration={"command": ["npx"]},
        owner_id=EntityId.new(),
    )
    repository.save(foreign)
    provider = FakeProvider(
        {
            "ok": True,
            "status": "READY",
            "tools": [],
            "tool_count": 0,
            "error": None,
            "connected_at": None,
        }
    )
    _override_provider(provider)

    response = TestClient(app).post(f"/api/v1/mcp-servers/{foreign.id}/test")

    assert response.status_code == 404
    assert provider.tested == []
