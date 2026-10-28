from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.application.always_on.execution_coordinator import JobExecutionCoordinator
from app.application.security.approval_service import ApprovalService
from app.domain.entities.permission_request import PermissionRequest
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.presentation.dependencies import get_approval_service
from app.presentation.dependencies.always_on import get_job_execution_coordinator
from app.presentation.dependencies.identity import current_user_id


router = APIRouter(prefix="/api/v1/agent-runs", tags=["permission-requests"])


class PermissionRequestResponse(BaseModel):
    id: str
    agent_run_id: str
    tool_name: str
    skill_name: str
    reason: str
    risk_level: str
    arguments_summary: dict
    status: str
    created_at: str
    updated_at: str
    expires_at: str

    @classmethod
    def from_entity(cls, request: PermissionRequest) -> "PermissionRequestResponse":
        return cls(
            id=str(request.id),
            agent_run_id=str(request.agent_run_id),
            tool_name=request.tool_name,
            skill_name=request.skill_name,
            reason=request.reason,
            risk_level=request.risk_level.value,
            arguments_summary=request.arguments_summary,
            status=request.status.value,
            created_at=request.created_at.isoformat(),
            updated_at=request.updated_at.isoformat(),
            expires_at=request.expires_at.isoformat(),
        )


def _load_owned_request(
    service: ApprovalService, run_id: str, request_id: str, user_id: EntityId
) -> PermissionRequest:
    """Load the request, proving it belongs to this run *and* to this caller.

    Three checks, and all three are load-bearing. Existence, run association,
    and ownership are separable: a request id from another run passes the first
    two only if you skip one, and a request belonging to another user passes all
    of them if you keep the old hardcoded ``"default-user-id"`` placeholder --
    which is exactly what this module did before.

    Every failure returns 404. Distinguishing "exists but not yours" from "does
    not exist" is an enumeration oracle, and for an approval endpoint it would
    also tell an attacker which runs have pending actions worth guessing for.
    """
    try:
        run_entity_id = EntityId.from_string(run_id)
        request_entity_id = EntityId.from_string(request_id)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission request not found",
        ) from error

    request = service.get_by_id(request_entity_id)
    if request is None or request.agent_run_id != run_entity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Permission request not found"
        )
    if request.user_id is None or request.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Permission request not found"
        )
    return request


@router.get("/{run_id}/permission-requests", response_model=list[PermissionRequestResponse])
async def list_permission_requests(
    run_id: str,
    service: ApprovalService = Depends(get_approval_service),
    user_id: EntityId = Depends(current_user_id),
) -> list[PermissionRequestResponse]:
    """List the permission requests raised on an agent run.

    Filtering by owner happens after the query rather than in the repository,
    because this endpoint also exposes the argument summary of each request --
    what the agent wanted to do. Returning another user's pending requests would
    disclose their plan, not merely their existence.

    A run the caller does not own yields an empty list rather than a 403: the
    caller learns nothing about whether the run id is real.
    """
    try:
        run_entity_id = EntityId.from_string(run_id)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found"
        ) from error

    return [
        PermissionRequestResponse.from_entity(request)
        for request in service.list_by_run(run_entity_id)
        if request.user_id == user_id
    ]


@router.post("/{run_id}/permission-requests/{request_id}/approve", status_code=status.HTTP_200_OK)
async def approve_permission_request(
    run_id: str,
    request_id: str,
    service: ApprovalService = Depends(get_approval_service),
    coordinator: JobExecutionCoordinator = Depends(get_job_execution_coordinator),
    user_id: EntityId = Depends(current_user_id),
) -> PermissionRequestResponse:
    """Approve a pending permission request by resuming its run.

    Recording APPROVED and resuming are one step, not two. The orchestrator's
    ``resume`` is what re-checks the Trust Engine and calls
    ``approval_service.approve`` once the action is actually allowed, so this
    route must not mark the request APPROVED first. Doing that left resume with
    no PENDING request to match and the run parked in WAITING_PERMISSION forever:
    the "approved" action never ran. The coordinator resumes through the
    orchestrator, so a fresh single-use authorization is minted there rather than
    the approval being replayed as a token.
    """
    request = _load_owned_request(service, run_id, request_id, user_id)
    if request.status is not PermissionRequestStatus.PENDING:
        # Already-decided and expired are genuine 409s: the request exists and
        # is the caller's, but its state does not permit this transition.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot approve request in status: {request.status.value}",
        )

    outcome = await coordinator.reconcile(
        request.agent_run_id, allow=True, user_id=user_id
    )
    decided = service.get_by_id(request.id)
    if decided is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Permission request not found"
        )
    if decided.status is PermissionRequestStatus.PENDING:
        # Nothing recorded the decision: the run was not in a state resume could
        # advance, so there was no action to authorize. Refusing is the honest
        # answer -- marking it APPROVED would claim an execution that never
        # happened, which is exactly the bug this route used to have.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=outcome.detail or "The agent run could not be resumed",
        )
    return PermissionRequestResponse.from_entity(decided)


@router.post("/{run_id}/permission-requests/{request_id}/reject", status_code=status.HTTP_200_OK)
async def reject_permission_request(
    run_id: str,
    request_id: str,
    service: ApprovalService = Depends(get_approval_service),
    coordinator: JobExecutionCoordinator = Depends(get_job_execution_coordinator),
    user_id: EntityId = Depends(current_user_id),
) -> PermissionRequestResponse:
    """Reject a pending permission request by resuming its run.

    Resumed with ``allow=False`` so the run observes the refusal and can finish
    rather than being left parked. A rejection is a decision, not a
    cancellation: the agent may still report what it was going to do. As with
    approve, the resume records the rejection -- the route must not flip the
    request first, or resume would find no PENDING request to act on.
    """
    request = _load_owned_request(service, run_id, request_id, user_id)
    if request.status is not PermissionRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reject request in status: {request.status.value}",
        )

    outcome = await coordinator.reconcile(
        request.agent_run_id, allow=False, user_id=user_id
    )
    decided = service.get_by_id(request.id)
    if decided is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Permission request not found"
        )
    if decided.status is PermissionRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=outcome.detail or "The agent run could not be resumed",
        )
    return PermissionRequestResponse.from_entity(decided)