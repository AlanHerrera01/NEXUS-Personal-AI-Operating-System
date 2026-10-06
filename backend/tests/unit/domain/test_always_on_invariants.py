"""Always-On domain invariants.

These are contract tests on the rules that are easy to break and invisible when
broken. Both regressions here were live for a while and no existing test noticed:

* resuming a ``FAILED`` job raised, because the transition table did not permit
  ``FAILED -> ACTIVE`` even though the resume use case performs exactly that
  transition;
* the per-user concurrency limit never fired, because it counted executions
  created *since the current instant*, which is always none.

A test that only asserts the happy path would have passed with both bugs in
place, so each case below states the specific failure it rules out.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.application.always_on.manage_scheduled_job import ResumeScheduledJobUseCase
from app.domain.entities._common import utc_now
from app.domain.entities.job_execution import JobExecution, JobExecutionError
from app.domain.entities.scheduled_job import (
    MAX_PAYLOAD_BYTES,
    ScheduledJob,
    ScheduledJobError,
    _validate_payload,
)
from app.domain.value_objects.cron_expression import CronExpression, CronExpressionError
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.job_execution_status import JobExecutionStatus
from app.domain.repositories.scheduled_job_repository import ScheduledJobRepository
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType

UTC = timezone.utc


# -- helpers ----------------------------------------------------------


def cron_job(expression: str = "0 9 * * *", timezone_name: str = "UTC") -> ScheduledJob:
    return ScheduledJob(
        user_id=EntityId.new(),
        agent_id=EntityId.new(),
        name="daily standup summary",
        trigger_type=ScheduledTriggerType.CRON,
        timezone=timezone_name,
        cron_expression=expression,
        payload={"prompt": "summarise my tasks"},
    )


class InMemoryScheduledJobRepository(ScheduledJobRepository):
    """Real storage, not a mock, so the resume path is genuinely exercised.

    Subclasses the real ABC on purpose: if the repository contract grows a method
    this fake does not implement, instantiation fails here instead of quietly
    diverging from the production adapter.
    """

    def __init__(self, job: ScheduledJob) -> None:
        self.job = job

    def save(self, job: ScheduledJob) -> ScheduledJob:
        self.job = job
        return job

    def get_by_id(self, job_id: EntityId) -> ScheduledJob | None:
        return self.job if self.job.id == job_id else None

    def list_by_user(self, user_id, status=None, limit=100):
        if not self.job.is_owned_by(user_id):
            return []
        if status is not None and self.job.status is not status:
            return []
        return [self.job]

    def list_due(self, now, limit=50):
        return []

    def count_active_for_user(self, user_id: EntityId) -> int:
        return 1 if self.job.status is ScheduledJobStatus.ACTIVE else 0

    def try_advance_schedule(self, job_id, expected, new_next) -> bool:
        return self.job.next_run_at == expected


def execution(status: JobExecutionStatus = JobExecutionStatus.RUNNING) -> JobExecution:
    item = JobExecution(
        scheduled_job_id=EntityId.new(),
        user_id=EntityId.new(),
        idempotency_key=f"schedule:{EntityId.new()}:2026-01-01T00:00:00+00:00",
        scheduled_for=utc_now(),
    )
    if status is JobExecutionStatus.RUNNING:
        # claim() is what moves QUEUED -> RUNNING; mark_running() only stamps
        # started_at, so using the wrong one here would leave the entity QUEUED.
        item.claim()
    return item


# -- cron -------------------------------------------------------------


class TestCronExpression:
    def test_rejects_wrong_field_count(self) -> None:
        with pytest.raises(CronExpressionError):
            CronExpression("0 9 * *")

    def test_rejects_out_of_range_values(self) -> None:
        with pytest.raises(CronExpressionError):
            CronExpression("99 9 * * *")

    def test_rejects_non_numeric_minutes(self) -> None:
        with pytest.raises(CronExpressionError):
            CronExpression("abc 9 * * *")

    def test_unknown_timezone_is_rejected(self) -> None:
        with pytest.raises(CronExpressionError):
            CronExpression("0 9 * * *", timezone="Mars/Olympus_Mons")

    def test_next_after_is_strictly_later(self) -> None:
        cron = CronExpression("0 9 * * *", "UTC")
        exactly_nine = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        assert cron.next_after(exactly_nine) == datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

    def test_next_after_honours_the_configured_timezone(self) -> None:
        # 09:00 in New York is 14:00 UTC in March (EDT, UTC-4).
        cron = CronExpression("0 9 * * *", "America/New_York")
        result = cron.next_after(datetime(2026, 3, 1, 0, 0, tzinfo=UTC))
        assert result is not None
        local = result.astimezone(cron._timezone)
        assert (local.hour, local.minute) == (9, 0)

    def test_step_and_range_are_parsed(self) -> None:
        cron = CronExpression("*/15 9-17 * * 1-5", "UTC")
        nine_am = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        following = cron.next_after(nine_am)
        assert following == datetime(2026, 3, 2, 9, 15, tzinfo=UTC)

    def test_sunday_is_accepted_as_seven(self) -> None:
        # Cron allows 0 or 7 for Sunday; both must parse rather than 7 failing
        # an out-of-range check.
        assert CronExpression("0 9 * * 7", "UTC").expression


class TestPayloadSerialisation:
    """Payloads are validated against the encoding that will actually be stored.

    Sizing with ``repr`` looks equivalent and is not: ``repr`` happily accepts a
    ``set``, a ``datetime`` or a function, so the payload is accepted at creation
    and only blows up much later when the driver writes it to a JSON column. The
    error also lands far from its cause, which is the expensive kind to debug.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            {"tags": {1, 2, 3}},
            {"at": datetime(2026, 1, 1, tzinfo=UTC)},
            {"blob": b"bytes"},
            {"fn": len},
        ],
        ids=["set", "datetime", "bytes", "callable"],
    )
    def test_rejects_values_json_cannot_store(self, payload: dict) -> None:
        with pytest.raises(ScheduledJobError, match="not serialisable"):
            _validate_payload(payload)

    def test_accepts_an_ordinary_payload(self) -> None:
        _validate_payload({"prompt": "summarise", "limit": 5})

    def test_limit_is_measured_on_the_real_encoding(self) -> None:
        payload = {"k": "x" * (MAX_PAYLOAD_BYTES + 100)}
        with pytest.raises(ScheduledJobError, match="exceeds"):
            _validate_payload(payload)


