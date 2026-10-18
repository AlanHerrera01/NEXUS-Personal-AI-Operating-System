"""Read model for the activity / audit feed.

The Activity screen is a *merged* view. The backend keeps authorization
decisions, permission requests, runs, tool invocations and memories in five
different places, and none of them alone answers "what happened". This model
joins them into one time-ordered list, owner-scoped to the caller, plus the
summary the telemetry cockpit renders.

Two rules govern what lives here:

* **Only real events.** Every field is derived from a row the backend owns or an
  in-memory audit entry it recorded. Where the backend measures nothing --
  execution latency, payload size, token counts, retention policy -- the field
  simply does not exist, and the UI says so rather than inventing a number.
* **A denial is an event, not a statistic.** A brake that fired is the most
  important thing an audit trail can show, so ``DENIED`` is a first-class
  outcome with a cause attached, not a count folded into a total.
"""

from pydantic import BaseModel, Field


class ActivityEventView(BaseModel):
    """One entry in the merged timeline."""

    #: Stable across polls so React keys and open detail views survive a refresh.
    id: str
    timestamp: str
    #: TOOL | TRUST | MEMORY | RUN | SYSTEM
    category: str
    #: Machine-readable event name (e.g. ``TOOL_DENIED``, ``RUN_COMPLETED``).
    kind: str
    #: SUCCESS | DENIED | PENDING | ERROR | INFO
    outcome: str
    title: str
    detail: str = ""
    #: Where the event came from -- a skill name, a service, a daemon.
    source: str | None = None
    #: The tool/action name or the referenced id.
    reference: str | None = None
    agent_run_id: str | None = None
    risk_level: str | None = None
    decision: str | None = None
    #: Structured detail for the payload inspector. Never fabricated: it is the
    #: fields the source actually recorded.
    payload: dict = Field(default_factory=dict)


class ActivityCategoryCount(BaseModel):
    category: str
    label: str
    count: int


class ActivitySummaryView(BaseModel):
    """Counts over the *whole* selected window, not just the returned page."""

    total: int = 0
    success: int = 0
    denied: int = 0
    pending: int = 0
    error: int = 0
    info: int = 0
    #: Events that reached a verdict (success + denied + error).
    resolved: int = 0
    #: ``success / resolved`` as a fraction, or None when nothing resolved.
    success_rate: float | None = None
    categories: list[ActivityCategoryCount] = Field(default_factory=list)
    #: Event counts per time bucket, oldest first.
    density: list[int] = Field(default_factory=list)
    density_peak: int = 0
    bucket_seconds: int = 3600


class AuditTrailView(BaseModel):
    """The in-memory authorisation ring, described honestly.

    It is bounded and lost on restart, so the UI must not present it as a
    compliance archive. ``retained_entries`` is the whole process ring;
    ``visible_entries`` is how many of those belong to the caller and fall in the
    window.
    """

    persisted: bool = False
    retention_capacity: int = 0
    retained_entries: int = 0
    visible_entries: int = 0
    note: str = ""


class ActivityResponse(BaseModel):
    generated_at: str
    window: str
    storage_available: bool
    #: True when more events exist in the window than ``events`` returned.
    truncated: bool
    events: list[ActivityEventView] = Field(default_factory=list)
    summary: ActivitySummaryView
    audit: AuditTrailView
