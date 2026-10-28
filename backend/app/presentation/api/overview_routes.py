"""Dashboard overview endpoint.

A single read that answers "what is happening right now" for the control center:
system health, the active model, the trust posture, the caller's runs, and any
authorizations waiting on them. It is assembled from repositories the API
already owns rather than a new projection table, because every source is cheap
and per-user scoped.

Two deliberate properties:

* **Owner-scoped.** Runs and authorizations are filtered by the resolved
  identity. A dashboard is a view of *your* work, so an unscoped aggregation
  would be a disclosure, not a convenience.
* **Degradation is reported, not hidden.** If the database is unreachable the
  read-only sections come back empty and ``system.database`` reads ``down``.
  The endpoint still serves health and model state, so the UI can render a
  useful page while the datastore is being restored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config.settings import Settings
from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.infrastructure.persistence.database import is_database_available
from app.presentation.dependencies.identity import current_user_id
from app.presentation.dependencies.overview import (
    get_overview_agent_repository,
    get_overview_agent_run_repository,
    get_overview_permission_repository,
    get_overview_permission_request_repository,
)
from app.presentation.dependencies.settings import get_effective_settings
from app.presentation.schemas.overview import (
    ActiveRunsView,
    AgentRunView,
    AgentView,
    AuthorizationView,
    AuthorizationsView,
    ModelView,
    OverviewResponse,
    RuntimeView,
    SystemHealthView,
    TrustView,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["overview"])

#: Captured once at import so uptime is process uptime, not time since the first
#: request. Good enough for an operator dashboard and honest about its meaning.
_STARTED_AT = datetime.now(timezone.utc)

#: A run in any other state is still moving work; these four have stopped.
_TERMINAL_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.BLOCKED,
        AgentRunStatus.CANCELLED,
    }
)

_RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _iso(value: datetime) -> str:
    """Serialise a timestamp as UTC-aware ISO-8601.

    A naive value is assumed to be UTC rather than left bare: the browser parses
    an offset-less string as local time, which would make "waiting 4m" wrong by
    the caller's timezone offset.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _safe(read, default):
    """Run a repository read, degrading to ``default`` if the store is down.

    The overview must not 500 because Postgres blinked; the UI shows an empty
    section and the health field says why.
    """
    try:
        return read()
    except Exception:  # noqa: BLE001 - the point is to survive any storage fault
        logger.warning("overview: a section could not be read", exc_info=True)
        return default


def _run_view(run: AgentRun) -> AgentRunView:
    """The dashboard's projection of a run, shared by the active and recent lists."""
    return AgentRunView(
        run_id=str(run.id),
        status=run.status.value,
        user_request=run.user_request,
        created_at=_iso(run.created_at),
        updated_at=_iso(run.updated_at),
    )


def _risk_sort_key(request) -> tuple[int, float]:
    created = request.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (_RISK_ORDER.get(request.risk_level.value, 3), -created.timestamp())


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    settings: Settings = Depends(get_effective_settings),
    agent_run_repository=Depends(get_overview_agent_run_repository),
    agent_repository=Depends(get_overview_agent_repository),
    permission_repository=Depends(get_overview_permission_repository),
    permission_request_repository=Depends(get_overview_permission_request_repository),
    user_id: EntityId = Depends(current_user_id),
) -> OverviewResponse:
    database_up = _safe(is_database_available, False)

    runs: list[AgentRun] = _safe(
        lambda: agent_run_repository.list_by_user(user_id, limit=50), []
    )
    active_runs = [run for run in runs if run.status not in _TERMINAL_RUN_STATUSES]

    grants = _safe(lambda: permission_repository.list_all(), [])
    own_grants = [grant for grant in grants if grant.user_id == user_id]

    requests = _safe(lambda: permission_request_repository.list_all(), [])
    pending = [
        request
        for request in requests
        if request.status == PermissionRequestStatus.PENDING
        and request.user_id == user_id
        and not request.is_expired()
    ]
    pending.sort(key=_risk_sort_key)

    agents = _safe(lambda: agent_repository.list_by_user(user_id), [])
    active_agent = next(
        (agent for agent in agents if agent.status is AgentStatus.ACTIVE), None
    )

    runtime = await _runtime_view()

    return OverviewResponse(
        system=SystemHealthView(
            status="ok" if database_up else "degraded",
            database="up" if database_up else "down",
            environment=settings.environment,
            uptime_seconds=max(0, int((datetime.now(timezone.utc) - _STARTED_AT).total_seconds())),
        ),
        model=ModelView(
            provider="nebius",
            model=settings.nebius_model,
            configured=bool(settings.nebius_api_key and settings.nebius_model),
        ),
        runtime=runtime,
        trust=TrustView(
            default_decision=settings.trust_default_decision,
            allow_grants=sum(1 for g in own_grants if g.effect is PermissionDecision.ALLOW),
            ask_grants=sum(1 for g in own_grants if g.effect is PermissionDecision.ASK),
            deny_grants=sum(1 for g in own_grants if g.effect is PermissionDecision.DENY),
            total_grants=len(own_grants),
        ),
        runs=ActiveRunsView(
            active_count=len(active_runs),
            items=[_run_view(run) for run in active_runs[:10]],
            # The repository already returns the owner's runs newest-first, so
            # this is a slice of the same read the active list comes from.
            recent=[_run_view(run) for run in runs[:20]],
        ),
        authorizations=AuthorizationsView(
            pending_count=len(pending),
            items=[
                AuthorizationView(
                    request_id=str(request.id),
                    agent_run_id=str(request.agent_run_id),
                    tool_name=request.tool_name,
                    skill_name=request.skill_name,
                    reason=request.reason,
                    risk_level=request.risk_level.value,
                    created_at=_iso(request.created_at),
                    expires_at=_iso(request.expires_at),
                )
                for request in pending[:10]
            ],
        ),
        agent=AgentView(id=str(active_agent.id), name=active_agent.name)
        if active_agent is not None
        else None,
    )


async def _runtime_view() -> RuntimeView:
    """Report the configured runtime without making the overview depend on it.

    Building the runtime is where a misconfigured provider fails, so a failure is
    reported as unavailable rather than propagated -- the rest of the dashboard
    is still worth serving.
    """
    try:
        from app.presentation.dependencies.runtime import build_runtime_service

        health = await build_runtime_service().health()
        return RuntimeView(
            available=health.available,
            provider=health.provider.value,
            detail=health.detail,
        )
    except Exception:  # noqa: BLE001 - a broken runtime must not break the page
        logger.warning("overview: runtime health could not be read", exc_info=True)
        return RuntimeView(available=False, provider="unknown", detail="unavailable")
