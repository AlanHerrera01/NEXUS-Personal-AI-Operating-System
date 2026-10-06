from dataclasses import dataclass

from app.domain.entities.execution_plan import ExecutionPlan
from app.domain.entities.plan_step import PlanStep
from app.domain.repositories.execution_plan_repository import ExecutionPlanRepository
from app.domain.value_objects.entity_id import EntityId


@dataclass
class AddPlanStepUseCase:
    execution_plan_repository: ExecutionPlanRepository

    def execute(self, plan_id: EntityId, step: PlanStep) -> ExecutionPlan:
        plan = self.execution_plan_repository.get_by_id(plan_id)
        if plan is None:
            raise ValueError("execution plan not found")
        plan.add_step(step)
        return self.execution_plan_repository.save(plan)
