from dataclasses import dataclass

from app.domain.entities.execution_plan import ExecutionPlan
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.execution_plan_repository import ExecutionPlanRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class CreateExecutionPlanUseCase:
    agent_run_repository: AgentRunRepository
    execution_plan_repository: ExecutionPlanRepository

    def execute(self, agent_run_id: EntityId, user_id: EntityId) -> ExecutionPlan:
        """Attach a plan to a run, provided the caller owns that run.

        A plan is the executable form of somebody's request. Creating one against
        a run you do not own would let you express intent on their behalf, so the
        existence check is owner-scoped rather than a bare lookup.
        """
        if self.agent_run_repository.get_by_id(agent_run_id, user_id) is None:
            raise ValueError("agent run not found")
        plan = ExecutionPlan(agent_run_id=agent_run_id)
        return self.execution_plan_repository.save(plan)
