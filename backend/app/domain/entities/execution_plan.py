from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import utc_now
from app.domain.entities.plan_step import PlanStep
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.plan_status import PlanStatus


@dataclass
class ExecutionPlan:
    agent_run_id: EntityId
    id: EntityId = field(default_factory=EntityId.new)
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.CREATED
    created_at: datetime = field(default_factory=utc_now)

    def add_step(self, step: PlanStep) -> None:
        if self.status is not PlanStatus.CREATED:
            raise ValueError("steps can only be added to a new plan")
        expected_order = len(self.steps) + 1
        if step.order != expected_order:
            raise ValueError(f"step order must be {expected_order}")
        self.steps.append(step)
