"""The scheduled job: a user's standing instruction to run an agent later.

Two rules shape this entity and both are worth stating up front.

**The job is an instruction, never an authorization.** Creating a job that runs
"every weekday at 09:00" says nothing about what the agent is allowed to do when
it wakes up. Every execution creates a fresh ``AgentRun`` and re-enters the Trust
Engine from scratch. There is deliberately no field on this entity that could be
read as a standing grant.

**Rehydration must never fail.** A mapper rebuilds this object from a database
row, including rows whose ``next_run_at`` is in the past (a finished ``ONCE``
job keeps its original timestamp forever). So ``__post_init__`` validates
*structure* only -- types, required fields, cron syntax -- and never compares
against the current time. The "an ``ONCE`` job may not be scheduled in the past"
rule is enforced where "now" is an explicit argument, in
:func:`schedule_occurrence` and in the creation use cases.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.domain.entities._common import json_size, require_text, utc_now
from app.domain.value_objects.cron_expression import CronExpression, CronExpressionError
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType

#: Serialised ``payload`` cap. A scheduled job carries the arguments a user
#: pre-filled once; it is not a place to stage documents.
MAX_PAYLOAD_BYTES = 16_384
MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 4_000

_ALLOWED_TRANSITIONS: dict[ScheduledJobStatus, frozenset[ScheduledJobStatus]] = {
    ScheduledJobStatus.ACTIVE: frozenset(
        {
            ScheduledJobStatus.PAUSED,
            ScheduledJobStatus.COMPLETED,
            ScheduledJobStatus.FAILED,
            ScheduledJobStatus.CANCELLED,
        }
    ),
    ScheduledJobStatus.PAUSED: frozenset(
        {
            ScheduledJobStatus.ACTIVE,
            ScheduledJobStatus.CANCELLED,
        }
    ),
    ScheduledJobStatus.COMPLETED: frozenset({ScheduledJobStatus.CANCELLED}),
    # FAILED can go back to ACTIVE, but only because resuming a failed job is an
    # explicit, deliberate user action -- nothing reaches that state
    # automatically. The scheduler's recovery sweep moves executions to FAILED,
    # never jobs, so there is no code path that revives a job on its own.
    # COMPLETED stays terminal: a one-shot that already ran is history, and
    # CANCELLED stays terminal because the user said stop.
    ScheduledJobStatus.FAILED: frozenset(
        {ScheduledJobStatus.ACTIVE, ScheduledJobStatus.CANCELLED}
    ),
    ScheduledJobStatus.CANCELLED: frozenset(),
}


class ScheduledJobError(ValueError):
    """The job cannot exist in the state its fields describe."""


def _require_aware(moment: datetime, field_name: str) -> None:
    if moment.tzinfo is None:
        raise ScheduledJobError(
            f"{field_name} must be timezone-aware; store UTC and convert at the edge"
        )


def _validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ScheduledJobError("payload must be a mapping")
    try:
        size = json_size(payload)
    except (TypeError, ValueError) as error:
        raise ScheduledJobError(f"payload is not serialisable: {error}") from error
    if size > MAX_PAYLOAD_BYTES:
        raise ScheduledJobError(
            f"payload is {size} bytes which exceeds the {MAX_PAYLOAD_BYTES} byte limit"
        )


@dataclass
class ScheduledJob:
    """A user's standing instruction to create an agent run on a schedule."""

    user_id: EntityId
    agent_id: EntityId
    name: str
    trigger_type: ScheduledTriggerType
    id: EntityId = field(default_factory=EntityId.new)
    description: str = ""
    timezone: str = "UTC"
    cron_expression: str | None = None
    interval_seconds: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    status: ScheduledJobStatus = ScheduledJobStatus.ACTIVE
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.timezone, "timezone")
        if len(self.name) > MAX_NAME_LENGTH:
            raise ScheduledJobError(f"name exceeds {MAX_NAME_LENGTH} characters")
        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise ScheduledJobError(
                f"description exceeds {MAX_DESCRIPTION_LENGTH} characters"
            )
        _validate_payload(self.payload)

        try:
            self.trigger_type = ScheduledTriggerType(self.trigger_type)
            self.status = ScheduledJobStatus(self.status)
        except ValueError as error:
            raise ScheduledJobError(f"invalid enum value: {error}") from error

        for field_name in ("next_run_at", "last_run_at", "created_at", "updated_at"):
            moment = getattr(self, field_name)
            if moment is not None:
                _require_aware(moment, field_name)

        self._validate_schedule_shape()

    # -- validation ------------------------------------------------------

    def _validate_schedule_shape(self) -> None:
        """Check the trigger fields agree with ``trigger_type``.

        Structure only. Time comparisons happen in the use cases, so a completed
        job can still be rebuilt from its row.
        """
        if self.trigger_type is ScheduledTriggerType.CRON:
            if not self.cron_expression:
                raise ScheduledJobError("CRON jobs require a cron_expression")
            # Parses, or raises. The timezone is resolved here too, so a bad IANA
            # name is rejected at creation rather than at 09:00 on the first fire.
            CronExpression(self.cron_expression, self.timezone)
            if self.interval_seconds is not None:
                raise ScheduledJobError("CRON jobs must not set interval_seconds")
            # next_run_at is not required here: it is derived from the cron
            # expression by schedule_from(), which needs an explicit "now" that
            # a constructor does not have. The creation use case calls
            # schedule_from() and refuses to persist an unscheduled job.

        elif self.trigger_type is ScheduledTriggerType.INTERVAL:
            if self.interval_seconds is None:
                raise ScheduledJobError("INTERVAL jobs require interval_seconds")
            if self.interval_seconds <= 0:
                raise ScheduledJobError("interval_seconds must be greater than zero")
            if self.cron_expression is not None:
                raise ScheduledJobError("INTERVAL jobs must not set cron_expression")

        elif self.trigger_type is ScheduledTriggerType.ONCE:
            if self.cron_expression is not None:
                raise ScheduledJobError("ONCE jobs must not set cron_expression")
            if self.interval_seconds is not None:
                raise ScheduledJobError("ONCE jobs must not set interval_seconds")
            # Unlike CRON and INTERVAL, an ONCE job has no schedule to derive a
            # time from. It is stated outright, so it is required here.
            if self.next_run_at is None:
                raise ScheduledJobError("ONCE jobs require next_run_at")

        else:  # EVENT
            if self.cron_expression is not None:
                raise ScheduledJobError("EVENT jobs must not set cron_expression")
            if self.interval_seconds is not None:
                raise ScheduledJobError("EVENT jobs must not set interval_seconds")
            # An event job has no clock, so a next_run_at would be a lie the
            # dispatcher would otherwise have to special-case forever.
            if self.next_run_at is not None:
                raise ScheduledJobError("EVENT jobs must not set next_run_at")

    # -- schedule computation --------------------------------------------

    def next_occurrence_after(self, after: datetime) -> datetime | None:
        """When this job should next fire strictly after ``after``, in UTC.

        Returns ``None`` only for a CRON that can never fire (February 30th).
        """
        _require_aware(after, "after")
        if self.trigger_type is ScheduledTriggerType.EVENT:
            return None
        if self.trigger_type is ScheduledTriggerType.ONCE:
            # A one-shot does not roll forward: once its moment has passed it is
            # finished, not deferred.
            return None
        if self.trigger_type is ScheduledTriggerType.INTERVAL:
            assert self.interval_seconds is not None  # guaranteed by validation
            return after + timedelta(seconds=self.interval_seconds)
        assert self.cron_expression is not None  # guaranteed by validation
        return CronExpression(self.cron_expression, self.timezone).next_after(after)

    def revalidate(self) -> "ScheduledJob":
        """Re-check the trigger fields after an in-place edit.

        Public on purpose: the update use case mutates individual fields and
        then needs the same structural guarantee ``__post_init__`` gives, without
        rebuilding the object (which would discard its id and history).
        """
        self._validate_schedule_shape()
        _validate_payload(self.payload)
        return self

    def schedule_from(self, now: datetime) -> "ScheduledJob":
        """Compute ``next_run_at`` from ``now`` and return self, for chaining.

        ``ONCE`` is left alone: its time was stated outright, and there is no
        schedule to derive one from. Deriving it anyway would overwrite the
        requested instant with ``None``.
        """
        _require_aware(now, "now")
        if self.trigger_type is not ScheduledTriggerType.ONCE:
            self.next_run_at = self.next_occurrence_after(now)
        self.updated_at = utc_now()
        return self

    def is_due(self, now: datetime) -> bool:
        """True when the clock says this job should fire now.

        An event job is never due on a clock; it has no ``next_run_at`` at all.
        """
        if not self.status.is_schedulable:
            return False
        if not self.trigger_type.is_clock_based:
            return False
        if self.next_run_at is None:
            return False
        return self.next_run_at <= now

    def has_missed(self, now: datetime, grace_seconds: int) -> bool:
        """True when the job fell so far behind that replaying it is harmful.

        After downtime an ``INTERVAL`` job may be hours overdue. Replaying every
        skipped occurrence would turn a ten-minute outage into a burst of
        duplicate agent runs, so past that grace window the job records a
        ``SKIPPED`` execution and simply reschedules.
        """
        if self.next_run_at is None:
            return False
        return (now - self.next_run_at) > timedelta(seconds=grace_seconds)

    # -- event matching --------------------------------------------------

    def watched_event_types(self) -> frozenset[str]:
        """Event types this job subscribes to, read from its payload.

        Declared in the payload rather than as a dedicated column because it is
        a property of the same user-authored instruction the rest of the payload
        holds, and because a job has exactly one place where "what this does"
        is written down.
        """
        if self.trigger_type is not ScheduledTriggerType.EVENT:
            return frozenset()

        raw_list = self.payload.get("event_types")
        if raw_list is not None:
            if not isinstance(raw_list, (list, tuple)):
                raise ScheduledJobError("payload 'event_types' must be a list")
            for entry in raw_list:
                if not isinstance(entry, str) or not entry.strip():
                    raise ScheduledJobError("payload 'event_types' must hold non-empty strings")
            return frozenset(entry.strip() for entry in raw_list)

        single = self.payload.get("event_type")
        if isinstance(single, str) and single.strip():
            return frozenset({single.strip()})
        return frozenset()

    def matches_event_type(self, event_type: str) -> bool:
        """Exact, case-sensitive match against this job's subscriptions."""
        return event_type in self.watched_event_types()

    # -- lifecycle -------------------------------------------------------

    def transition_to(self, status: ScheduledJobStatus) -> "ScheduledJob":
        try:
            target = ScheduledJobStatus(status)
        except ValueError as error:
            raise ScheduledJobError(f"invalid scheduled job status: {status}") from error
        if target is self.status:
            return self
        allowed = _ALLOWED_TRANSITIONS[self.status]
        if target not in allowed:
            raise ScheduledJobError(
                f"invalid scheduled job transition: {self.status.value} -> {target.value}"
            )
        self.status = target
        self.updated_at = utc_now()
        return self

    def pause(self) -> "ScheduledJob":
        return self.transition_to(ScheduledJobStatus.PAUSED)

    def activate(self) -> "ScheduledJob":
        return self.transition_to(ScheduledJobStatus.ACTIVE)

    def cancel(self) -> "ScheduledJob":
        self.next_run_at = None
        return self.transition_to(ScheduledJobStatus.CANCELLED)

    def complete(self) -> "ScheduledJob":
        self.next_run_at = None
        return self.transition_to(ScheduledJobStatus.COMPLETED)

    def mark_failed(self, reason: str) -> "ScheduledJob":
        """Latch the job into FAILED and stop the clock."""
        self.last_error = reason[:2_000] if reason else "unspecified failure"
        self.next_run_at = None
        return self.transition_to(ScheduledJobStatus.FAILED)

    def record_run(self, fired_at: datetime, next_run_at: datetime | None) -> "ScheduledJob":
        """Note that the job just fired and when it is next expected to.

        For ``ONCE`` and for a CRON that cannot fire again this latches the job
        to COMPLETED, because leaving it ACTIVE with a ``None`` next run would
        make the dispatcher re-claim it forever.
        """
        _require_aware(fired_at, "fired_at")
        self.last_run_at = fired_at
        self.updated_at = utc_now()

        if self.trigger_type is ScheduledTriggerType.ONCE or next_run_at is None:
            return self.complete()
        self.next_run_at = next_run_at
        return self

    def is_owned_by(self, user_id: EntityId) -> bool:
        return self.user_id == user_id

    def assert_owned_by(self, user_id: EntityId) -> None:
        """Raise unless this job belongs to ``user_id``.

        Ownership is enforced here rather than at the route so that it holds no
        matter which entry point reaches the entity.
        """
        if not self.is_owned_by(user_id):
            raise PermissionError("scheduled job belongs to another user")