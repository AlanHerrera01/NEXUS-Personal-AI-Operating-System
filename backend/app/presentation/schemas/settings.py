"""Request/response models for the runtime settings panel.

The response separates *values* from *provenance* on purpose: the UI needs to
show not only the effective temperature but whether the number came from the
environment or from a saved override, so ``overridden`` names the fields that
were changed here and ``defaults`` carries what they would fall back to.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.application.settings.service import (
    MAX_TOKENS_RANGE,
    MODEL_MAX_LENGTH,
    REQUEST_TIMEOUT_RANGE,
    TEMPERATURE_RANGE,
)


class ProviderView(BaseModel):
    """Read-only provider facts. None of these are settable from the panel."""

    name: str
    api_key_configured: bool
    base_url_configured: bool


class SettingsResponse(BaseModel):
    # Effective values (override where present, environment otherwise).
    model: str
    temperature: float
    max_tokens: int
    request_timeout_seconds: float
    notifications_enabled: bool

    # Provenance.
    defaults: dict[str, Any]
    overridden: list[str]

    # Read-only context the panel displays but cannot change.
    provider: ProviderView
    trust_default_decision: str
    trust_editable: bool = False
    #: The memory firewall is enforced and not switchable: disabling secret or
    #: injection blocking would make the deployment store credentials and
    #: replay injected instructions. Reported as a fact, not a control.
    memory_firewall_enforced: bool = True
    memory_firewall_editable: bool = False
    environment: str
    updated_at: str | None = None
    #: False when the override store could not be read; the values above are
    #: then the environment defaults and any saved overrides are absent.
    storage_available: bool = True


class SettingsUpdateRequest(BaseModel):
    """A partial update.

    Omit a field to leave it alone; send it as ``null`` to clear the override and
    fall back to the environment value. The route reads ``exclude_unset`` so the
    two cases are distinguishable.
    """

    model: str | None = Field(default=None, min_length=1, max_length=MODEL_MAX_LENGTH)
    temperature: float | None = Field(
        default=None, ge=TEMPERATURE_RANGE[0], le=TEMPERATURE_RANGE[1]
    )
    max_tokens: int | None = Field(
        default=None, ge=MAX_TOKENS_RANGE[0], le=MAX_TOKENS_RANGE[1]
    )
    request_timeout_seconds: float | None = Field(
        default=None, ge=REQUEST_TIMEOUT_RANGE[0], le=REQUEST_TIMEOUT_RANGE[1]
    )
    notifications_enabled: bool | None = None
