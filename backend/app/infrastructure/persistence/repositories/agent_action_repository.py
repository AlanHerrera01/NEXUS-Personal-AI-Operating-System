from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.agent_action import AgentAction
from app.domain.ports.agent_action_repository import AgentActionRepository
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.persistence.models import AgentActionModel


class SqlAlchemyAgentActionRepository(AgentActionRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, action: AgentAction) -> AgentAction:
        model = self.session.get(AgentActionModel, action.id.value)
        if model is None:
            model = AgentActionModel(
                id=action.id.value,
                agent_run_id=action.agent_run_id.value,
                skill_name=action.skill_name,
                action_name=action.action_name,
                arguments=action.arguments,
                status=action.status.value,
                created_at=action.created_at,
                risk_level=action.risk_level.value if action.risk_level else None,
                permission_decision=action.permission_decision.value if action.permission_decision else None,
                policy_result=action.policy_result,
                execution_status=action.execution_status,
                error_message=action.error_message,
            )
            self.session.add(model)
        else:
            model.status = action.status.value
            model.arguments = action.arguments
            model.risk_level = action.risk_level.value if action.risk_level else None
            model.permission_decision = action.permission_decision.value if action.permission_decision else None
            model.policy_result = action.policy_result
            model.execution_status = action.execution_status
            model.error_message = action.error_message
        self.session.commit()
        return action

    def list_by_run(self, agent_run_id: EntityId) -> list[AgentAction]:
        models = self.session.scalars(
            select(AgentActionModel)
            .where(AgentActionModel.agent_run_id == agent_run_id.value)
            .order_by(AgentActionModel.created_at.asc())
        ).all()
        return [
            AgentAction(
                id=EntityId(model.id),
                agent_run_id=EntityId(model.agent_run_id),
                skill_name=model.skill_name,
                action_name=model.action_name,
                arguments=model.arguments,
                status=AgentActionStatus(model.status),
                created_at=model.created_at,
                risk_level=RiskLevel(model.risk_level) if model.risk_level else RiskLevel.LOW,
                permission_decision=PermissionDecision(model.permission_decision) if model.permission_decision else None,
                policy_result=model.policy_result,
                execution_status=model.execution_status,
                error_message=model.error_message,
            )
            for model in models
        ]
