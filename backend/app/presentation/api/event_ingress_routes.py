"""The external event ingress.

This is the only endpoint in the codebase that asks a caller to prove something,
and it does so with a shared secret compared in constant time. Everything else
about the request is untrusted input that gets validated as data.

Three things are worth stating plainly, because "webhook endpoint" is exactly the
kind of phrase that hides these:

* the secret authenticates the *caller* to this deployment. It does not
  authenticate the caller as any particular person, and there is no such thing
  here as "the event's owner". Events are recorded for the single local user.
  A multi-tenant deployment has to solve identity before exposing this.
* with no secret configured every request is refused. There is no default secret
  and no development bypass, because a default secret is a public secret.
* ``event_type`` and ``idempotency_key`` are validated against a strict charset
  before they are stored, and ``payload`` is bounded, so a provider cannot smuggle
  prompt text or unbounded data into an agent request.

Nothing here can cause an action. An accepted event only starts jobs that the
user already created and registered for that event type, and each of those still
goes through the Trust Engine.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.application.always_on.errors import (
    AlwaysOnError,
    EventRateLimited,
    TriggerEventNotFound,
)
from app.application.always_on.job_dispatcher import DispatchOutcomeType
from app.application.always_on.trigger_event_service import TriggerEventService
from app.config.settings import Settings, get_settings
from app.infrastructure.always_on.event_source import (
    INGRESS_HEADER,
    IngressAuthenticator,
)
from app.presentation.dependencies.always_on import (
    get_ingress_authenticator,
    get_trigger_event_service,
)
from app.presentation.dependencies.identity import LOCAL_USER_ID

router = APIRouter(prefix="/api/v1/events", tags=["always-on"])


class TriggerEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=300)
    payload: dict = Field(default_factory=dict)


class TriggerEventResponse(BaseModel):
    event_id: str
    processed: bool
    duplicate: bool
    jobs_matched: int
    jobs_dispatched: int
    error: str | None = None


@router.post(
    "/trigger",
    response_model=TriggerEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_event(
    body: TriggerEventRequest,
    authenticator: IngressAuthenticator = Depends(get_ingress_authenticator),
    service: TriggerEventService = Depends(get_trigger_event_service),
    settings: Settings = Depends(get_settings),
    ingress_secret: str | None = Header(default=None, alias=INGRESS_HEADER),
) -> TriggerEventResponse:
    """Accept an external event and fan it out to matching jobs.

    Returns 202 rather than 200 because dispatch is scheduled, not performed:
    the acceptance that matters has already happened once the event row is
    committed under its idempotency key.
    """
    # Authentication is checked *before* the feature flag, deliberately. The
    # other order answers 503 to an unauthenticated caller, which confirms that
    # an Always-On ingress exists here and is currently switched off -- free
    # reconnaissance about the deployment's configuration, handed to anyone who
    # can reach the port. An unauthenticated caller should learn nothing at all.
    # The same 401 is returned whether the secret is absent or wrong, so the
    # endpoint cannot be used to discover which of the two it was.
    if not authenticator.verify(ingress_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing or invalid {INGRESS_HEADER}",
        )

    if not settings.always_on_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Always-On is disabled in this deployment (always_on_enabled)",
        )

    from app.domain.entities._common import utc_now
    from app.domain.value_objects.entity_id import EntityId

    try:
        outcome = await service.ingest(
            user_id=EntityId(LOCAL_USER_ID),
            source="http-ingress",
            event_type=body.event_type,
            idempotency_key=body.idempotency_key,
            payload=body.payload,
            now=utc_now(),
        )
    except EventRateLimited as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)
        ) from error
    except TriggerEventNotFound as error:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except AlwaysOnError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except ValueError as error:
        # Rejected charset, oversized payload, and similar input validation.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    # A duplicate event is recorded but not re-dispatched; its original row is
    # what gets reported, so a retried webhook delivery gets a stable answer.
    assert outcome.event is not None

    return TriggerEventResponse(
        event_id=str(outcome.event.id),
        processed=outcome.event.processed_at is not None,
        duplicate=outcome.duplicate,
        jobs_matched=outcome.matched_jobs,
        jobs_dispatched=outcome.count(DispatchOutcomeType.DISPATCHED),
        error="; ".join(outcome.errors) or None,
    )