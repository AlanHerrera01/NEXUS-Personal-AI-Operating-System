"""Runtime settings endpoint: read the effective configuration, change the safe
subset of it.

What is writable is deliberately narrow. An operator may move the model id, the
generation parameters, the request timeout and a UI notification preference --
the knobs whose worst failure is a bad answer or a slow request.

Everything else is reported and not settable. The provider's API key and base
URL are not reachable from HTTP: a panel that could repoint the model endpoint
would turn a convenience screen into an exfiltration primitive. The trust
posture and the memory firewall are likewise read-only, because a switch that
could turn either off would be a way to disable the security model from the UI
rather than from the deployment's environment, where the person responsible for
it can see the change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.settings.service import (
    RuntimeSettingsService,
    RuntimeSettingsSnapshot,
    SettingsStorageError,
)
from app.config.settings import Settings, get_settings
from app.presentation.dependencies.settings import get_runtime_settings_service
from app.presentation.schemas.settings import (
    ProviderView,
    SettingsResponse,
    SettingsUpdateRequest,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _response(snapshot: RuntimeSettingsSnapshot, settings: Settings) -> SettingsResponse:
    values = snapshot.effective
    return SettingsResponse(
        model=str(values["model"]),
        temperature=float(values["temperature"]),  # type: ignore[arg-type]
        max_tokens=int(values["max_tokens"]),  # type: ignore[arg-type]
        request_timeout_seconds=float(values["request_timeout_seconds"]),  # type: ignore[arg-type]
        notifications_enabled=bool(values["notifications_enabled"]),
        defaults=dict(snapshot.defaults),
        overridden=snapshot.overridden,
        provider=ProviderView(
            name="nebius",
            api_key_configured=bool(settings.nebius_api_key),
            base_url_configured=bool(settings.nebius_base_url),
        ),
        trust_default_decision=settings.trust_default_decision,
        environment=settings.environment,
        updated_at=snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        storage_available=snapshot.storage_available,
    )


@router.get("", response_model=SettingsResponse)
async def read_settings(
    service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    settings: Settings = Depends(get_settings),
) -> SettingsResponse:
    return _response(service.snapshot(), settings)


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    settings: Settings = Depends(get_settings),
) -> SettingsResponse:
    # ``exclude_unset`` is what separates "leave this alone" (absent) from
    # "clear the override" (present and null). Both are legitimate; collapsing
    # them would make it impossible to return a field to its environment default.
    changes = payload.model_dump(exclude_unset=True)
    try:
        service.update(changes)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except SettingsStorageError as error:
        # The write did not reach the store. Reporting success here would show the
        # operator a setting that reverts on the next read.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="settings could not be persisted",
        ) from error
    return _response(service.snapshot(), settings)
