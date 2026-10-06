from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel


@dataclass
class AgentAction:
    agent_run_id: EntityId
    skill_name: str
    action_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: EntityId = field(default_factory=EntityId.new)
    status: AgentActionStatus = AgentActionStatus.PROPOSED
    created_at: datetime = field(default_factory=utc_now)
    risk_level: RiskLevel = RiskLevel.LOW
    permission_decision: PermissionDecision | None = None
    policy_result: str | None = None
    execution_status: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        require_text(self.skill_name, "skill_name")
        require_text(self.action_name, "action_name")

    def transition_to(self, status: AgentActionStatus) -> None:
        allowed = {
            AgentActionStatus.PROPOSED: {AgentActionStatus.APPROVED, AgentActionStatus.BLOCKED},
            AgentActionStatus.APPROVED: {AgentActionStatus.EXECUTING, AgentActionStatus.BLOCKED},
            AgentActionStatus.EXECUTING: {
                AgentActionStatus.COMPLETED,
                AgentActionStatus.FAILED,
                AgentActionStatus.BLOCKED,
            },
            AgentActionStatus.COMPLETED: set(),
            AgentActionStatus.FAILED: set(),
            AgentActionStatus.BLOCKED: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid agent action transition: {self.status} -> {status}")
        self.status = status
