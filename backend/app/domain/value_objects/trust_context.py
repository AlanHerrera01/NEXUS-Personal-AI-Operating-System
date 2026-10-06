from dataclasses import dataclass, field
from typing import Any

from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel


@dataclass(frozen=True)
class TrustContext:
    user_id: EntityId | None
    agent_id: EntityId
    agent_run_id: EntityId
    tool_name: str
    skill_name: str
    risk_level: RiskLevel
    read_only: bool
    side_effect: bool
    arguments: dict[str, Any] = field(default_factory=dict)
    current_permissions: frozenset[str] = frozenset()
    tool_metadata: dict[str, Any] = field(default_factory=dict)
