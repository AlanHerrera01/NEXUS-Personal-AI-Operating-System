"""Where inbound events come from.

Push-based sources (a webhook POST) never implement this port: they arrive
through the HTTP route, which builds a :class:`RawEvent` and hands it to the
same ``TriggerEventService`` that a pull-based source feeds. That is on purpose
-- validation, deduplication and rate limiting have to happen on exactly one
path, or an event admitted through the webhook would skip checks that a polled
source is subject to.

This port therefore covers only the case the push route cannot: sources NEXUS
has to go and ask for events itself.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RawEvent:
    """An unvalidated event as delivered by a source.

    Nothing here has been checked yet. ``user_id`` is deliberately absent: a
    source adapter states *which* user the events belong to out of band, and a
    ``user_id`` supplied inside a payload is never trusted.
    """

    source: str
    event_type: str
    idempotency_key: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventSourcePort(ABC):
    """A source NEXUS polls for events belonging to one user."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short identifier recorded on every event this source produces."""

    @abstractmethod
    async def poll(self, since: datetime) -> list[RawEvent]:
        """Return events newer than ``since``.

        Adapters must return events in ascending ``idempotency_key`` order and
        must not de-duplicate: the service does that, against the database,
        where it is authoritative across processes.
        """