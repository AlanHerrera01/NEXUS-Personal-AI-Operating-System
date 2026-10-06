from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.application.permissions.permission_service import PermissionService
from app.domain.entities.permission import Permission
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from app.presentation.dependencies import get_permission_service
from app.presentation.dependencies.identity import current_user_id


router = APIRouter(prefix="/api/v1/permissions", tags=["permissions"])


class PermissionRequest(BaseModel):
    agent_id: str
    skill_name: str
    action_name: str
    scope: str
    effect: str
    risk_level: str = "LOW"
    expires_in_days: int | None = None


class PermissionResponse(BaseModel):
    id: str
    user_id: str
    agent_id: str
    skill_name: str
    action_name: str
    scope: str
    effect: str
    risk_level: str
    created_at: str
    expires_at: str | None

    @classmethod
    def from_entity(cls, permission: Permission) -> "PermissionResponse":
        return cls(
            id=str(permission.id),
            user_id=str(permission.user_id),
            agent_id=str(permission.agent_id),
            skill_name=permission.skill_name,
            action_name=permission.action_name,
            scope=permission.scope,
            effect=permission.effect.value,
            risk_level=permission.risk_level.value,
            created_at=permission.created_at.isoformat(),
            expires_at=permission.expires_at.isoformat() if permission.expires_at else None,
        )


@router.get("", response_model=list[PermissionResponse])
async def list_permissions(
    service: PermissionService = Depends(get_permission_service),
    user_id: EntityId = Depends(current_user_id),
) -> list[PermissionResponse]:
    """List the caller's own permissions.

    Was ``service.list_all()``: every grant on the deployment, for every user.
    A permission row is a record of what somebody was willing to let an agent do,
    so returning everyone's rows is both a disclosure and a map of the trust
    configuration for anyone who can reach the API.
    """
    return [
        PermissionResponse.from_entity(permission)
        for permission in service.list_by_user(user_id)
    ]


@router.post("", response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
async def create_permission(
    request: PermissionRequest,
    service: PermissionService = Depends(get_permission_service),
    user_id: EntityId = Depends(current_user_id),
) -> PermissionResponse:
    """Create a new permission for the caller.

    The owner is the resolved identity. The previous signature took
    ``user_id: str = "default-user-id"`` as a plain query parameter, so a caller
    could grant a permission *to* another user, and -- because it was a plain
    string rather than an id -- that value was then stored after
    ``EntityId.from_string`` on a value that is not a UUID at all.
    """
    try:
        permission = service.grant(
            user_id=user_id,
            agent_id=EntityId.from_string(request.agent_id),
            skill_name=request.skill_name,
            action_name=request.action_name,
            scope=request.scope,
            effect=PermissionDecision(request.effect),
            risk_level=RiskLevel(request.risk_level),
            expires_in_days=request.expires_in_days,
        )
        return PermissionResponse.from_entity(permission)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: str,
    service: PermissionService = Depends(get_permission_service),
    user_id: EntityId = Depends(current_user_id),
) -> None:
    """Revoke one of the caller's permissions by id.

    This replaced an endpoint that parsed ``"skill:action"`` out of the path and
    called ``service.revoke(user_id, EntityId("dummy"), skill, action)``. The
    agent id was a literal ``"dummy"``, so the DELETE matched a row that cannot
    exist and the permission was never actually revoked -- a user clicking
    "revoke" saw a 204 and the grant stayed live. Revoking by primary key fixes
    the correctness bug and removes the need to reconstruct a composite key from
    caller-supplied text.
    """
    try:
        entity_id = EntityId.from_string(permission_id)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid permission id"
        ) from error

    if not service.revoke_by_id(entity_id, user_id):
        # 404 for both "no such permission" and "not yours" -- see the note in
        # permission_requests.py: the distinction is an enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found"
        )