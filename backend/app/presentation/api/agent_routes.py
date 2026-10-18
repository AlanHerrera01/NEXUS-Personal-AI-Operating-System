"""The agent registry.

Three screens were dead ends without this. The objective bar, the runs page and
the memory page all act on an agent, and ``GET /api/v1/overview`` reports the
caller's active agent -- but ``CreateAgentUseCase`` was reachable only from
tests, so a fresh deployment had no way to create the one thing everything else
required.

What is enforced here:

* reads and writes are owner-scoped from the resolved identity, never from the
  payload, and an id the caller does not own answers 404 rather than 403 so the
  route cannot be used to enumerate agent ids;
* activation is exclusive. The dashboard reads "the active agent" as a single
  agent, so activating one deactivates the caller's others instead of leaving
  which one is used up to creation order.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.agents.activate_agent import ActivateAgentUseCase
from app.application.agents.create_agent import CreateAgentUseCase
from app.domain.entities.agent import Agent
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId
from app.presentation.dependencies.agents import get_agent_repository
from app.presentation.dependencies.identity import current_user_id
from app.presentation.schemas.agents import (
    AgentView,
    AgentsResponse,
    CreateAgentRequest,
    UpdateAgentRequest,
)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _view(agent: Agent) -> AgentView:
    return AgentView(
        id=str(agent.id),
        name=agent.name,
        description=agent.description,
        status=agent.status.value,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat(),
    )


def _owned(repository: AgentRepository, agent_id: UUID, user_id: EntityId) -> Agent:
    agent = repository.get_by_id(EntityId(agent_id), user_id)
    # 404 rather than 403: a caller that does not own the agent should not be able
    # to tell "not yours" apart from "does not exist".
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )
    return agent


@router.get("", response_model=AgentsResponse)
def list_agents(
    repository: AgentRepository = Depends(get_agent_repository),
    user_id: EntityId = Depends(current_user_id),
) -> AgentsResponse:
    agents = repository.list_by_user(user_id)
    # Selected exactly as the overview selects it, so the selector and the
    # dashboard cannot name different agents.
    active = next(
        (agent for agent in agents if agent.status is AgentStatus.ACTIVE), None
    )
    return AgentsResponse(
        items=[_view(agent) for agent in agents],
        active_id=str(active.id) if active is not None else None,
    )


@router.post("", response_model=AgentView, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: CreateAgentRequest,
    repository: AgentRepository = Depends(get_agent_repository),
    user_id: EntityId = Depends(current_user_id),
) -> AgentView:
    # The owner comes from the resolved identity, never from the request body.
    agent = CreateAgentUseCase(repository).execute(
        payload.name, user_id, payload.description
    )
    return _view(agent)


@router.patch("/{agent_id}", response_model=AgentView)
def update_agent(
    agent_id: UUID,
    payload: UpdateAgentRequest,
    repository: AgentRepository = Depends(get_agent_repository),
    user_id: EntityId = Depends(current_user_id),
) -> AgentView:
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("status") == AgentStatus.ACTIVE.value:
        activated = ActivateAgentUseCase(repository).execute(EntityId(agent_id), user_id)
        if activated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
            )
        agent = activated
    else:
        agent = _owned(repository, agent_id, user_id)
        if changes.get("status") == AgentStatus.INACTIVE.value:
            agent.deactivate()

    if changes.get("name") is not None:
        agent.name = changes["name"]
    if changes.get("description") is not None:
        agent.description = changes["description"]

    return _view(repository.save(agent))
