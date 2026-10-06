"""The single door through which every external event enters the system.

Both ingress paths converge here on purpose. A webhook POST from the HTTP route
and an event pulled by an :class:`EventSourcePort` adapter are handed to the same
:meth:`TriggerEventService.ingest`, because if they had separate paths the
checks below would exist on only one of them and the unguarded one would become
the way in.

What an untrusted event gets here, in order:

1. **Rate limit**, counted from the database, before any work is done.
2. **Validation** by constructing a :class:`TriggerEvent`, which bounds the
   payload size and restricts the identifiers to a safe charset.
3. **Deduplication** against the unique ``idempotency_key``. A provider that
   retries a delivery -- which most of them do -- produces one row and zero
   extra runs.
4. **Subscription matching** against EVENT-triggered jobs belonging to that same
   user. ``user_id`` comes from the authenticated ingress, never from the
   payload, so an event cannot be aimed at someone else's jobs.
5. **Dispatch** through the normal orchestrator.

Note what is *not* here: nothing about the event widens what the resulting run
may do. The event only decides *whether a run starts*, never what it is allowed
to do once started.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.application.always_on.errors import EventRateLimited
from app.application.always_on.job_dispatcher import (
    DispatchOutcome,
    DispatchOutcomeType,
    JobDispatcher,
)
from app.domain.entities._common import utc_now
from app.domain.entities.scheduled_job import ScheduledJob
from app.domain.entities.trigger_event import TriggerEvent, TriggerEventError
from app.domain.ports.event_source import RawEvent
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository
from app.domain.repositories.trigger_event_repository import TriggerEventRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus


@dataclass
class IngestReport:
    """Outcome of accepting one event."""

    event: TriggerEvent | None
    duplicate: bool = False
    matched_jobs: int = 0
    outcomes: list[DispatchOutcome] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def count(self, outcome: DispatchOutcomeType) -> int:
        return sum(1 for item in self.outcomes if item.outcome is outcome)


class TriggerEventService:
    """Validates, deduplicates and fans out inbound events."""

    def __init__(
        self,
        *,
        trigger_event_repository: TriggerEventRepository,
        scheduled_job_repository: ScheduledJobRepository,
        dispatcher: JobDispatcher,
        max_events_per_minute: int = 60,
        max_jobs_per_event: int = 20,
        logger: logging.Logger | None = None,
    ) -> None:
        self.trigger_event_repository = trigger_event_repository
        self.scheduled_job_repository = scheduled_job_repository
        self.dispatcher = dispatcher
        self.max_events_per_minute = max_events_per_minute
        self.max_jobs_per_event = max_jobs_per_event
        self.logger = logger or logging.getLogger(__name__)

    async def ingest(
        self,
        *,
        user_id: EntityId,
        source: str,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> IngestReport:
        moment = now or utc_now()
        report = IngestReport(event=None)

        self._enforce_rate_limit(user_id, moment)

        try:
            candidate = TriggerEvent(
                user_id=user_id,
                source=source,
                event_type=event_type,
                idempotency_key=idempotency_key,
                payload=payload or {},
                received_at=moment,
            )
        except TriggerEventError as error:
            # A malformed event is refused outright; it is never persisted, so a
            # caller cannot fill the table with junk by retrying.
            raise ValueError(str(error)) from error

        try:
            event, created = self.trigger_event_repository.create_if_absent(candidate)
        except Exception as error:  # noqa: BLE001
            report.errors.append(f"could not record the event: {error}")
            self.logger.error("could not record event %s: %s", idempotency_key, error)
            return report

        if not created:
            report.event = event
            report.duplicate = True
            self.logger.info(
                "ignoring duplicate event %s from %s", idempotency_key, source
            )
            return report

        report.event = event

        jobs = self._matching_jobs(user_id, event_type)
        report.matched_jobs = len(jobs)

        if not jobs:
            event.mark_processed()
            self.trigger_event_repository.save(event)
            return report

        for job in jobs:
            try:
                report.outcomes.append(
                    await self.dispatcher.run_event_triggered(job, event, moment)
                )
            except Exception as error:  # noqa: BLE001
                report.errors.append(f"job {job.id}: {error}")
                self.logger.exception("event dispatch failed for job %s", job.id)

        # A partial fan-out is recorded as a failure on the event, but the jobs
        # that did run are not unwound: their executions carry their own outcomes.
        if report.errors:
            event.mark_failed("; ".join(report.errors))
        else:
            event.mark_processed()
        self.trigger_event_repository.save(event)
        return report

    async def ingest_many(
        self, user_id: EntityId, raws: list[RawEvent], now: datetime | None = None
    ) -> list[IngestReport]:
        """Fan in a polled batch, preserving per-event outcomes."""
        return [
            await self.ingest(
                user_id=user_id,
                source=raw.source,
                event_type=raw.event_type,
                idempotency_key=raw.idempotency_key,
                payload=raw.payload,
                now=now,
            )
            for raw in raws
        ]

    # -- internals -------------------------------------------------------

    def _enforce_rate_limit(self, user_id: EntityId, now: datetime) -> None:
        since = now - timedelta(minutes=1)
        recent = self.trigger_event_repository.count_by_user_since(user_id, since)
        if recent >= self.max_events_per_minute:
            raise EventRateLimited(str(user_id))

    def _matching_jobs(self, user_id: EntityId, event_type: str) -> list[ScheduledJob]:
        candidates = self.scheduled_job_repository.list_by_user(
            user_id, status=ScheduledJobStatus.ACTIVE, limit=200
        )
        matched = []
        for job in candidates:
            try:
                if job.matches_event_type(event_type):
                    matched.append(job)
            except Exception as error:  # noqa: BLE001 - one bad job must not block others
                self.logger.warning(
                    "job %s has an unusable event subscription: %s", job.id, error
                )
        return matched[: self.max_jobs_per_event]