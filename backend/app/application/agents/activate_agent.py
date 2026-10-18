from dataclasses import dataclass

from app.domain.entities.agent import Agent
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId


@dataclass
class ActivateAgentUseCase:
    agent_repository: AgentRepository

    def execute(self, agent_id: EntityId, user_id: EntityId) -> Agent | None:
        """Make ``agent_id`` the caller's active agent, or None if it is not theirs.

        Activation is exclusive. The dashboard reads "the active agent" as a
        single agent -- the first one it finds in ACTIVE state -- so leaving two
        active would make which one the objective bar uses depend on creation
        order. Deactivating the caller's other agents makes that choice theirs.

        The target is loaded with the owner in the WHERE clause, so an agent that
        is not the caller's is indistinguishable from one that does not exist and
        no other user's agent is mutated on the way.
        """
        target = self.agent_repository.get_by_id(agent_id, user_id)
        if target is None:
            return None
        for agent in self.agent_repository.list_by_user(user_id):
            if agent.id != target.id and agent.status is AgentStatus.ACTIVE:
                agent.deactivate()
                self.agent_repository.save(agent)
        target.activate()
        return self.agent_repository.save(target)
