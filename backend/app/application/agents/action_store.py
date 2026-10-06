from app.domain.entities.agent_action import AgentAction
from app.domain.ports.agent_action_repository import AgentActionRepository
from app.domain.value_objects.entity_id import EntityId


class InMemoryAgentActionRepository(AgentActionRepository):
    def __init__(self) -> None:
        self.items: list[AgentAction] = []

    def save(self, action: AgentAction) -> AgentAction:
        self.items.append(action)
        return action

    def list_by_run(self, agent_run_id: EntityId) -> list[AgentAction]:
        return [action for action in self.items if action.agent_run_id == agent_run_id]