class TestDayFieldSemantics:
    """Vixie cron ORs the two day fields when both are restricted.

    Getting this backwards is invisible: the expression still validates and the
    schedule still looks sensible in a UI, it just almost never fires. `0 0 13 * 5`
    under AND fires roughly once every 28 months instead of every Friday.
    """

    def test_day_of_month_alone(self) -> None:
        cron = CronExpression("0 0 13 * *", "UTC")
        assert cron.matches(datetime(2026, 3, 13, 0, 0, tzinfo=UTC))
        assert not cron.matches(datetime(2026, 3, 14, 0, 0, tzinfo=UTC))

    def test_day_of_week_alone(self) -> None:
        # 2026-03-13 is a Friday, 2026-03-14 a Saturday.
        cron = CronExpression("0 0 * * 5", "UTC")
        assert cron.matches(datetime(2026, 3, 13, 0, 0, tzinfo=UTC))
        assert not cron.matches(datetime(2026, 3, 14, 0, 0, tzinfo=UTC))

    def test_both_restricted_means_either(self) -> None:
        cron = CronExpression("0 0 13 * 5", "UTC")
        assert cron.matches(datetime(2026, 3, 20, 0, 0, tzinfo=UTC))  # Friday
        assert cron.matches(datetime(2026, 4, 13, 0, 0, tzinfo=UTC))  # Monday the 13th
        assert not cron.matches(datetime(2026, 3, 21, 0, 0, tzinfo=UTC))  # Saturday

    def test_next_after_advances_to_the_friday_not_the_next_13th(self) -> None:
        """The two fields each contribute occurrences, not their intersection."""
        cron = CronExpression("0 0 13 * 5", "UTC")
        friday = datetime(2026, 3, 20, 0, 0, tzinfo=UTC)
        following = cron.next_after(friday)
        assert following is not None
        # The next occurrence is the following Friday, not a month away.
        assert following == datetime(2026, 3, 27, 0, 0, tzinfo=UTC)


# -- scheduled job state machine --------------------------------------


