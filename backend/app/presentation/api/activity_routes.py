"""Activity / audit feed.

`GET /api/v1/activity` answers "what happened, and what did NEXUS decide about
it" for the operator. There is no single audit table in this codebase, so the
endpoint merges the owner-scoped sources the backend already keeps:

* the in-memory :class:`SecurityAuditLog` -- the Trust Engine's own decisions;
* persisted permission requests -- human approvals and their outcomes;
* persisted agent runs -- the lifecycle of the caller's work;
* persisted agent actions -- tool invocations and how they ended;
* persisted memories -- what the system chose to remember.

Four properties are deliberate.

**Owner-scoped.** Every persisted source is filtered by the resolved identity,
and the in-memory audit entries are filtered to the caller's (or ownerless,
process-level) records. A feed of "what everyone did" would be a disclosure, not
a convenience.

**Degradation is reported, not hidden.** Each source read degrades to empty if
the store is unreachable and ``storage_available`` goes false; the in-memory
audit trail still serves, because it never touched the database.

**Nothing is computed that is not measured.** There is no latency, token or
payload-size telemetry here, because the backend records none; those cells are
absent from the model rather than populated with a plausible number.

**A denial is an event.** ``DENIED`` is a first-class outcome with its cause, so
a brake that fired can be found by looking, not by inferring.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.application.security.audit import AuditEntry, SecurityAuditLog
from app.config.settings import get_settings
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.memory import Memory
from app.domain.entities.permission_request import PermissionRequest
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.infrastructure.persistence.database import is_database_available
from app.presentation.dependencies.activity import (
    get_activity_action_repository,
    get_activity_agent_run_repository,
    get_activity_memory_repository,
    get_activity_permission_request_repository,
)
from app.presentation.dependencies.identity import current_user_id
from app.presentation.dependencies.security import get_security_audit
from app.presentation.schemas.activity import (
    ActivityCategoryCount,
    ActivityEventView,
    ActivityResponse,
    ActivitySummaryView,
    AuditTrailView,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["activity"])

# -- categories -------------------------------------------------------------

TOOL = "TOOL"
TRUST = "TRUST"
MEMORY = "MEMORY"
RUN = "RUN"
SYSTEM = "SYSTEM"

_CATEGORY_LABELS: dict[str, str] = {
    TOOL: "Herramientas",
    TRUST: "Trust Engine",
    MEMORY: "Memoria Vectorial",
    RUN: "Runs",
    SYSTEM: "Sistema",
}
_CATEGORY_ORDER = (TOOL, TRUST, MEMORY, RUN, SYSTEM)

# -- outcomes ---------------------------------------------------------------

SUCCESS = "SUCCESS"
DENIED = "DENIED"
PENDING = "PENDING"
ERROR = "ERROR"
INFO = "INFO"

# -- windows ----------------------------------------------------------------

_WINDOWS = ("today", "24h", "7d", "all")
_DEFAULT_WINDOW = "24h"

# -- audit event mapping ----------------------------------------------------

#: Every ``AuthorizationEventType`` the orchestrator and middleware can emit,
#: mapped to the feed category and outcome it represents. Unknown (future) event
#: names fall back to SYSTEM/INFO rather than being dropped, so a new decision
#: type shows up in the feed the day it starts being recorded.
_AUDIT_META: dict[str, tuple[str, str]] = {
    "TOOL_ALLOWED": (TRUST, SUCCESS),
    "TOOL_DENIED": (TRUST, DENIED),
    "PERMISSION_DENIED": (TRUST, DENIED),
    "PERMISSION_GRANTED": (TRUST, SUCCESS),
    "PERMISSION_REVOKED": (TRUST, DENIED),
    "PERMISSION_REQUESTED": (TRUST, PENDING),
    "PERMISSION_APPROVED": (TRUST, SUCCESS),
    "PERMISSION_REJECTED": (TRUST, DENIED),
    "PERMISSION_EXPIRED": (TRUST, INFO),
    "APPROVAL_OVERRULED": (TRUST, DENIED),
    "UNAUTHORIZED_RESOURCE": (TRUST, DENIED),
    "TRUST_ENGINE_BYPASS_ATTEMPT": (TRUST, DENIED),
    "SUSPICIOUS_AGENT_LOOP": (TRUST, DENIED),
    "PLAN_REJECTED": (TRUST, DENIED),
    "MEMORY_POISONING_DETECTED": (MEMORY, DENIED),
    "PROMPT_INJECTION_DETECTED": (SYSTEM, DENIED),
    "SECRET_DETECTED": (SYSTEM, DENIED),
    "INVALID_WEBHOOK": (SYSTEM, ERROR),
    "RATE_LIMIT_EXCEEDED": (SYSTEM, ERROR),
    "UNTRUSTED_MCP_OUTPUT": (SYSTEM, DENIED),
}

_AUDIT_TITLES: dict[str, str] = {
    "TOOL_ALLOWED": "Herramienta autorizada por el Trust Engine",
    "TOOL_DENIED": "Herramienta denegada por el Trust Engine",
    "PERMISSION_DENIED": "Permiso denegado",
    "PERMISSION_GRANTED": "Permiso concedido",
    "PERMISSION_REVOKED": "Permiso revocado",
    "PERMISSION_REQUESTED": "Aprobación humana solicitada",
    "PERMISSION_APPROVED": "Aprobación humana concedida",
    "PERMISSION_REJECTED": "Aprobación humana rechazada",
    "PERMISSION_EXPIRED": "Solicitud de aprobación expirada",
    "APPROVAL_OVERRULED": "Aprobación anulada por la política vigente",
    "UNAUTHORIZED_RESOURCE": "Acceso a recurso no autorizado",
    "TRUST_ENGINE_BYPASS_ATTEMPT": "Intento de elusión del Trust Engine",
    "SUSPICIOUS_AGENT_LOOP": "Bucle de agente sospechoso",
    "PLAN_REJECTED": "Plan rechazado por política",
    "MEMORY_POISONING_DETECTED": "Envenenamiento de memoria detectado",
    "PROMPT_INJECTION_DETECTED": "Inyección de prompt detectada",
    "SECRET_DETECTED": "Secreto detectado y bloqueado",
    "INVALID_WEBHOOK": "Webhook inválido",
    "RATE_LIMIT_EXCEEDED": "Límite de peticiones excedido",
    "UNTRUSTED_MCP_OUTPUT": "Salida MCP no confiable",
}

# -- action / run mapping ---------------------------------------------------

_ACTION_OUTCOME: dict[AgentActionStatus, str] = {
    AgentActionStatus.COMPLETED: SUCCESS,
    AgentActionStatus.FAILED: ERROR,
    AgentActionStatus.BLOCKED: DENIED,
    AgentActionStatus.APPROVED: PENDING,
    AgentActionStatus.EXECUTING: PENDING,
    AgentActionStatus.PROPOSED: PENDING,
}

_ACTION_TITLES: dict[AgentActionStatus, str] = {
    AgentActionStatus.COMPLETED: "Herramienta ejecutada",
    AgentActionStatus.FAILED: "Herramienta falló",
    AgentActionStatus.BLOCKED: "Herramienta bloqueada",
    AgentActionStatus.APPROVED: "Herramienta aprobada",
    AgentActionStatus.EXECUTING: "Herramienta en ejecución",
    AgentActionStatus.PROPOSED: "Herramienta propuesta",
}

_TERMINAL_RUNS = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.BLOCKED,
        AgentRunStatus.CANCELLED,
    }
)

_RUN_OUTCOME: dict[AgentRunStatus, str] = {
    AgentRunStatus.COMPLETED: SUCCESS,
    AgentRunStatus.FAILED: ERROR,
    AgentRunStatus.BLOCKED: DENIED,
    AgentRunStatus.CANCELLED: INFO,
    AgentRunStatus.CREATED: PENDING,
    AgentRunStatus.CONTEXT_LOADING: PENDING,
    AgentRunStatus.PLANNING: PENDING,
    AgentRunStatus.WAITING_PERMISSION: PENDING,
    AgentRunStatus.EXECUTING: PENDING,
    AgentRunStatus.OBSERVING: PENDING,
}

_RUN_TITLES: dict[AgentRunStatus, str] = {
    AgentRunStatus.COMPLETED: "Run completado",
    AgentRunStatus.FAILED: "Run fallido",
    AgentRunStatus.BLOCKED: "Run bloqueado por política",
    AgentRunStatus.CANCELLED: "Run cancelado",
}

_PERMISSION_OUTCOME: dict[PermissionRequestStatus, str] = {
    PermissionRequestStatus.PENDING: PENDING,
    PermissionRequestStatus.APPROVED: SUCCESS,
    PermissionRequestStatus.REJECTED: DENIED,
    PermissionRequestStatus.EXPIRED: INFO,
    PermissionRequestStatus.CANCELLED: INFO,
}

_PERMISSION_TITLES: dict[PermissionRequestStatus, str] = {
    PermissionRequestStatus.PENDING: "Aprobación humana solicitada",
    PermissionRequestStatus.APPROVED: "Aprobación humana concedida",
    PermissionRequestStatus.REJECTED: "Aprobación humana rechazada",
    PermissionRequestStatus.EXPIRED: "Solicitud de aprobación expirada",
    PermissionRequestStatus.CANCELLED: "Solicitud de aprobación cancelada",
}

#: Per-source read caps. Generous enough that the whole recent window is counted
#: in the summary, bounded enough that a decade of rows does not get loaded to
#: render one screen.
_SOURCE_LIMIT = 200


def _aware(value: datetime) -> datetime:
    """Assume UTC for a naive timestamp instead of leaking local-time guesses.

    A naive value reaching the browser is parsed as local time, which would make
    every "hace 3m" wrong by the caller's offset. Postgres returns aware values;
    SQLite (tests) does not.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _safe(read, default, *, failures: list[str] | None = None, label: str = ""):
    """Read a section, or fall back to ``default`` when it cannot be read.

    ``failures`` collects the labels of the sections that raised, so the caller
    can report the store as unavailable instead of presenting a partial feed as
    a complete one.
    """
    try:
        return read()
    except Exception:  # noqa: BLE001 - a blinking store must not 500 the feed
        logger.warning("activity: a section could not be read", exc_info=True)
        if failures is not None:
            failures.append(label or "section")
        return default


