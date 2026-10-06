from datetime import datetime, timedelta, timezone

from app.domain.entities.permission import Permission
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel


class PermissionService:
    """Service for managing user/agent permissions."""

    def __init__(self, permission_repository: PermissionRepository) -> None:
        self.permission_repository = permission_repository

    def grant(
        self,
        user_id: EntityId,
        agent_id: EntityId,
        skill_name: str,
        action_name: str,
        scope: str,
        effect: PermissionDecision,
        risk_level: RiskLevel = RiskLevel.LOW,
        expires_in_days: int | None = None,
    ) -> Permission:
        """Grant a permission to a user/agent."""
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        permission = Permission(
            user_id=user_id,
            agent_id=agent_id,
            skill_name=skill_name,
            action_name=action_name,
            scope=scope,
            effect=effect,
            risk_level=risk_level,
            expires_at=expires_at,
        )

        self.permission_repository.save(permission)
        return permission

    def revoke(self, user_id: EntityId, agent_id: EntityId, skill_name: str, action_name: str) -> None:
        """Revoke a permission. Scoped to one user/agent pair on purpose."""
        self.permission_repository.delete(user_id, agent_id, skill_name, action_name)

    def revoke_by_id(self, permission_id: EntityId, user_id: EntityId) -> bool:
        """Revoke the specific grant ``permission_id``, if the caller owns it.

        Preferred over :meth:`revoke` for anything driven by a URL, because it
        addresses one row by primary key instead of reconstructing a composite key
        from user-supplied strings. Returns False rather than raising when there
        is nothing to revoke: the caller cannot tell the difference between a
        missing grant and someone else's, and it should not be able to.
        """
        return self.permission_repository.delete_by_id(permission_id, user_id)

    def get(self, permission_id: EntityId, user_id: EntityId) -> Permission | None:
        """Look one grant up, owner-scoped."""
        return self.permission_repository.get_by_id(permission_id, user_id)

    def check(
        self,
        user_id: EntityId,
        agent_id: EntityId,
        skill_name: str,
        action_name: str,
    ) -> bool:
        """Check if a user/agent has permission for a specific skill/action."""
        return self.permission_repository.check_permission(user_id, agent_id, skill_name, action_name)

    def list_by_user(self, user_id: EntityId) -> list[Permission]:
        """List all permissions for a user."""
        # This would need to be implemented in the repository
        # For now, return all permissions and filter
        all_permissions = self.permission_repository.list_all()
        return [p for p in all_permissions if p.user_id == user_id]

    def list_by_agent(self, agent_id: EntityId) -> list[Permission]:
        """List all permissions for an agent."""
        # This would need to be implemented in the repository
        # For now, return all permissions and filter
        all_permissions = self.permission_repository.list_all()
        return [p for p in all_permissions if p.agent_id == agent_id]

    def list_all(self) -> list[Permission]:
        """List all permissions."""
        return self.permission_repository.list_all()
