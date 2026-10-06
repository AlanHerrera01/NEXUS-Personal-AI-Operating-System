from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel


@dataclass
class Permission:
    user_id: EntityId
    agent_id: EntityId
    skill_name: str
    action_name: str
    scope: str
    effect: PermissionDecision
    risk_level: RiskLevel = RiskLevel.LOW
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    #: Stable identity of the grant itself. The table has had an ``id``
    #: primary key all along, but the entity did not carry it -- which is why
    #: the revoke endpoint had to invent a ``"skill:action"`` string format and
    #: pass ``EntityId("dummy")`` as the agent to delete by composite key. With
    #: an id, revocation addresses one specific row the caller was shown, instead
    #: of reconstructing a key that may match several rows or none.
    id: EntityId = field(default_factory=EntityId.new)

    def __post_init__(self) -> None:
        require_text(self.skill_name, "skill_name")
        require_text(self.action_name, "action_name")
        require_text(self.scope, "scope")

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return utc_now() > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_expired()
