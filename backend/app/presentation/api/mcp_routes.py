"""MCP server registration.

The panel can record which MCP servers exist, where they live and how to reach
them. It cannot make NEXUS connect to them: this route only ever writes
configuration. That separation is what makes exposing it defensible -- an
endpoint that connected on demand would be a remote code execution primitive
wearing a settings dialog's clothes.

The honest gap, stated rather than implied: nothing in the tool pipeline
consumes this registry yet. ``MCPClientAdapter`` and ``MCPToolMapper`` exist,
but the orchestrator does not load registered servers, so a row here changes no
agent behaviour today.

What is enforced here:

* a caller only sees, changes or deletes its own servers, and an unowned id
  answers 404 rather than 403 so the route is not an existence oracle;
* ``trust_level`` is never read from the request. A form that could label a
  server "trusted" would let the caller grant itself the trust the engine is
  supposed to decide;
* the transport-specific shape is checked against what the adapter actually
  reads, so a stored row is one the adapter can act on.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.application.mcp.mcp_server_registry import MCPServerRegistry
from app.domain.entities.mcp_server import MCPServer
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.presentation.dependencies.identity import current_user_id
from app.presentation.dependencies.mcp import mcp_registry_dependency
from app.presentation.schemas.mcp import (
    ADAPTER_TRANSPORTS,
    MAX_CONFIGURATION_BYTES,
    REGISTRABLE_TRANSPORTS,
    MCPServerCreateRequest,
    MCPServerUpdateRequest,
    MCPServerView,
    MCPServersResponse,
)

router = APIRouter(prefix="/api/v1/mcp-servers", tags=["mcp"])


def _to_view(server: MCPServer) -> MCPServerView:
    transport = server.transport_type.value
    return MCPServerView(
        id=str(server.id),
        name=server.name,
        description=server.description,
        transport_type=transport,
        endpoint=server.endpoint,
        configuration=server.configuration,
        enabled=server.enabled,
        trust_level=server.trust_level,
        status=server.status.value,
        owner_id=str(server.owner_id) if server.owner_id else None,
        metadata=server.metadata,
        transport_supported=transport in ADAPTER_TRANSPORTS,
        created_at=server.created_at.isoformat(),
        updated_at=server.updated_at.isoformat(),
        last_connected_at=(
            server.last_connected_at.isoformat() if server.last_connected_at else None
        ),
    )


def _validate_transport(transport: str, endpoint: str, configuration: dict) -> None:
    """Check the fields the adapter will read, not merely that JSON arrived."""
    encoded = json.dumps(configuration, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_CONFIGURATION_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"configuration exceeds {MAX_CONFIGURATION_BYTES} bytes",
        )

    if transport == MCPTransportType.STDIO.value:
        command = configuration.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="stdio servers need configuration.command as a non-empty list of strings",
            )
    else:
        if not endpoint.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="remote servers need an http(s) endpoint",
            )
        headers = configuration.get("headers", {})
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="configuration.headers must map strings to strings",
            )

    env = configuration.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="configuration.env must map strings to strings",
        )


def _owned(registry: MCPServerRegistry, server_id: UUID, owner_id: EntityId) -> MCPServer:
    server = registry.get_server(EntityId(server_id))
    # 404 rather than 403: a caller that does not own the row should not be able
    # to tell "not yours" apart from "does not exist".
    if server is None or server.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    return server


@router.get("", response_model=MCPServersResponse)
def list_mcp_servers(
    registry: MCPServerRegistry = Depends(mcp_registry_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> MCPServersResponse:
    servers = registry.list_servers_for_owner(user_id)
    return MCPServersResponse(
        items=[_to_view(server) for server in servers],
        transports=list(REGISTRABLE_TRANSPORTS),
        registered=len(servers),
    )


@router.post("", response_model=MCPServerView, status_code=status.HTTP_201_CREATED)
def register_mcp_server(
    payload: MCPServerCreateRequest,
    registry: MCPServerRegistry = Depends(mcp_registry_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> MCPServerView:
    _validate_transport(payload.transport_type, payload.endpoint, payload.configuration)
    if registry.get_server_by_name(payload.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"an MCP server named '{payload.name}' is already registered",
        )
    try:
        server = registry.register(
            name=payload.name,
            description=payload.description,
            transport_type=payload.transport_type,
            endpoint=payload.endpoint,
            configuration=payload.configuration,
            # The owner comes from the resolved identity, never the request body.
            owner_id=user_id,
            # Trust is the engine's to assign; this route does not take it as input.
            trust_level="default",
        )
    except IntegrityError as error:
        # The name column is unique, so a concurrent registration can lose the
        # race between the check above and the insert. Report it as the conflict
        # it is instead of a 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"an MCP server named '{payload.name}' is already registered",
        ) from error
    return _to_view(server)


@router.patch("/{server_id}", response_model=MCPServerView)
def update_mcp_server(
    server_id: UUID,
    payload: MCPServerUpdateRequest,
    registry: MCPServerRegistry = Depends(mcp_registry_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> MCPServerView:
    server = _owned(registry, server_id, user_id)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("description") is not None:
        server.description = changes["description"]
    if changes.get("configuration") is not None:
        # Re-check against the transport already on the row: the transport is
        # immutable, so a new configuration must still fit it.
        _validate_transport(
            server.transport_type.value, server.endpoint, changes["configuration"]
        )
        server.update_configuration(changes["configuration"])
    if changes.get("enabled") is not None:
        if changes["enabled"]:
            server.enable()
        else:
            server.disable()

    return _to_view(registry.save_server(server))


@router.delete(
    "/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # Without ``from __future__ import annotations`` this would be inferred, but
    # postponed evaluation turns ``-> None`` into ``NoneType``, which FastAPI
    # then reads as a response model and refuses for a 204.
    response_model=None,
)
def delete_mcp_server(
    server_id: UUID,
    registry: MCPServerRegistry = Depends(mcp_registry_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> None:
    _owned(registry, server_id, user_id)
    registry.unregister(EntityId(server_id))