class TestScheduledJobTransitions:
    def test_failed_job_can_be_resumed(self) -> None:
        """Resume performs FAILED -> ACTIVE; the table must allow it.

        Regression: this raised ``invalid transition FAILED -> ACTIVE``.
        """
        job = cron_job()
        job.mark_failed("last fire blew up")
        assert job.status is ScheduledJobStatus.FAILED

        repository = InMemoryScheduledJobRepository(job)
        resumed = ResumeScheduledJobUseCase(repository).execute(job.id, job.user_id)

        assert resumed.status is ScheduledJobStatus.ACTIVE
        assert resumed.next_run_at is not None

    def test_resume_reschedules_from_now_not_from_the_stale_slot(self) -> None:
        """A job paused for a week must not fire a week late on resume."""
        job = cron_job()
        job.pause()
        job.next_run_at = utc_now() - timedelta(days=7)

        resumed = ResumeScheduledJobUseCase(
            InMemoryScheduledJobRepository(job)
        ).execute(job.id, job.user_id)

        assert resumed.next_run_at is not None
        assert resumed.next_run_at > utc_now() - timedelta(minutes=1)

    def test_completed_job_cannot_be_resumed(self) -> None:
        """A one-shot that already ran is history, not something to reopen."""
        job = cron_job()
        job.complete()

        with pytest.raises(Exception):
            ResumeScheduledJobUseCase(
                InMemoryScheduledJobRepository(job)
            ).execute(job.id, job.user_id)

    def test_cancelled_job_is_final(self) -> None:
        job = cron_job()
        job.cancel()
        with pytest.raises(ScheduledJobError):
            job.activate()

    def test_ownership_is_required_to_read_a_job(self) -> None:
        job = cron_job()
        assert job.is_owned_by(job.user_id)
        assert not job.is_owned_by(EntityId.new())


# -- job execution state machine --------------------------------------


class TestJobExecutionTransitions:
    def test_running_execution_can_be_skipped(self) -> None:
        """Declining to run because of the concurrency limit is not a failure.

        Regression: the dispatcher called ``mark_failed`` here, and RUNNING ->
        SKIPPED was not a legal transition, so the deferral path could not have
        worked even once the count was fixed.
        """
        item = execution(JobExecutionStatus.RUNNING)
        item.mark_skipped("user is at their concurrency limit")
        assert item.status is JobExecutionStatus.SKIPPED
        assert item.is_open is False

    def test_terminal_execution_is_never_reopened(self) -> None:
        item = execution(JobExecutionStatus.RUNNING)
        item.mark_completed("done")
        with pytest.raises(JobExecutionError):
            item.mark_failed("too late")

    def test_waiting_permission_stays_open_across_restart(self) -> None:
        item = execution(JobExecutionStatus.RUNNING)
        item.mark_waiting_permission()
        assert item.status is JobExecutionStatus.WAITING_PERMISSION
        assert item.is_open is True
        assert item.completed_at is None

    def test_scheduled_for_must_be_aware(self) -> None:
        with pytest.raises(JobExecutionError):
            JobExecution(
                scheduled_job_id=EntityId.new(),
                user_id=EntityId.new(),
                idempotency_key="schedule:x:2026-01-01T00:00:00+00:00",
                scheduled_for=datetime(2026, 1, 1),  # naive
            )


# -- concurrency limit ------------------------------------------------


class TestConcurrencyCounting:
    def test_limit_counts_runs_of_any_age(self) -> None:
        """The count must not be scoped to recent executions.

        Regression: ``count_by_user_since(user, now, RUNNING)`` filtered on
        ``created_at >= now``, so it returned 0 and the limit never engaged.
        """

        class Repo:
            def count_by_user_status(self, user_id, status):
                # Includes a run that started a long time ago.
                return 3

            def count_by_user_since(self, user_id, since, status):
                return 0

        from app.application.always_on.job_dispatcher import JobDispatcher

        dispatcher = JobDispatcher(
            create_agent_run=None,
            orchestrator=None,
            agent_run_repository=None,
            scheduled_job_repository=None,
            job_execution_repository=Repo(),
            window_service=None,
            max_concurrent_runs_per_user=3,
        )

        reason = dispatcher._concurrency_blocked(EntityId.new())
        assert reason is not None
        assert "already running" in reason

    def test_limit_allows_work_below_the_cap(self) -> None:
        class Repo:
            def count_by_user_status(self, user_id, status):
                return 2

        from app.application.always_on.job_dispatcher import JobDispatcher

        dispatcher = JobDispatcher(
            create_agent_run=None,
            orchestrator=None,
            agent_run_repository=None,
            scheduled_job_repository=None,
            job_execution_repository=Repo(),
            window_service=None,
            max_concurrent_runs_per_user=3,
        )
        assert dispatcher._concurrency_blocked(EntityId.new()) is None