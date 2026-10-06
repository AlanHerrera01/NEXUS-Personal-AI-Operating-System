import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.permission import Permission
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.persistence.models.permission_model import PermissionModel


class SqlPermissionRepository(PermissionRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, permission: Permission) -> None:
        model = PermissionModel(
            id=str(permission.id),
            user_id=str(permission.user_id),
            agent_id=str(permission.agent_id),
            skill_name=permission.skill_name,
            action_name=permission.action_name,
            scope=permission.scope,
            effect=permission.effect.value,
            risk_level=permission.risk_level.value,
            created_at=permission.created_at,
            expires_at=permission.expires_at,
        )
        self.session.merge(model)
        self.session.commit()

    def get(self, skill_name: str, action_name: str) -> Permission | None:
        stmt = select(PermissionModel).where(
            PermissionModel.skill_name == skill_name,
            PermissionModel.action_name == action_name
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        return self._to_entity(result)

    def list_all(self) -> list[Permission]:
        stmt = select(PermissionModel)
        results = self.session.execute(stmt).scalars().all()
        return [self._to_entity(r) for r in results]

    def delete(self, user_id: EntityId, agent_id: EntityId, skill_name: str, action_name: str) -> None:
        stmt = select(PermissionModel).where(
            PermissionModel.user_id == str(user_id),
            PermissionModel.agent_id == str(agent_id),
            PermissionModel.skill_name == skill_name,
            PermissionModel.action_name == action_name
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is not None:
            self.session.delete(result)
            self.session.commit()

    def resolve(
        self,
        user_id: EntityId | None,
        agent_id: EntityId,
        skill_name: str,
        action_name: str,
    ) -> Permission | None:
        """Most specific live permission for an action, or None.

        Specificity order: exact tool, then the action wildcard. An exact DENY
        therefore beats a wildcard ALLOW, which is the direction that fails
        closed. Expired rows are skipped rather than returned, so a stale DENY
        does not outlive its own expiry -- expiry is an explicit decision to
        return to the default, not a permanent refusal.
        """
        # A permission belongs to a user. With no user there is nobody to have
        # granted it, so nothing matches and the caller falls back to the
        # default-deny policy set.
        if user_id is None:
            return None

        for candidate_action in (action_name, "*"):
            stmt = select(PermissionModel).where(
                PermissionModel.user_id == str(user_id),
                PermissionModel.agent_id == str(agent_id),
                PermissionModel.skill_name == skill_name,
                PermissionModel.action_name == candidate_action,
            )
            result = self.session.execute(stmt).scalars().first()
            if result is None:
                continue
            permission = self._to_entity(result)
            if permission.is_valid():
                return permission
            # An expired row at this specificity means "no live opinion"; keep
            # looking at the next-wider level rather than returning it.
        return None

    def check_permission(self, user_id: EntityId, agent_id: EntityId, skill_name: str, action_name: str) -> bool:
        # Check for exact match first
        stmt = select(PermissionModel).where(
            PermissionModel.user_id == str(user_id),
            PermissionModel.agent_id == str(agent_id),
            PermissionModel.skill_name == skill_name,
            PermissionModel.action_name == action_name,
            PermissionModel.effect == "ALLOW"
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is not None:
            permission = self._to_entity(result)
            return permission.is_valid()
        
        # Check for wildcard skill permission (skill_name.*)
        stmt = select(PermissionModel).where(
            PermissionModel.user_id == str(user_id),
            PermissionModel.agent_id == str(agent_id),
            PermissionModel.skill_name == skill_name,
            PermissionModel.action_name == "*",
            PermissionModel.effect == "ALLOW"
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        if result is not None:
            permission = self._to_entity(result)
            return permission.is_valid()
        
        return False

    def _to_entity(self, model: PermissionModel) -> Permission:
        return Permission(
            user_id=EntityId.from_string(model.user_id),
            agent_id=EntityId.from_string(model.agent_id),
            skill_name=model.skill_name,
            action_name=model.action_name,
            scope=model.scope,
            effect=PermissionDecision(model.effect),
            risk_level=RiskLevel(model.risk_level),
            created_at=model.created_at,
            expires_at=model.expires_at,
            id=EntityId.from_string(model.id),
        )

    def get_by_id(self, permission_id: EntityId, user_id: EntityId) -> Permission | None:
        """One grant, if it exists and belongs to ``user_id``.

        Owner-scoped so the delete endpoint can revoke by id without first
        learning whose grant it is. ``None`` covers both "no such row" and "not
        yours", which is the only safe answer for an id that came from a URL.
        """
        result = self.session.scalars(
            select(PermissionModel).where(
                PermissionModel.id == str(permission_id),
                PermissionModel.user_id == str(user_id),
            )
        ).first()
        return self._to_entity(result) if result else None

    def delete_by_id(self, permission_id: EntityId, user_id: EntityId) -> bool:
        """Revoke exactly one grant, and only the caller's. True if a row went."""
        model = self.session.scalars(
            select(PermissionModel).where(
                PermissionModel.id == str(permission_id),
                PermissionModel.user_id == str(user_id),
            )
        ).first()
        if model is None:
            return False
        self.session.delete(model)
        self.session.commit()
        return True
