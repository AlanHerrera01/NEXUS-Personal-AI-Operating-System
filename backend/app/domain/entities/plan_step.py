from dataclasses import dataclass, field
from typing import Any

from app.domain.entities._common import require_text
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.plan_step_status import PlanStepStatus
from app.domain.value_objects.risk_level import RiskLevel


@dataclass
class PlanStep:
    order: int
    skill_name: str
    action_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    id: EntityId = field(default_factory=EntityId.new)
    status: PlanStepStatus = PlanStepStatus.PENDING

    def __post_init__(self) -> None:
        if self.order < 1:
            raise ValueError("order must be greater than zero")
        require_text(self.skill_name, "skill_name")
        require_text(self.action_name, "action_name")

    def transition_to(self, status: PlanStepStatus) -> None:
        if self.status is PlanStepStatus.BLOCKED:
            raise ValueError("a blocked plan step cannot transition")
        allowed = {
            PlanStepStatus.PENDING: {
                PlanStepStatus.WAITING_PERMISSION,
                PlanStepStatus.APPROVED,
                PlanStepStatus.BLOCKED,
            },
            PlanStepStatus.WAITING_PERMISSION: {
                PlanStepStatus.APPROVED,
                PlanStepStatus.BLOCKED,
            },
            PlanStepStatus.APPROVED: {PlanStepStatus.EXECUTING, PlanStepStatus.BLOCKED},
            PlanStepStatus.EXECUTING: {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.FAILED,
                PlanStepStatus.BLOCKED,
            },
            PlanStepStatus.COMPLETED: set(),
            PlanStepStatus.FAILED: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid plan step transition: {self.status} -> {status}")
        self.status = status
