import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.mcp_server import MCPServer
from app.domain.repositories.mcp_server_repository import MCPServerRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.mcp_server_status import MCPServerStatus
from app.domain.value_objects.mcp_transport_type import MCPTransportType
from app.infrastructure.persistence.models.mcp_server_model import MCPServerModel


class SqlMCPServerRepository(MCPServerRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, server: MCPServer) -> None:
        model = MCPServerModel(
            id=str(server.id),
            name=server.name,
            description=server.description,
            transport_type=server.transport_type.value,
            endpoint=server.endpoint,
            configuration=json.dumps(server.configuration),
            enabled=server.enabled,
            trust_level=server.trust_level,
            owner_id=str(server.owner_id) if server.owner_id else None,
            status=server.status.value,
            created_at=server.created_at,
            updated_at=server.updated_at,
            last_connected_at=server.last_connected_at,
            metadata=json.dumps(server.metadata),
        )
        self.session.merge(model)
        self.session.commit()

    def get_by_id(self, server_id: EntityId) -> MCPServer | None:
        stmt = select(MCPServerModel).where(MCPServerModel.id == str(server_id))
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        return self._to_entity(result)

    def get_by_name(self, name: str) -> MCPServer | None:
        stmt = select(MCPServerModel).where(MCPServerModel.name == name)
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        return self._to_entity(result)

    def list_all(self) -> list[MCPServer]:
        stmt = select(MCPServerModel).order_by(MCPServerModel.name)
        results = self.session.execute(stmt).scalars().all()
        return [self._to_entity(r) for r in results]

    def list_enabled(self) -> list[MCPServer]:
        stmt = select(MCPServerModel).where(
            MCPServerModel.enabled == True
        ).order_by(MCPServerModel.name)
        results = self.session.execute(stmt).scalars().all()
        return [self._to_entity(r) for r in results]

    def delete(self, server_id: EntityId) -> None:
        stmt = select(MCPServerModel).where(MCPServerModel.id == str(server_id))
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is not None:
            self.session.delete(result)
            self.session.commit()

    def _to_entity(self, model: MCPServerModel) -> MCPServer:
        configuration = {}
        if model.configuration:
            try:
                configuration = json.loads(model.configuration)
            except (json.JSONDecodeError, TypeError):
                pass
        
        metadata = {}
        if model.metadata:
            try:
                metadata = json.loads(model.metadata)
            except (json.JSONDecodeError, TypeError):
                pass
        
        return MCPServer(
            id=EntityId.from_string(model.id),
            name=model.name,
            description=model.description,
            transport_type=MCPTransportType(model.transport_type),
            endpoint=model.endpoint,
            configuration=configuration,
            enabled=model.enabled,
            trust_level=model.trust_level,
            owner_id=EntityId.from_string(model.owner_id) if model.owner_id else None,
            status=MCPServerStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
            last_connected_at=model.last_connected_at,
            metadata=metadata,
        )
