from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.entities.agent_run import AgentRun
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.domain_mappers import agent_run_from_model, agent_run_to_model
from app.infrastructure.persistence.models import AgentRunModel, PermissionRequestModel


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
            existing.response = agent_run.response
            existing.question = agent_run.question
            existing.conversation_id = agent_run.conversation_id.value if agent_run.conversation_id else None
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

    def delete(self, agent_run_id: EntityId, user_id: EntityId) -> bool:
        model = self.session.get(AgentRunModel, agent_run_id.value)
        if model is None or model.user_id != user_id.value:
            return False
        # Actions, execution plans and runtime sessions carry ON DELETE CASCADE,
        # and job executions point at a run with ON DELETE SET NULL, so they do
        # not need clearing here. Permission requests do: their agent_run_id is a
        # plain string with no foreign key, so nothing cascades them and a
        # deleted run would leave its approvals behind.
        self.session.execute(
            delete(PermissionRequestModel).where(
                PermissionRequestModel.agent_run_id == str(agent_run_id.value)
            )
        )
        self.session.delete(model)
        self.session.commit()
        return True

    def list_by_user(self, user_id: EntityId, limit: int = 50) -> list[AgentRun]:
        """Most recent runs owned by ``user_id``.

        The owner is part of the WHERE clause for the same reason it is on
        :meth:`get_by_id`: a dashboard that lists runs is a read of the user's
        request history, so an unscoped query would surface everyone's.
        """
        models = self.session.scalars(
            select(AgentRunModel)
            .where(AgentRunModel.user_id == user_id.value)
            .order_by(AgentRunModel.created_at.desc())
            .limit(limit)
        ).all()
        return [agent_run_from_model(model) for model in models]

    def list_by_conversation(
        self, conversation_id: EntityId, user_id: EntityId
    ) -> list[AgentRun]:
        """The conversation's runs oldest first, scoped to ``user_id``.

        A conversation id arrives from the URL, so the owner filter is what
        keeps the thread of one user from being read by another. Ordered
        ascending because the caller replays the exchanges in the order they
        happened.
        """
        models = self.session.scalars(
            select(AgentRunModel)
            .where(
                AgentRunModel.conversation_id == conversation_id.value,
                AgentRunModel.user_id == user_id.value,
            )
            .order_by(AgentRunModel.created_at.asc())
        ).all()
        return [agent_run_from_model(model) for model in models]