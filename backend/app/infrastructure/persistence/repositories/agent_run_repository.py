from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.agent_run import AgentRun
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.domain_mappers import agent_run_from_model, agent_run_to_model
from app.infrastructure.persistence.models import AgentRunModel


class SqlAlchemyAgentRunRepository(AgentRunRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, agent_run: AgentRun) -> AgentRun:
        existing = self.session.get(AgentRunModel, agent_run.id.value)
        if existing is None:
            self.session.add(agent_run_to_model(agent_run))
        else:
            existing.status = agent_run.status.value
            existing.user_request = agent_run.user_request
            existing.updated_at = agent_run.updated_at
            # Not the owner, for the same reason as agents: re-saving a run must
            # not be a way to claim it.
        self.session.commit()
        return agent_run_from_model(self.session.get(AgentRunModel, agent_run.id.value))

    def get_by_id(self, agent_run_id: EntityId, user_id: EntityId) -> AgentRun | None:
        model = self.session.scalars(
            select(AgentRunModel).where(
                AgentRunModel.id == agent_run_id.value,
                AgentRunModel.user_id == user_id.value,
            )
        ).first()
        return agent_run_from_model(model) if model else None