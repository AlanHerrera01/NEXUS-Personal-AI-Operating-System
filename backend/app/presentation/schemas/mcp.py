"""Request/response models for MCP server registration and connection tests.

Registering a server writes configuration. Opening a connection is a separate
act: ``POST /mcp-servers/{id}/test`` asks the adapter to list the server's tools,
and an agent run discovers the same tools before planning. Every discovered tool
still goes through the Trust Engine, and all of them require confirmation.

The shape of ``configuration`` is transport-specific and mirrors exactly what
:class:`~app.infrastructure.mcp.adapters.mcp_client_adapter.MCPClientAdapter`
reads, so a stored row is one the adapter can act on rather than free-form
text:

* ``stdio``            -> ``{"command": [exe, *args], "env": {"K": "V"}}``
* ``sse``/``streamable_http`` -> ``{"headers": {"K": "V"}}``
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#: Transports an operator may register from the panel. ``in_process`` is left
#: out deliberately: it names an embedding inside this very process rather than
#: an address, so it is not something a form can legitimately configure.
RegistrableTransport = Literal["stdio", "sse", "streamable_http"]

#: Registrable transports, for the response and for validation.
REGISTRABLE_TRANSPORTS: tuple[str, ...] = ("stdio", "sse", "streamable_http")

#: What the adapter can actually talk to today (see the branches in
#: ``MCPClientAdapter._get_client``). Keep this in sync with the registrable
#: transports: a row the form accepts should not be reported as unsupported.
ADAPTER_TRANSPORTS: tuple[str, ...] = ("stdio", "sse", "streamable_http")

#: Caps just this field; the security middleware already caps the whole body.
#: A registration form is not a blob store.
MAX_CONFIGURATION_BYTES = 8192


class MCPServerView(BaseModel):
    id: str
    name: str
    description: str
    transport_type: str
    endpoint: str
    configuration: dict[str, Any]
    enabled: bool
    #: Assigned by the engine, reported here, never taken from the request.
    trust_level: str
    status: str
    owner_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    #: False for a registered transport the current adapter cannot reach yet.
    transport_supported: bool
    created_at: str
    updated_at: str
    last_connected_at: str | None = None


class MCPServersResponse(BaseModel):
    items: list[MCPServerView]
    transports: list[str]
    #: How many servers the caller has registered.
    registered: int


class MCPServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    transport_type: RegistrableTransport
    #: STDIO: the executable to run (first token of the command line).
    #: sse/streamable_http: the URL to reach.
    endpoint: str = Field(min_length=1, max_length=2000)
    configuration: dict[str, Any] = Field(default_factory=dict)


class MCPServerUpdateRequest(BaseModel):
    """A partial update: omit a field to leave it alone."""

    description: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None
    configuration: dict[str, Any] | None = None


class MCPToolView(BaseModel):
    """One tool reported by a server during a connection test."""

    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPConnectionTestResponse(BaseModel):
    """Result of an actual connection attempt.

    A failed connection is returned as ``ok=false`` rather than an HTTP error:
    the row is still registered and the panel needs the reason next to it.
    """

    ok: bool
    server_id: str
    server_name: str
    status: str
    tools: list[MCPToolView] = Field(default_factory=list)
    tool_count: int = 0
    error: str | None = None
    connected_at: str | None = None
