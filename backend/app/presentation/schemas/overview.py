"""Read model for the dashboard overview.

Everything here is derived from state the backend already owns -- health, the
configured model, the trust defaults, the caller's runs, grants and pending
authorizations. No field is invented: when a value is not known the view reports
that honestly (``configured: false``, an empty list) rather than a plausible
placeholder, because a dashboard that fabricates telemetry is worse than one
that admits it has none.
"""

from pydantic import BaseModel, Field


class SystemHealthView(BaseModel):
    status: str
    database: str
    environment: str
    uptime_seconds: int


class ModelView(BaseModel):
    provider: str
    model: str
    configured: bool


class RuntimeView(BaseModel):
    available: bool
    provider: str
    detail: str = ""


class TrustView(BaseModel):
    default_decision: str
    allow_grants: int = 0
    ask_grants: int = 0
    deny_grants: int = 0
    total_grants: int = 0


class AgentRunView(BaseModel):
    run_id: str
    status: str
    user_request: str
    created_at: str
    updated_at: str


class ActiveRunsView(BaseModel):
    active_count: int
    items: list[AgentRunView] = Field(default_factory=list)
    #: The owner's most recent runs regardless of state. ``items`` only carries
    #: the ones still in flight, so a dashboard that wants to get back into a
    #: finished run had nothing to list once everything settled.
    recent: list[AgentRunView] = Field(default_factory=list)


class AuthorizationView(BaseModel):
    request_id: str
    agent_run_id: str
    tool_name: str
    skill_name: str
    reason: str
    risk_level: str
    created_at: str
    expires_at: str


class AuthorizationsView(BaseModel):
    pending_count: int
    items: list[AuthorizationView] = Field(default_factory=list)


class AgentView(BaseModel):
    id: str
    name: str


class OverviewResponse(BaseModel):
    system: SystemHealthView
    model: ModelView
    runtime: RuntimeView
    trust: TrustView
    runs: ActiveRunsView
    authorizations: AuthorizationsView
    agent: AgentView | None = None
