from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId


@dataclass
class AgentRun:
    agent_id: EntityId
    user_request: str
    id: EntityId = field(default_factory=EntityId.new)
    status: AgentRunStatus = AgentRunStatus.CREATED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    #: Owner of the run. Separate from the agent's owner: sharing an agent does
    #: not mean sharing its runs, and an agent-run resume endpoint that checks
    #: only the agent would hand over the other party's request history.
    user_id: EntityId | None = None
    #: Optional conversation that groups related runs together
    conversation_id: EntityId | None = None
    #: What the agent said when it stopped. Kept on the run rather than only in
    #: the response of the call that produced it, so a run read back later -- a
    #: recent run reopened from the sidebar -- still shows its whole exchange.
    #: ``response`` closes a run; ``question`` is what it parked on.
    response: str | None = None
    question: str | None = None

    def __post_init__(self) -> None:
        require_text(self.user_request, "user_request")

    def set_status(self, status: AgentRunStatus) -> None:
        self.status = status
        self.updated_at = utc_now()
