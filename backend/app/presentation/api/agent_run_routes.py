from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.application.agent_runs.create_agent_run import CreateAgentRunUseCase
from app.application.agents.orchestrator import AgentOrchestrator
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.infrastructure.persistence.repositories.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.repositories.agent_action_repository import SqlAlchemyAgentActionRepository
from app.domain.value_objects.execution_authorization import AuthorizationError
from app.presentation.dependencies.agent import orchestrator_dependency
from app.presentation.dependencies.identity import current_user_id
from app.presentation.dependencies.persistence import session_dependency
from app.presentation.schemas.agent_runs import AgentActionResponse, AgentRunResponse, CreateAgentRunRequest, ResumeAgentRunRequest

router = APIRouter(prefix="/api/v1/agents", tags=["agent-runs"])


@router.post("/{agent_id}/runs", response_model=AgentRunResponse, status_code=status.HTTP_201_CREATED)
async def run_agent(
    agent_id: UUID,
    payload: CreateAgentRunRequest,
    session: Session = Depends(session_dependency),
    orchestrator: AgentOrchestrator = Depends(orchestrator_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> AgentRunResponse:
    use_case = CreateAgentRunUseCase(
        SqlAlchemyAgentRepository(session),
        SqlAlchemyAgentRunRepository(session),
    )
    try:
        run = use_case.execute(EntityId(agent_id), payload.input, user_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    # The owner is resolved from the server-side identity, never from the payload.
    # Previously this call passed nothing at all, so every authorization decision
    # for an agent run was made with a null user.
    result = await orchestrator.execute(run, user_id=str(user_id))
    return AgentRunResponse(
        run_id=str(result.run.id),
        status=result.run.status.value,
        response=result.response,
        question=result.question,
        actions=[
            AgentActionResponse(
                tool_name=action.action_name,
                status=action.status.value,
                arguments=action.arguments,
            )
            for action in SqlAlchemyAgentActionRepository(session).list_by_run(result.run.id)
        ],
    )


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
def get_agent_run(
    run_id: UUID,
    session: Session = Depends(session_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> AgentRunResponse:
    # Owner-scoped. The run id comes from the URL, so an unscoped lookup here
    # returned any run on the deployment along with the full list of tool
    # arguments it attempted -- which is the request text and the agent's plan.
    run = SqlAlchemyAgentRunRepository(session).get_by_id(EntityId(run_id), user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return AgentRunResponse(
        run_id=str(run.id),
        status=run.status.value,
        actions=[
            AgentActionResponse(
                tool_name=action.action_name,
                status=action.status.value,
                arguments=action.arguments,
            )
            for action in SqlAlchemyAgentActionRepository(session).list_by_run(run.id)
        ],
    )


@router.post("/runs/{run_id}/resume", response_model=AgentRunResponse)
async def resume_agent_run(
    run_id: UUID,
    payload: ResumeAgentRunRequest,
    session: Session = Depends(session_dependency),
    orchestrator: AgentOrchestrator = Depends(orchestrator_dependency),
    user_id: EntityId = Depends(current_user_id),
) -> AgentRunResponse:
    # Resuming is a state transition on somebody's run, so the run must be loaded
    # under the acting identity before the orchestrator is even reached. Checking
    # ownership only inside resume would leave the unscoped read in place here.
    run = SqlAlchemyAgentRunRepository(session).get_by_id(EntityId(run_id), user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    try:
        result = await orchestrator.resume(
            run, payload.permission.value == "ALLOW", user_id=str(user_id)
        )
    except AuthorizationError as error:
        # The run is not in a state where an authorization may be minted. That is
        # a conflict with the run's state, not a client error, and the detail is
        # our own message rather than a policy explanation.
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return AgentRunResponse(
        run_id=str(result.run.id),
        status=result.run.status.value,
        response=result.response,
        actions=[
            AgentActionResponse(
                tool_name=action.action_name,
                status=action.status.value,
                arguments=action.arguments,
            )
            for action in SqlAlchemyAgentActionRepository(session).list_by_run(result.run.id)
        ],
    )
