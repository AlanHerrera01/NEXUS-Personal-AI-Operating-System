"""Runtime settings: how the persisted overrides merge with the boot config.

Two kinds of value meet here.

* The **boot configuration** comes from the process environment -- the model id,
  the generation parameters, the request timeout. It is the ground truth for a
  fresh deployment, and it is what every knob falls back to.
* The **persisted overrides** are what an operator changed from the UI after the
  process started. They are stored sparsely (see :class:`RuntimeSettings`), so a
  field left unset keeps inheriting the environment.

The merge is one-directional on purpose: an override can only move the fields in
``WRITABLE_FIELDS``. The API key, the base URL, the trust posture and every bound
the environment set are unreachable from here. A settings panel that could
repoint the provider or relax the trust engine would be a remote-control surface
for the security model, not a convenience.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.entities.runtime_settings import WRITABLE_FIELDS, RuntimeSettings
from app.domain.repositories.runtime_settings_repository import (
    RuntimeSettingsRepository,
)

# Bounds live here, not only in the request schema, so a caller that reaches the
# service directly (an internal job, a test) is held to the same numbers.
TEMPERATURE_RANGE = (0.0, 2.0)
MAX_TOKENS_RANGE = (1, 32_768)
REQUEST_TIMEOUT_RANGE = (1.0, 600.0)
MODEL_MAX_LENGTH = 200


class SettingsStorageError(RuntimeError):
    """The override row could not be read or written.

    Distinct from a validation failure: this is the store being unavailable, not
    the caller asking for something invalid. The route turns it into a 503 rather
    than pretending a write succeeded.
    """


@dataclass(frozen=True)
class RuntimeSettingsSnapshot:
    """Everything the UI needs to render the panel honestly."""

    effective: dict[str, object]
    defaults: dict[str, object]
    overridden: list[str]
    updated_at: datetime | None
    storage_available: bool


class RuntimeSettingsService:
    def __init__(
        self,
        repository: RuntimeSettingsRepository,
        defaults: Mapping[str, object],
    ) -> None:
        self._repository = repository
        self._defaults = dict(defaults)

    def overrides(self) -> RuntimeSettings:
        """The stored overrides, or an empty set when nothing was saved."""
        return self._repository.get() or RuntimeSettings()

    def snapshot(self) -> RuntimeSettingsSnapshot:
        """The effective configuration plus its provenance.

        A storage fault is reported, not raised: the panel is still worth
        rendering with the environment's values, and ``storage_available`` tells
        the user why their saved overrides are not in the list.
        """
        try:
            stored = self._repository.get()
        except Exception:  # noqa: BLE001 - a store outage must not blank the page
            return RuntimeSettingsSnapshot(
                effective=dict(self._defaults),
                defaults=dict(self._defaults),
                overridden=[],
                updated_at=None,
                storage_available=False,
            )

        overrides = (stored or RuntimeSettings()).overrides()
        effective = dict(self._defaults)
        effective.update(overrides)
        return RuntimeSettingsSnapshot(
            effective=effective,
            defaults=dict(self._defaults),
            overridden=sorted(overrides),
            updated_at=stored.updated_at if stored else None,
            storage_available=True,
        )

    def update(self, changes: Mapping[str, object]) -> RuntimeSettings:
        """Apply a partial change set, merging it onto the stored overrides.

        A key present with a value of ``None`` clears that override (returns the
        field to its environment default); a key that is absent is left alone.
        The caller distinguishes the two with its request model's
        ``exclude_unset``, so the two cases never collapse into one here.
        """
        # Validation failures are the caller's fault and must surface as 422;
        # they are raised before this block so a storage fault below cannot
        # swallow them into a 503.
        validated = self._validate(changes)
        try:
            # The read is inside the guard on purpose: a change set is merged
            # onto the current overrides, so an unreadable store means the write
            # cannot be computed -- not that it can proceed from an empty row.
            current = self._repository.get() or RuntimeSettings()
            for name, value in validated.items():
                setattr(current, name, value)
            current.updated_at = datetime.now(timezone.utc)
            saved = self._repository.save(current)
        except Exception as error:  # noqa: BLE001 - re-raise as a typed fault
            raise SettingsStorageError(str(error)) from error
        return saved or current

    def _validate(self, changes: Mapping[str, object]) -> dict[str, object]:
        unknown = sorted(set(changes) - set(WRITABLE_FIELDS))
        if unknown:
            raise ValueError(f"unknown setting(s): {', '.join(unknown)}")

        cleaned: dict[str, object] = {}
        for name, value in changes.items():
            if value is None:
                cleaned[name] = None
                continue
            if name == "model":
                cleaned[name] = self._validate_model(value)
            elif name == "temperature":
                cleaned[name] = self._validate_number(
                    name, value, TEMPERATURE_RANGE
                )
            elif name == "max_tokens":
                cleaned[name] = int(self._validate_number(name, value, MAX_TOKENS_RANGE))
            elif name == "request_timeout_seconds":
                cleaned[name] = self._validate_number(
                    name, value, REQUEST_TIMEOUT_RANGE
                )
            elif name == "notifications_enabled":
                if not isinstance(value, bool):
                    raise ValueError("notifications_enabled must be a boolean")
                cleaned[name] = value
        return cleaned

    @staticmethod
    def _validate_model(value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("model must not be blank")
        if len(text) > MODEL_MAX_LENGTH:
            raise ValueError(f"model must be at most {MODEL_MAX_LENGTH} characters")
        return text

    @staticmethod
    def _validate_number(
        name: str, value: object, bounds: tuple[float, float]
    ) -> float:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number") from error
        low, high = bounds
        if not low <= number <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return number
