import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.application.security.approval_service import ApprovalService
from app.domain.entities.permission_request import PermissionRequest
from app.domain.ports.permission_request_repository import PermissionRequestRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.risk_level import RiskLevel


@pytest.fixture
def mock_permission_request_repository():
    return Mock(spec=PermissionRequestRepository)


@pytest.fixture
def approval_service(mock_permission_request_repository):
    return ApprovalService(
        permission_request_repository=mock_permission_request_repository,
        request_ttl_seconds=300,
    )


@pytest.fixture
def sample_permission_request():
    return PermissionRequest(
        agent_run_id=EntityId.new(),
        tool_name="calendar.create",
        skill_name="calendar",
        reason="Medium-risk action requires confirmation",
        risk_level=RiskLevel.MEDIUM,
        arguments_summary={"title": "Meeting"},
    )


class TestApprovalService:
    def test_create_request(self, approval_service, mock_permission_request_repository):
        agent_run_id = EntityId.new()
        
        request = approval_service.create_request(
            agent_run_id=agent_run_id,
            tool_name="calendar.create",
            skill_name="calendar",
            reason="Medium-risk action requires confirmation",
            risk_level=RiskLevel.MEDIUM,
            arguments_summary={"title": "Meeting"},
        )
        
        assert isinstance(request, PermissionRequest)
        assert request.agent_run_id == agent_run_id
        assert request.tool_name == "calendar.create"
        assert request.skill_name == "calendar"
        assert request.status == PermissionRequestStatus.PENDING
        assert request.expires_at > datetime.now(timezone.utc)
        mock_permission_request_repository.save.assert_called_once()

    def test_approve_pending_request(self, approval_service, mock_permission_request_repository, sample_permission_request):
        mock_permission_request_repository.get_by_id.return_value = sample_permission_request
        
        result = approval_service.approve(sample_permission_request.id)
        
        assert result.status == PermissionRequestStatus.APPROVED
        mock_permission_request_repository.save.assert_called()

    def test_approve_expired_request_raises_error(self, approval_service, mock_permission_request_repository):
        expired_request = PermissionRequest(
            agent_run_id=EntityId.new(),
            tool_name="calendar.create",
            skill_name="calendar",
            reason="Test",
            risk_level=RiskLevel.MEDIUM,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),  # Expired
        )
        mock_permission_request_repository.get_by_id.return_value = expired_request
        
        with pytest.raises(ValueError, match="expired"):
            approval_service.approve(expired_request.id)

    def test_approve_non_pending_request_raises_error(self, approval_service, mock_permission_request_repository, sample_permission_request):
        sample_permission_request.status = PermissionRequestStatus.APPROVED
        mock_permission_request_repository.get_by_id.return_value = sample_permission_request
        
        with pytest.raises(ValueError, match="Cannot approve"):
            approval_service.approve(sample_permission_request.id)

    def test_reject_pending_request(self, approval_service, mock_permission_request_repository, sample_permission_request):
        mock_permission_request_repository.get_by_id.return_value = sample_permission_request
        
        result = approval_service.reject(sample_permission_request.id)
        
        assert result.status == PermissionRequestStatus.REJECTED
        mock_permission_request_repository.save.assert_called()

    def test_reject_non_pending_request_raises_error(self, approval_service, mock_permission_request_repository, sample_permission_request):
        sample_permission_request.status = PermissionRequestStatus.REJECTED
        mock_permission_request_repository.get_by_id.return_value = sample_permission_request
        
        with pytest.raises(ValueError, match="Cannot reject"):
            approval_service.reject(sample_permission_request.id)

    def test_cancel_pending_request(self, approval_service, mock_permission_request_repository, sample_permission_request):
        mock_permission_request_repository.get_by_id.return_value = sample_permission_request
        
        result = approval_service.cancel(sample_permission_request.id)
        
        assert result.status == PermissionRequestStatus.CANCELLED
        mock_permission_request_repository.save.assert_called()

    def test_get_pending_by_run(self, approval_service, mock_permission_request_repository, sample_permission_request):
        run_id = EntityId.new()
        mock_permission_request_repository.get_pending_by_run_id.return_value = sample_permission_request
        
        result = approval_service.get_pending_by_run(run_id)
        
        assert result == sample_permission_request
        mock_permission_request_repository.get_pending_by_run_id.assert_called_once_with(run_id)

    def test_get_by_id(self, approval_service, mock_permission_request_repository, sample_permission_request):
        mock_permission_request_repository.get_by_id.return_value = sample_permission_request
        
        result = approval_service.get_by_id(sample_permission_request.id)
        
        assert result == sample_permission_request

    def test_list_by_run(self, approval_service, mock_permission_request_repository, sample_permission_request):
        run_id = EntityId.new()
        mock_permission_request_repository.get_by_run_id.return_value = [sample_permission_request]
        
        result = approval_service.list_by_run(run_id)
        
        assert len(result) == 1
        assert result[0] == sample_permission_request

    def test_expire_old_requests(self, approval_service, mock_permission_request_repository, sample_permission_request):
        expired_request = PermissionRequest(
            agent_run_id=EntityId.new(),
            tool_name="calendar.create",
            skill_name="calendar",
            reason="Test",
            risk_level=RiskLevel.MEDIUM,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        mock_permission_request_repository.list_all.return_value = [sample_permission_request, expired_request]
        
        count = approval_service.expire_old_requests()
        
        assert count == 1
        assert expired_request.status == PermissionRequestStatus.EXPIRED

    def test_consume_consumable_request(self, approval_service, sample_permission_request):
        sample_permission_request.status = PermissionRequestStatus.APPROVED
        sample_permission_request.expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        
        # Should not raise error
        approval_service.consume(sample_permission_request.id)

    def test_consume_non_consumable_request_raises_error(self, approval_service, sample_permission_request):
        # Mock the repository to return the modified request
        sample_permission_request.status = PermissionRequestStatus.PENDING
        sample_permission_request.expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        
        # The consume method fetches from repository, so we need to mock that
        from app.domain.ports.permission_request_repository import PermissionRequestRepository
        mock_repo = approval_service.permission_request_repository
        mock_repo.get_by_id.return_value = sample_permission_request
        
        with pytest.raises(ValueError, match="not consumable"):
            approval_service.consume(sample_permission_request.id)
