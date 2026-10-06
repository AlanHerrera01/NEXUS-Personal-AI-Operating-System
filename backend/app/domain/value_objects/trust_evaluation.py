from dataclasses import dataclass
from typing import Any

from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel


@dataclass(frozen=True)
class TrustEvaluation:
    decision: PermissionDecision
    risk_level: RiskLevel
    reason: str
    policy_id: str | None = None
    requires_confirmation: bool = False
    metadata: dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})