def _window_start(window: str, now: datetime) -> datetime | None:
    if window == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "24h":
        return now - timedelta(hours=24)
    if window == "7d":
        return now - timedelta(days=7)
    return None


def _density(stamps: list[datetime], *, now: datetime, window: str) -> tuple[list[int], int, int]:
    """Bucket event timestamps into a sparkline.

    Only the buckets a real event fell into are ever non-zero, so a straight line
    means "nothing happened", which is the correct thing to show.
    """
    if window in ("today", "24h"):
        bucket, count = 3600, 24
    elif window == "7d":
        bucket, count = 86400, 7
    else:
        if not stamps:
            return [], 0, 3600
        span = (now - min(stamps)).total_seconds()
        if span <= 48 * 3600:
            bucket = 3600
            count = max(1, min(48, int(span // bucket) + 1))
        else:
            bucket = 86400
            count = max(1, min(30, int(span // bucket) + 1))

    buckets = [0] * count
    start = now.timestamp() - bucket * count
    for stamp in stamps:
        index = int((stamp.timestamp() - start) // bucket)
        if 0 <= index < count:
            buckets[index] += 1
    return buckets, max(buckets, default=0), bucket


# -- event builders ---------------------------------------------------------


def _audit_events(
    entries: tuple[AuditEntry, ...], user: EntityId
) -> tuple[list[tuple[datetime, ActivityEventView]], int]:
    """Build the Trust Engine / security feed from the in-memory ring.

    Ownerless entries are included: on a deployment without auth these are
    process-level events (rate limiting) that belong to the single operator, and
    they carry no payload or identity of anyone else.
    """
    pairs: list[tuple[datetime, ActivityEventView]] = []
    visible = 0
    owner = str(user)
    for index, entry in enumerate(entries):
        if entry.user_id is not None and entry.user_id != owner:
            continue
        visible += 1
        name = str(entry.event)
        category, outcome = _AUDIT_META.get(name, (SYSTEM, INFO))
        title = _AUDIT_TITLES.get(name, name.replace("_", " ").capitalize())
        stamp = _aware(entry.timestamp)
        pairs.append(
            (
                stamp,
                ActivityEventView(
                    id=f"audit:{index}",
                    timestamp=_iso(stamp),
                    category=category,
                    kind=name,
                    outcome=outcome,
                    title=title,
                    detail=entry.reason or "",
                    source=entry.tool_name,
                    reference=entry.action_name,
                    agent_run_id=entry.agent_run_id,
                    risk_level=entry.risk_level,
                    decision=entry.decision,
                    payload={k: v for k, v in entry.as_dict().items() if v is not None},
                ),
            )
        )
    return pairs, visible


def _action_events(actions: list[AgentAction]) -> list[tuple[datetime, ActivityEventView]]:
    pairs: list[tuple[datetime, ActivityEventView]] = []
    for action in actions:
        status = action.status
        stamp = _aware(action.created_at)
        detail = action.error_message or action.policy_result or action.execution_status or ""
        pairs.append(
            (
                stamp,
                ActivityEventView(
                    id=f"action:{action.id}",
                    timestamp=_iso(stamp),
                    category=TOOL,
                    kind=f"ACTION_{status.value}",
                    outcome=_ACTION_OUTCOME.get(status, INFO),
                    title=_ACTION_TITLES.get(status, "Herramienta"),
                    detail=detail,
                    source=action.skill_name,
                    reference=action.action_name,
                    agent_run_id=str(action.agent_run_id),
                    risk_level=action.risk_level.value if action.risk_level else None,
                    decision=(
                        action.permission_decision.value if action.permission_decision else None
                    ),
                    payload={
                        "skill": action.skill_name,
                        "action": action.action_name,
                        "status": status.value,
                        "arguments": action.arguments,
                        "policy_result": action.policy_result,
                        "execution_status": action.execution_status,
                        "error_message": action.error_message,
                    },
                ),
            )
        )
    return pairs


def _permission_events(
    requests: list[PermissionRequest],
) -> list[tuple[datetime, ActivityEventView]]:
    pairs: list[tuple[datetime, ActivityEventView]] = []
    for request in requests:
        status = request.status
        # A pending request is timestamped when it was asked; a resolved one when
        # it was decided, so the feed shows the moment that matters.
        stamp = _aware(request.created_at if status is PermissionRequestStatus.PENDING else request.updated_at)
        pairs.append(
            (
                stamp,
                ActivityEventView(
                    id=f"permission:{request.id}",
                    timestamp=_iso(stamp),
                    category=TRUST,
                    kind=f"PERMISSION_{status.value}",
                    outcome=_PERMISSION_OUTCOME.get(status, INFO),
                    title=_PERMISSION_TITLES.get(status, "Solicitud de aprobación"),
                    detail=request.reason,
                    source=request.skill_name,
                    reference=request.tool_name,
                    agent_run_id=str(request.agent_run_id),
                    risk_level=request.risk_level.value,
                    decision="ASK" if status is PermissionRequestStatus.PENDING else None,
                    payload={
                        "tool": request.tool_name,
                        "skill": request.skill_name,
                        "status": status.value,
                        "risk_level": request.risk_level.value,
                        "reason": request.reason,
                        "arguments_summary": request.arguments_summary,
                        "expires_at": _iso(request.expires_at),
                        # Only meaningful while the request is still resolvable.
                        "resolvable": status is PermissionRequestStatus.PENDING
                        and not request.is_expired(),
                    },
                ),
            )
        )
    return pairs


def _run_events(runs: list[AgentRun]) -> list[tuple[datetime, ActivityEventView]]:
    pairs: list[tuple[datetime, ActivityEventView]] = []
    for run in runs:
        status = run.status
        terminal = status in _TERMINAL_RUNS
        created = _aware(run.created_at)
        pairs.append(
            (
                created,
                ActivityEventView(
                    id=f"run:{run.id}:start",
                    timestamp=_iso(created),
                    category=RUN,
                    kind="RUN_STARTED",
                    outcome=INFO,
                    title="Run iniciado",
                    detail=run.user_request,
                    source="orchestrator",
                    reference=str(run.id),
                    agent_run_id=str(run.id),
                    payload={"status": status.value, "user_request": run.user_request},
                ),
            )
        )
        updated = _aware(run.updated_at)
        if updated <= created:
            continue
        if terminal:
            pairs.append(
                (
                    updated,
                    ActivityEventView(
                        id=f"run:{run.id}:end",
                        timestamp=_iso(updated),
                        category=RUN,
                        kind=f"RUN_{status.value}",
                        outcome=_RUN_OUTCOME.get(status, INFO),
                        title=_RUN_TITLES.get(status, f"Run {status.value}"),
                        detail=run.user_request,
                        source="orchestrator",
                        reference=str(run.id),
                        agent_run_id=str(run.id),
                        payload={"status": status.value, "user_request": run.user_request},
                    ),
                )
            )
        else:
            pairs.append(
                (
                    updated,
                    ActivityEventView(
                        id=f"run:{run.id}:update",
                        timestamp=_iso(updated),
                        category=RUN,
                        kind=f"RUN_{status.value}",
                        outcome=PENDING,
                        title=f"Run en curso · {status.value}",
                        detail=run.user_request,
                        source="orchestrator",
                        reference=str(run.id),
                        agent_run_id=str(run.id),
                        payload={"status": status.value, "user_request": run.user_request},
                    ),
                )
            )
    return pairs


def _memory_events(memories: list[Memory]) -> list[tuple[datetime, ActivityEventView]]:
    pairs: list[tuple[datetime, ActivityEventView]] = []
    for memory in memories:
        stamp = _aware(memory.created_at)
        preview = memory.content if len(memory.content) <= 220 else memory.content[:219] + "…"
        pairs.append(
            (
                stamp,
                ActivityEventView(
                    id=f"memory:{memory.id}",
                    timestamp=_iso(stamp),
                    category=MEMORY,
                    kind="MEMORY_SAVED",
                    outcome=SUCCESS,
                    title="Memoria persistida",
                    detail=preview,
                    source=memory.source.value,
                    reference=memory.memory_type.value,
                    agent_run_id=str(memory.agent_id) if memory.agent_id else None,
                    payload={
                        "memory_type": memory.memory_type.value,
                        "importance": memory.importance.value,
                        "source": memory.source.value,
                        "persistence": memory.persistence.value,
                    },
                ),
            )
        )
    return pairs


@router.get("/activity", response_model=ActivityResponse)
async def get_activity(
    window: str = Query(_DEFAULT_WINDOW, description="today | 24h | 7d | all"),
    limit: int = Query(100, ge=1, le=500),
    agent_run_repository=Depends(get_activity_agent_run_repository),
    action_repository=Depends(get_activity_action_repository),
    permission_request_repository=Depends(get_activity_permission_request_repository),
    memory_repository=Depends(get_activity_memory_repository),
    audit_log: SecurityAuditLog = Depends(get_security_audit),
    user_id: EntityId = Depends(current_user_id),
) -> ActivityResponse:
    selected = window if window in _WINDOWS else _DEFAULT_WINDOW
    now = datetime.now(timezone.utc)
    since = _window_start(selected, now)

    # A section that fails is reported, not hidden. If the store could not
    # answer, the feed is the audit trail and nothing else -- claiming
    # ``storage_available`` there would dress an incomplete view up as a whole
    # one, which is exactly the kind of quiet lie this screen exists to avoid.
    unreadable: list[str] = []

    runs: list[AgentRun] = _safe(
        lambda: agent_run_repository.list_by_user(user_id, limit=_SOURCE_LIMIT),
        [],
        failures=unreadable,
        label="agent_runs",
    )
    actions: list[AgentAction] = _safe(
        lambda: action_repository.list_recent_for_user(user_id, limit=_SOURCE_LIMIT),
        [],
        failures=unreadable,
        label="actions",
    )
    requests_all: list[PermissionRequest] = _safe(
        lambda: permission_request_repository.list_all(),
        [],
        failures=unreadable,
        label="permission_requests",
    )
    requests = [request for request in requests_all if request.user_id == user_id]
    memories: list[Memory] = _safe(
        lambda: memory_repository.list_by_user(user_id, limit=_SOURCE_LIMIT),
        [],
        failures=unreadable,
        label="memories",
    )

    storage_available = _safe(is_database_available, False) and not unreadable

    audit_pairs, audit_visible = _audit_events(audit_log.entries(), user_id)

    pairs: list[tuple[datetime, ActivityEventView]] = []
    pairs.extend(audit_pairs)
    pairs.extend(_action_events(actions))
    pairs.extend(_permission_events(requests))
    pairs.extend(_run_events(runs))
    pairs.extend(_memory_events(memories))

    if since is not None:
        pairs = [(stamp, event) for stamp, event in pairs if stamp >= since]
    pairs.sort(key=lambda pair: pair[0], reverse=True)

    total = len(pairs)
    truncated = total > limit
    events = [event for _, event in pairs[:limit]]

    summary = _summarize(pairs, now=now, window=selected)
    capacity = get_settings().security_audit_capacity

    return ActivityResponse(
        generated_at=_iso(now),
        window=selected,
        storage_available=storage_available,
        truncated=truncated,
        events=events,
        summary=summary,
        audit=AuditTrailView(
            persisted=False,
            retention_capacity=capacity,
            retained_entries=len(audit_log),
            visible_entries=audit_visible,
            note=(
                "Traza de autorización en memoria: acotada y se reinicia con el "
                "proceso. Es una ayuda operativa, no un archivo de cumplimiento."
            ),
        ),
    )


def _summarize(
    pairs: list[tuple[datetime, ActivityEventView]], *, now: datetime, window: str
) -> ActivitySummaryView:
    counts = {SUCCESS: 0, DENIED: 0, PENDING: 0, ERROR: 0, INFO: 0}
    categories = {name: 0 for name in _CATEGORY_ORDER}
    stamps: list[datetime] = []

    for stamp, event in pairs:
        counts[event.outcome] = counts.get(event.outcome, 0) + 1
        if event.category in categories:
            categories[event.category] += 1
        stamps.append(stamp)

    resolved = counts[SUCCESS] + counts[DENIED] + counts[ERROR]
    success_rate = (counts[SUCCESS] / resolved) if resolved else None
    density, peak, bucket = _density(stamps, now=now, window=window)

    return ActivitySummaryView(
        total=len(pairs),
        success=counts[SUCCESS],
        denied=counts[DENIED],
        pending=counts[PENDING],
        error=counts[ERROR],
        info=counts[INFO],
        resolved=resolved,
        success_rate=success_rate,
        categories=[
            ActivityCategoryCount(
                category=name, label=_CATEGORY_LABELS[name], count=categories[name]
            )
            for name in _CATEGORY_ORDER
        ],
        density=density,
        density_peak=peak,
        bucket_seconds=bucket,
    )
