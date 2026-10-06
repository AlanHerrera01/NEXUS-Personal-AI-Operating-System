from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.agent import Agent
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.domain_mappers import agent_from_model, agent_to_model
from app.infrastructure.persistence.models import AgentModel


class SqlAlchemyAgentRepository(AgentRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, agent: Agent) -> Agent:
        existing = self.session.get(AgentModel, agent.id.value)
        if existing is None:
            self.session.add(agent_to_model(agent))
        else:
            existing.name = agent.name
            existing.description = agent.description
            existing.status = agent.status.value
            existing.updated_at = agent.updated_at
            # Deliberately not reassigned: the owner of an agent is not something
            # an update request may change. If that were writable, saving an agent
            # you did not own -- via any path that loads then re-saves it -- would
            # quietly transfer it to you.
        self.session.commit()
        return agent_from_model(self.session.get(AgentModel, agent.id.value))

    def get_by_id(self, agent_id: EntityId, user_id: EntityId) -> Agent | None:
        # The owner is part of the WHERE clause rather than a post-fetch check, so
        # a mismatched agent never becomes a loaded entity on this session. Once an
        # Agent is in the identity map it is reachable from anywhere holding that
        # session; not loading it is the stronger position.
        model = self.session.scalars(
            select(AgentModel).where(
                AgentModel.id == agent_id.value,
                AgentModel.user_id == user_id.value,
            )
        ).first()
        return agent_from_model(model) if model else None