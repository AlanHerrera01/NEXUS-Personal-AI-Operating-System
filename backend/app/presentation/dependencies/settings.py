"""Dependency providers for the runtime settings panel.

Two providers, and the difference between them matters:

* :func:`get_runtime_settings_service` is the read/write surface the settings
  route uses. It holds the environment defaults so it can report provenance.
* :func:`get_effective_settings` is the *merged* ``Settings`` that the parts of
  the system which actually consume these knobs -- the LLM client, the overview,
  the model health probe -- should inject. They get a ``Settings`` object, not a
  new type, so nothing downstream needs to know overrides exist.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.settings.service import (
    RuntimeSettingsService,
    RuntimeSettingsSnapshot,
)
from app.config.settings import Settings, get_settings
from app.infrastructure.persistence.repositories.runtime_settings_repository import (
    SqlAlchemyRuntimeSettingsRepository,
)
from app.presentation.dependencies.persistence import session_dependency

#: Override field -> the ``Settings`` attribute it replaces. The panel speaks in
#: provider-neutral names ("model"); the config speaks in Nebius names
#: ("nebius_model"). The translation lives here, at the one seam that knows both.
_FIELD_TO_SETTING = {
    "model": "nebius_model",
    "temperature": "llm_temperature",
    "max_tokens": "llm_max_tokens",
    "request_timeout_seconds": "llm_timeout",
}


def _environment_defaults(settings: Settings) -> dict[str, object]:
    return {
        "model": settings.nebius_model,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "request_timeout_seconds": settings.llm_timeout,
        # A UI preference with no environment equivalent; the default is off
        # because nothing in the backend sends notifications yet.
        "notifications_enabled": False,
    }


def get_runtime_settings_service(
    session: Session = Depends(session_dependency),
    settings: Settings = Depends(get_settings),
) -> RuntimeSettingsService:
    return RuntimeSettingsService(
        SqlAlchemyRuntimeSettingsRepository(session),
        defaults=_environment_defaults(settings),
    )


def _merged(settings: Settings, snapshot: RuntimeSettingsSnapshot) -> Settings:
    """The boot config with the persisted overrides applied on top.

    Degrades to the boot config when the override store cannot be read, so a
    database outage does not stop the model from answering with the credentials
    the environment already provided.
    """
    if not snapshot.storage_available:
        return settings
    update = {
        _FIELD_TO_SETTING[name]: snapshot.effective[name]
        for name in snapshot.overridden
        if name in _FIELD_TO_SETTING
    }
    return settings.model_copy(update=update) if update else settings


def get_effective_settings(
    service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    settings: Settings = Depends(get_settings),
) -> Settings:
    """The merged configuration, for the request path."""
    return _merged(settings, service.snapshot())


def resolve_effective_settings(session: Session) -> Settings:
    """The same merge, for a caller that holds a session but no request.

    The orchestrator builder and the always-on loop are in that category: they
    assemble long-lived objects outside a request, and they must still see the
    model the panel was pointed at rather than only the one the process booted
    with.
    """
    base = get_settings()
    return _merged(base, get_runtime_settings_service(session, base).snapshot())
