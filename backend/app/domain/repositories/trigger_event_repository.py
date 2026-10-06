from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.trigger_event import TriggerEvent
from app.domain.value_objects.entity_id import EntityId


class TriggerEventRepository(ABC):
    """Persistence for :class:`TriggerEvent`.

    ``idempotency_key`` is unique, exactly as on job executions. A provider that
    retries a webhook delivery therefore produces one row and one dispatch: the
    second delivery is recognised as a duplicate at ingest, before any job is
    even considered.
    """

    @abstractmethod
    def save(self, event: TriggerEvent) -> TriggerEvent:
        """Insert or update the event and return the stored state."""

    @abstractmethod
    def create_if_absent(self, event: TriggerEvent) -> tuple[TriggerEvent, bool]:
        """Insert unless ``idempotency_key`` already exists.

        Returns ``(event, True)`` when newly stored, ``(existing, False)`` when
        the key was already taken. Must not raise on a duplicate key.
        """

    @abstractmethod
    def get_by_id(self, event_id: EntityId) -> TriggerEvent | None: ...

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> TriggerEvent | None: ...

    @abstractmethod
    def list_by_user(self, user_id: EntityId, limit: int = 100) -> list[TriggerEvent]:
        """Recent events for one user, newest first."""

    @abstractmethod
    def count_by_user_since(self, user_id: EntityId, since: datetime) -> int:
        """Count events for the user received at or after ``since``.

        The rate limiter is a database count rather than an in-process counter on
        purpose: an in-process counter resets on restart and is per-worker, so
        with two workers the effective limit would quietly double, and after a
        deploy an attacker would get a fresh allowance.
        """