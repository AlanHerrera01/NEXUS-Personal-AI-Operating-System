from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId


@dataclass
class Agent:
    name: str
    description: str = ""
    id: EntityId = field(default_factory=EntityId.new)
    status: AgentStatus = AgentStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    #: Owner. Optional on the entity for the same reason as Memory.user_id: the
    #: column postdates existing rows and the migration backfills them. It is
    #: never None for a row this codebase creates.
    user_id: EntityId | None = None

    def __post_init__(self) -> None:
        require_text(self.name, "name")

    def activate(self) -> None:
        self.status = AgentStatus.ACTIVE
        self.updated_at = utc_now()

    def deactivate(self) -> None:
        self.status = AgentStatus.INACTIVE
        self.updated_at = utc_now()
