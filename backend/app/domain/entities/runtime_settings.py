"""Operator-tunable runtime settings, as persisted overrides.

Every field is optional, and ``None`` means *no override*: the value configured
in the process environment applies. That tri-state is the entire point of the
entity. Storing "the value" instead would make a deliberate change and a
return-to-default indistinguishable, and the UI could not honestly tell the user
which of the two they are looking at.

The set of tunable fields is closed and lives in :data:`WRITABLE_FIELDS`. An
override can only ever reach one of those names -- never the API key, the base
URL or the trust posture, which stay in the environment where the person who
runs the deployment put them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: The only fields an override is allowed to carry. Anything else is refused by
#: the service rather than silently dropped.
WRITABLE_FIELDS: tuple[str, ...] = (
    "model",
    "temperature",
    "max_tokens",
    "request_timeout_seconds",
    "notifications_enabled",
)


@dataclass
class RuntimeSettings:
    """Sparse overrides. ``None`` on a field means "inherit the environment"."""

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    request_timeout_seconds: float | None = None
    notifications_enabled: bool | None = None
    updated_at: datetime | None = None

    def overrides(self) -> dict[str, object]:
        """Only the fields that actually carry an override."""
        return {
            name: getattr(self, name)
            for name in WRITABLE_FIELDS
            if getattr(self, name) is not None
        }
