from datetime import datetime, timedelta, timezone

from app.domain.entities.permission_request import PermissionRequest
from app.domain.ports.permission_request_repository import PermissionRequestRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.risk_level import RiskLevel


class ApprovalService:
    """Service for managing permission requests and approvals."""

    def __init__(
        self,
        permission_request_repository: PermissionRequestRepository,
        request_ttl_seconds: int = 300,
    ) -> None:
        self.permission_request_repository = permission_request_repository
        self.request_ttl_seconds = request_ttl_seconds

    def create_request(
        self,
        agent_run_id: EntityId,
        tool_name: str,
        skill_name: str,
        reason: str,
        risk_level: RiskLevel,
        arguments_summary: dict,
        user_id: EntityId,
    ) -> PermissionRequest:
        """Create a new permission request on behalf of ``user_id``.

        The owner is required. A request exists so that a specific person is
        asked whether a specific action may proceed; without recording who was
        asked, "approve my own requests only" is not checkable later, and the
        check that matters most is the one that gets skipped.
        """
        if user_id is None:
            raise ValueError("a permission request requires an owner")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.request_ttl_seconds)
        
        request = PermissionRequest(
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            skill_name=skill_name,
            reason=reason,
            risk_level=risk_level,
            arguments_summary=arguments_summary,
            user_id=user_id,
            expires_at=expires_at,
        )

        self.permission_request_repository.save(request)
        return request

    def approve(self, request_id: EntityId) -> PermissionRequest:
        """Approve a pending permission request."""
        request = self.permission_request_repository.get_by_id(request_id)
        if request is None:
            raise ValueError("Permission request not found")
        
        if request.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot approve request in status: {request.status}")
        
        if request.is_expired():
            request.expire()
            self.permission_request_repository.save(request)
            raise ValueError("Permission request has expired")
        
        request.approve()
        self.permission_request_repository.save(request)
        return request

    def reject(self, request_id: EntityId) -> PermissionRequest:
        """Reject a pending permission request."""
        request = self.permission_request_repository.get_by_id(request_id)
        if request is None:
            raise ValueError("Permission request not found")
        
        if request.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot reject request in status: {request.status}")
        
        request.reject()
        self.permission_request_repository.save(request)
        return request

    def cancel(self, request_id: EntityId) -> PermissionRequest:
        """Cancel a pending permission request."""
        request = self.permission_request_repository.get_by_id(request_id)
        if request is None:
            raise ValueError("Permission request not found")
        
        if request.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot cancel request in status: {request.status}")
        
        request.cancel()
        self.permission_request_repository.save(request)
        return request

    def consume(self, request_id: EntityId) -> PermissionRequest:
        """Mark an approved request as consumed (used). Single-use enforced."""
        request = self.permission_request_repository.get_by_id(request_id)
        if request is None:
            raise ValueError("Permission request not found")

        if not request.is_consumable():
            raise ValueError(f"Request is not consumable: {request.status}")

        request.consume()
        self.permission_request_repository.save(request)
        return request

    def get_pending_by_run(self, run_id: EntityId) -> PermissionRequest | None:
        """Get the pending permission request for an agent run."""
        return self.permission_request_repository.get_pending_by_run_id(run_id)

    def get_by_id(self, request_id: EntityId) -> PermissionRequest | None:
        """Get a permission request by ID."""
        return self.permission_request_repository.get_by_id(request_id)

    def list_by_run(self, run_id: EntityId) -> list[PermissionRequest]:
        """List all permission requests for an agent run."""
        return self.permission_request_repository.get_by_run_id(run_id)

    def expire(self, request_id: EntityId) -> PermissionRequest:
        """Expire one pending request.

        Separate from :meth:`expire_old_requests` because a caller that is holding
        a request it has just discovered is past its TTL needs to move that
        specific request out of PENDING. Without this, an expired request stays
        PENDING forever and every retry re-discovers it as "still pending".
        """
        request = self.permission_request_repository.get_by_id(request_id)
        if request is None:
            raise ValueError("Permission request not found")

        if request.status == PermissionRequestStatus.EXPIRED:
            return request
        if request.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Cannot expire request in status: {request.status}")

        request.expire()
        self.permission_request_repository.save(request)
        return request

    def expire_old_requests(self) -> int:
        """Expire all pending requests that have passed their TTL."""
        all_requests = self.permission_request_repository.list_all()
        expired_count = 0
        
        for request in all_requests:
            if request.status == PermissionRequestStatus.PENDING and request.is_expired():
                request.expire()
                self.permission_request_repository.save(request)
                expired_count += 1
        
        return expired_count
