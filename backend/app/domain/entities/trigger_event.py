"""An inbound signal from the outside world.

Events are untrusted by default. This entity is the choke point where that
untrusted input is bounded, identified and recorded before any job can act on
it. Everything here is about refusing work, not enabling it:

* the payload is size-capped and must be a JSON object
* the source and type must be short, printable, pattern-checked strings, so a
  crafted value cannot end up in a log line or a query
* ``user_id`` is supplied by the authenticated ingress, never by the payload,
  so a caller cannot act on another user's behalf by including their id
* ``idempotency_key`` is mandatory, which is what makes a retried webhook
  delivery a no-op instead of a second run
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities._common import json_size, require_text, utc_now
from app.domain.value_objects.entity_id import EntityId

MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
MAX_SOURCE_LENGTH = 64
MAX_EVENT_TYPE_LENGTH = 128
MAX_IDEMPOTENCY_KEY_LENGTH = 300

#: Conservative charset for identifiers that end up in logs, metrics and job
#: history. Deliberately narrower than URL-safe base64.
_ALLOWED_IDENTIFIER = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-/"
)


class TriggerEventError(ValueError):
    """The event is malformed or exceeds its bounds."""


def _validate_identifier(value: str, field_name: str, max_length: int) -> str:
    require_text(value, field_name)
    if len(value) > max_length:
        raise TriggerEventError(f"{field_name} exceeds {max_length} characters")
    if not set(value) <= _ALLOWED_IDENTIFIER:
        raise TriggerEventError(
            f"{field_name} contains characters outside the allowed identifier set"
        )
    return value


@dataclass
class TriggerEvent:
    """A received, validated, deduplicated external event."""

    user_id: EntityId
    source: str
    event_type: str
    idempotency_key: str
    id: EntityId = field(default_factory=EntityId.new)
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=utc_now)
    processed_at: datetime | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.source, "source", MAX_SOURCE_LENGTH)
        _validate_identifier(self.event_type, "event_type", MAX_EVENT_TYPE_LENGTH)
        _validate_identifier(
            self.idempotency_key, "idempotency_key", MAX_IDEMPOTENCY_KEY_LENGTH
        )
        if self.received_at.tzinfo is None:
            raise TriggerEventError("received_at must be timezone-aware")

        if not isinstance(self.payload, dict):
            raise TriggerEventError("payload must be a mapping")
        try:
            size = json_size(self.payload)
        except (TypeError, ValueError) as error:
            raise TriggerEventError(f"payload is not serialisable: {error}") from error
        if size > MAX_EVENT_PAYLOAD_BYTES:
            raise TriggerEventError(
                f"payload is {size} bytes which exceeds the "
                f"{MAX_EVENT_PAYLOAD_BYTES} byte limit"
            )

    def mark_processed(self) -> "TriggerEvent":
        self.processed_at = utc_now()
        self.error_message = None
        return self

    def mark_failed(self, reason: str) -> "TriggerEvent":
        self.processed_at = utc_now()
        self.error_message = reason[:2_000] if reason else "unspecified failure"
        return self

    @property
    def is_processed(self) -> bool:
        return self.processed_at is not None

    def is_owned_by(self, user_id: EntityId) -> bool:
        return self.user_id == user_id

    def matches(self, event_type: str) -> bool:
        """Exact match only. No prefix or glob matching on untrusted input."""
        return self.event_type == event_type