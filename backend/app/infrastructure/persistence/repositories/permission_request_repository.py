import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.permission_request import PermissionRequest
from app.domain.ports.permission_request_repository import PermissionRequestRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.persistence.models.permission_request_model import PermissionRequestModel


class SqlPermissionRequestRepository(PermissionRequestRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, request: PermissionRequest) -> None:
        model = PermissionRequestModel(
            id=str(request.id),
            agent_run_id=str(request.agent_run_id),
            user_id=str(request.user_id) if request.user_id else None,
            tool_name=request.tool_name,
            skill_name=request.skill_name,
            reason=request.reason,
            risk_level=request.risk_level.value,
            arguments_summary=json.dumps(request.arguments_summary),
            status=request.status.value,
            created_at=request.created_at,
            updated_at=request.updated_at,
            expires_at=request.expires_at,
            consumed_at=request.consumed_at,
        )
        self.session.merge(model)
        self.session.commit()

    def get_by_id(self, request_id: EntityId) -> PermissionRequest | None:
        stmt = select(PermissionRequestModel).where(PermissionRequestModel.id == str(request_id))
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        return self._to_entity(result)

    def get_by_run_id(self, run_id: EntityId) -> list[PermissionRequest]:
        stmt = select(PermissionRequestModel).where(
            PermissionRequestModel.agent_run_id == str(run_id)
        ).order_by(PermissionRequestModel.created_at)
        results = self.session.execute(stmt).scalars().all()
        return [self._to_entity(r) for r in results]

    def get_pending_by_run_id(self, run_id: EntityId) -> PermissionRequest | None:
        stmt = select(PermissionRequestModel).where(
            PermissionRequestModel.agent_run_id == str(run_id),
            PermissionRequestModel.status == PermissionRequestStatus.PENDING.value
        ).order_by(PermissionRequestModel.created_at.desc())
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        return self._to_entity(result)

    def list_all(self) -> list[PermissionRequest]:
        stmt = select(PermissionRequestModel).order_by(PermissionRequestModel.created_at.desc())
        results = self.session.execute(stmt).scalars().all()
        return [self._to_entity(r) for r in results]

    def _to_entity(self, model: PermissionRequestModel) -> PermissionRequest:
        arguments_summary = {}
        if model.arguments_summary:
            try:
                arguments_summary = json.loads(model.arguments_summary)
            except (json.JSONDecodeError, TypeError):
                arguments_summary = {}
        
        return PermissionRequest(
            id=EntityId.from_string(model.id),
            agent_run_id=EntityId.from_string(model.agent_run_id),
            user_id=EntityId.from_string(model.user_id) if model.user_id else None,
            tool_name=model.tool_name,
            skill_name=model.skill_name,
            reason=model.reason,
            risk_level=RiskLevel(model.risk_level),
            arguments_summary=arguments_summary,
            status=PermissionRequestStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
            expires_at=model.expires_at,
            consumed_at=model.consumed_at,
        )
