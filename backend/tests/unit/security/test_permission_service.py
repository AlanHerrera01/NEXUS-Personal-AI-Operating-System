import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.application.permissions.permission_service import PermissionService
from app.domain.entities.permission import Permission
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel


@pytest.fixture
def mock_permission_repository():
    return Mock(spec=PermissionRepository)


@pytest.fixture
def permission_service(mock_permission_repository):
    return PermissionService(mock_permission_repository)


@pytest.fixture
def sample_permission():
    return Permission(
        user_id=EntityId.new(),
        agent_id=EntityId.new(),
        skill_name="tasks",
        action_name="tasks.search",
        scope="read",
        effect=PermissionDecision.ALLOW,
        risk_level=RiskLevel.LOW,
    )


class TestPermissionService:
    def test_grant_permission(self, permission_service, mock_permission_repository):
        user_id = EntityId.new()
        agent_id = EntityId.new()
        
        permission = permission_service.grant(
            user_id=user_id,
            agent_id=agent_id,
            skill_name="tasks",
            action_name="tasks.search",
            scope="read",
            effect=PermissionDecision.ALLOW,
            risk_level=RiskLevel.LOW,
        )
        
        assert isinstance(permission, Permission)
        assert permission.user_id == user_id
        assert permission.agent_id == agent_id
        assert permission.skill_name == "tasks"
        assert permission.action_name == "tasks.search"
        assert permission.scope == "read"
        assert permission.effect == PermissionDecision.ALLOW
        mock_permission_repository.save.assert_called_once()

    def test_grant_permission_with_expiration(self, permission_service, mock_permission_repository):
        user_id = EntityId.new()
        agent_id = EntityId.new()
        
        permission = permission_service.grant(
            user_id=user_id,
            agent_id=agent_id,
            skill_name="tasks",
            action_name="tasks.create",
            scope="write",
            effect=PermissionDecision.ALLOW,
            risk_level=RiskLevel.MEDIUM,
            expires_in_days=7,
        )
        
        assert permission.expires_at is not None
        expected_expiry = datetime.now(timezone.utc) + timedelta(days=7)
        # Allow 1 second tolerance
        assert abs((permission.expires_at - expected_expiry).total_seconds()) < 1

    def test_revoke_permission(self, permission_service, mock_permission_repository):
        user_id = EntityId.new()
        agent_id = EntityId.new()
        
        permission_service.revoke(
            user_id=user_id,
            agent_id=agent_id,
            skill_name="tasks",
            action_name="tasks.search",
        )
        
        # Revocation is scoped to the owner: a caller can only delete the
        # permission of the user/agent pair they are authenticated as.
        mock_permission_repository.delete.assert_called_once_with(
            user_id, agent_id, "tasks", "tasks.search"
        )

    def test_check_permission_granted(self, permission_service, mock_permission_repository):
        user_id = EntityId.new()
        agent_id = EntityId.new()
        
        mock_permission_repository.check_permission.return_value = True
        
        result = permission_service.check(
            user_id=user_id,
            agent_id=agent_id,
            skill_name="tasks",
            action_name="tasks.search",
        )
        
        assert result is True
        mock_permission_repository.check_permission.assert_called_once()

    def test_check_permission_denied(self, permission_service, mock_permission_repository):
        user_id = EntityId.new()
        agent_id = EntityId.new()
        
        mock_permission_repository.check_permission.return_value = False
        
        result = permission_service.check(
            user_id=user_id,
            agent_id=agent_id,
            skill_name="credentials",
            action_name="credentials.access",
        )
        
        assert result is False

    def test_list_by_user(self, permission_service, mock_permission_repository, sample_permission):
        user_id = sample_permission.user_id
        mock_permission_repository.list_all.return_value = [sample_permission]
        
        result = permission_service.list_by_user(user_id)
        
        assert len(result) == 1
        assert result[0].user_id == user_id

    def test_list_by_agent(self, permission_service, mock_permission_repository, sample_permission):
        agent_id = sample_permission.agent_id
        mock_permission_repository.list_all.return_value = [sample_permission]
        
        result = permission_service.list_by_agent(agent_id)
        
        assert len(result) == 1
        assert result[0].agent_id == agent_id

    def test_list_all(self, permission_service, mock_permission_repository, sample_permission):
        mock_permission_repository.list_all.return_value = [sample_permission]
        
        result = permission_service.list_all()
        
        assert len(result) == 1
        assert result[0] == sample_permission
