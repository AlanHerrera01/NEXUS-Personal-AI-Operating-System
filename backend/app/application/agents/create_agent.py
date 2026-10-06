from dataclasses import dataclass

from app.domain.entities.agent import Agent
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CreateAgentUseCase:
    agent_repository: AgentRepository

    def execute(
        self, name: str, user_id: EntityId, description: str = ""
    ) -> Agent:
        """Create an agent owned by ``user_id``.

        The owner is a required argument rather than something the repository
        fills in. Making it explicit here means "who owns this" is answered by
        the layer that received the request, not by a default deeper in the stack
        where it would apply equally to every caller.
        """
        if user_id is None:
            raise ValueError("an agent requires an owner")
        agent = Agent(name=name, description=description, user_id=user_id)
        return self.agent_repository.save(agent)