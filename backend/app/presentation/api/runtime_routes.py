"""Runtime session endpoints.

Deliberately read-mostly and scoped. These routes expose the runtime's own
lifecycle and health; they are not a general shell. Execution still goes through
the orchestrator, which mints the ``ExecutionAuthorization`` this API refuses to
accept from a caller.

.. warning::
   NEXUS has no authentication layer yet, so these endpoints identify nobody.
   Until one exists they must not be exposed beyond a trusted network, and no
   endpoint here may be treated as an access-control boundary. What they *do*
   enforce is that a caller cannot obtain a host filesystem path or influence a
   run's policy.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.application.agent_runtime.service import AgentRuntimeService
from app.domain.entities.runtime_session import RuntimeSession
from app.domain.value_objects.entity_id import EntityId
from app.presentation.dependencies.runtime import build_runtime_service

router = APIRouter(prefix="/api/v1/runtime", tags=["runtime"])


def get_runtime_service() -> AgentRuntimeService:
    return build_runtime_service()


class RuntimeHealthResponse(BaseModel):
    available: bool
    provider: str
    detail: str = ""
    version: str | None = None


class RuntimeSessionResponse(BaseModel):
    id: str
    agent_id: str
    agent_run_id: str
    user_id: str | None
    provider: str
    state: str
    sandbox_id: str | None
    #: Host filesystem paths are deliberately absent from this response. A
    #: session's workspace lives under the server's runtime root, and publishing
    #: it tells a caller the server's directory layout and its run-scoped naming
    #: scheme, which is reconnaissance rather than runtime status. The field is
    #: not replaced by a boolean either: ``workspace_path`` is non-empty by entity
    #: invariant, so such a flag would always read ``true`` and mean nothing.
    created_at: str
    updated_at: str
    expires_at: str
    started_at: str | None
    stopped_at: str | None
    expired: bool
    last_error: str | None
    policy: dict

    @classmethod
    def from_entity(cls, session: RuntimeSession) -> "RuntimeSessionResponse":
        described = session.describe()
        return cls(
            id=described["id"],
            agent_id=described["agent_id"],
            agent_run_id=described["agent_run_id"],
            user_id=described["user_id"],
            provider=described["provider"],
            state=described["state"],
            sandbox_id=described["sandbox_id"],
            created_at=described["created_at"],
            updated_at=described["updated_at"],
            expires_at=described["expires_at"],
            started_at=described["started_at"],
            stopped_at=described["stopped_at"],
            expired=described["expired"],
            last_error=described["last_error"],
            policy=described["policy"],
        )


def _lookup(service: AgentRuntimeService, session_id: str) -> RuntimeSession:
    try:
        entity_id = EntityId.from_string(session_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid session id"
        ) from error
    session = service.session_repository.get_by_id(entity_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="runtime session not found"
        )
    return session


@router.get("/health", response_model=RuntimeHealthResponse)
async def runtime_health(service: AgentRuntimeService = Depends(get_runtime_service)):
    """Reports which runtime is configured and whether it is reachable.

    An unavailable runtime is reported as unavailable, never worked around by
    executing on the host.
    """
    health = await service.health()
    return RuntimeHealthResponse(
        available=health.available,
        provider=health.provider.value,
        detail=health.detail,
        version=health.version,
    )


@router.get("/sessions/{session_id}", response_model=RuntimeSessionResponse)
async def get_runtime_session(
    session_id: str, service: AgentRuntimeService = Depends(get_runtime_service)
):
    return RuntimeSessionResponse.from_entity(_lookup(service, session_id))


@router.get("/agent-runs/{agent_run_id}/runtime", response_model=RuntimeSessionResponse)
async def get_run_runtime(
    agent_run_id: str, service: AgentRuntimeService = Depends(get_runtime_service)
):
    try:
        run_id = EntityId.from_string(agent_run_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid agent run id"
        ) from error
    session = await service.get_session_for_run(run_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no runtime for this agent run"
        )
    return RuntimeSessionResponse.from_entity(session)


@router.post("/agent-runs/{agent_run_id}/runtime/stop", response_model=RuntimeSessionResponse)
async def stop_run_runtime(
    agent_run_id: str, service: AgentRuntimeService = Depends(get_runtime_service)
):
    """Tear down the runtime belonging to an agent run.

    Keyed by ``agent_run_id`` rather than a caller-supplied sandbox id, so the
    route cannot be pointed at an arbitrary sandbox by guessing a name. That is
    the only scoping guarantee here: with no authentication layer it is *not* an
    access-control boundary. The workspace is kept by default, since deleting a
    run's files is a separate, explicit decision.
    """
    try:
        run_id = EntityId.from_string(agent_run_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid agent run id"
        ) from error
    session = await service.get_session_for_run(run_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no runtime for this agent run"
        )
    await service.stop_session(session, user_id=session.user_id)
    return RuntimeSessionResponse.from_entity(session)


@router.post("/sessions/{session_id}/stop", response_model=RuntimeSessionResponse)
async def stop_runtime_session(
    session_id: str, service: AgentRuntimeService = Depends(get_runtime_service)
):
    """Stop one session by id and report its resulting state."""
    session = _lookup(service, session_id)
    await service.stop_session(session, user_id=session.user_id)
    return RuntimeSessionResponse.from_entity(session)