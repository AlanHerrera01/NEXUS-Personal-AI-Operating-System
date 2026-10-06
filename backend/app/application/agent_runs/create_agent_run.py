from dataclasses import dataclass

from app.domain.entities.agent_run import AgentRun
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CreateAgentRunUseCase:
    agent_repository: AgentRepository
    agent_run_repository: AgentRunRepository

    def execute(
        self, agent_id: EntityId, user_request: str, user_id: EntityId
    ) -> AgentRun:
        """Start a run of ``agent_id`` on behalf of ``user_id``.

        Both the agent lookup and the new run are owner-scoped. Looking the agent
        up unscoped would let a caller start runs against an agent they cannot
        read, and the resulting run would then be readable by them -- so the
        ownership check has to happen on the way in, not on the way out.
        """
        if user_id is None:
            raise ValueError("an agent run requires an owner")
        agent = self.agent_repository.get_by_id(agent_id, user_id)
        if agent is None:
            # Same message for "no such agent" and "not yours": a distinct error
            # for the second case confirms the agent exists.
            raise ValueError("agent not found")
        if agent.status is not AgentStatus.ACTIVE:
            raise ValueError("inactive agents cannot start runs")
        agent_run = AgentRun(
            agent_id=agent_id, user_request=user_request, user_id=user_id
        )
        return self.agent_run_repository.save(agent_run)