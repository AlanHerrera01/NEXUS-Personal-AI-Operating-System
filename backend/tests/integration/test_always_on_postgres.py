"""Always-On against a real PostgreSQL database.

The parts of this feature that cannot be verified with fakes are the parts that
matter most:

* ``create_if_absent`` relies on a unique-violation being raised and caught. An
  in-memory fake cannot raise ``IntegrityError``, so a fake would let this method
  look correct while the real one crashed or, worse, silently inserted twice.
* ``try_claim`` and ``try_advance_schedule`` are compare-and-set UPDATE
  statements whose outcome is decided by ``rowcount``. A fake returning
  ``True`` proves nothing about whether two processes can both win.
* Round-tripping ``json`` payloads and timezone-aware timestamps through real
  columns catches the coercion bugs that only appear against a real driver.

So these tests drive two independent sessions -- standing in for two worker
processes -- and assert that exactly one of them wins the same occurrence.

Marked ``integration``, matching the existing Postgres suites, so they are
skipped when no database is configured.
"""

from datetime import timedelta

import pytest

from app.application.always_on.create_scheduled_job import CreateScheduledJobUseCase
from app.application.always_on.job_dispatcher import clock_idempotency_key
from app.domain.entities._common import utc_now
from app.domain.entities.job_execution import JobExecution
from app.domain.entities.scheduled_job import ScheduledJob
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.job_execution_status import JobExecutionStatus
from app.domain.value_objects.scheduled_job_status import ScheduledJobStatus
from app.domain.value_objects.scheduled_trigger_type import ScheduledTriggerType
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.infrastructure.persistence.repositories.job_execution_repository import (
    SqlAlchemyJobExecutionRepository,
)
from app.infrastructure.persistence.repositories.scheduled_job_repository import (
    SqlAlchemyScheduledJobRepository,
)
from app.domain.entities.agent import Agent
from app.domain.entities.agent_run import AgentRun
from app.infrastructure.persistence.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)

pytestmark = pytest.mark.integration

USER = EntityId.new()
OTHER_USER = EntityId.new()


def _new_job(session, name: str = "always-on integration job") -> ScheduledJob:
    agent = SqlAlchemyAgentRepository(session).save(
        Agent(name=f"agent for {name} {EntityId.new()}")
    )
    return CreateScheduledJobUseCase(
        agent_repository=SqlAlchemyAgentRepository(session),
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
        min_interval_seconds=1,
    ).execute(
        user_id=USER,
        agent_id=agent.id,
        name=name,
        trigger_type=ScheduledTriggerType.INTERVAL,
        interval_seconds=60,
        payload={"prompt": "summarise"},
    )


class TestJobRoundTrip:
    def test_job_survives_a_real_round_trip(self) -> None:
        """Payload, timezone and schedule must come back unchanged.

        A naive/aware mismatch here would only appear in production, and would
        surface as a TypeError deep inside a cron calculation.
        """
        session = SessionFactory()
        try:
            job = _new_job(session, "round trip")

            stored = SqlAlchemyScheduledJobRepository(session).get_by_id(job.id)
            assert stored is not None
            assert stored.payload == {"prompt": "summarise"}
            assert stored.interval_seconds == 60
            assert stored.status is ScheduledJobStatus.ACTIVE
            assert stored.next_run_at == job.next_run_at
            assert stored.next_run_at.tzinfo is not None
            assert stored.is_owned_by(USER)
        finally:
            session.close()

    def test_list_is_scoped_to_the_owner(self) -> None:
        """Ownership must be enforced by the query, not only by the use case."""
        session = SessionFactory()
        try:
            _new_job(session, "scoped job")

            mine = SqlAlchemyScheduledJobRepository(session).list_by_user(USER)
            theirs = SqlAlchemyScheduledJobRepository(session).list_by_user(OTHER_USER)

            assert any(job.name == "scoped job" for job in mine)
            assert all(job.name != "scoped job" for job in theirs)
        finally:
            session.close()


class TestIdempotencyAcrossSessions:
    def test_second_worker_cannot_claim_the_same_occurrence(self) -> None:
        """The core guarantee: one occurrence, one execution, one winner.

        Two sessions stand in for two processes. The second must be told the
        key is taken rather than inserting a duplicate row.
        """
        first = SessionFactory()
        second = SessionFactory()
        try:
            job = _new_job(first, "race job")
            scheduled_for = job.next_run_at
            assert scheduled_for is not None

            key = clock_idempotency_key(job, scheduled_for)
            candidate = JobExecution(
                scheduled_job_id=job.id,
                user_id=USER,
                idempotency_key=key,
                scheduled_for=scheduled_for,
            )

            winner_repo = SqlAlchemyJobExecutionRepository(first)
            loser_repo = SqlAlchemyJobExecutionRepository(second)

            created, was_created = winner_repo.create_if_absent(candidate)
            assert was_created is True

            # Second worker, same derived key.
            duplicate, was_created_again = loser_repo.create_if_absent(
                JobExecution(
                    scheduled_job_id=job.id,
                    user_id=USER,
                    idempotency_key=key,
                    scheduled_for=scheduled_for,
                )
            )
            assert was_created_again is False
            assert duplicate.id == created.id

            # And exactly one claim succeeds.
            assert winner_repo.try_claim(created.id, utc_now()) is True
            assert loser_repo.try_claim(created.id, utc_now()) is False
        finally:
            first.close()
            second.close()

    def test_only_one_session_can_advance_the_schedule(self) -> None:
        """``try_advance_schedule`` must be a genuine compare-and-set."""
        first = SessionFactory()
        second = SessionFactory()
        try:
            job = _new_job(first, "cas job")
            expected = job.next_run_at
            assert expected is not None
            ahead = expected + timedelta(seconds=60)

            winner = SqlAlchemyScheduledJobRepository(first).try_advance_schedule(
                job.id, expected, ahead
            )
            loser = SqlAlchemyScheduledJobRepository(second).try_advance_schedule(
                job.id, expected, ahead
            )

            assert winner is True
            assert loser is False

            reloaded = SqlAlchemyScheduledJobRepository(first).get_by_id(job.id)
            assert reloaded.next_run_at == ahead
        finally:
            first.close()
            second.close()


class TestConcurrencyCount:
    def test_count_is_not_limited_to_recent_rows(self) -> None:
        """A long-running execution must still occupy a concurrency slot."""
        session = SessionFactory()
        try:
            job = _new_job(session, "count job")
            repository = SqlAlchemyJobExecutionRepository(session)

            execution = repository.create_if_absent(
                JobExecution(
                    scheduled_job_id=job.id,
                    user_id=USER,
                    idempotency_key=f"running:{EntityId.new()}",
                    scheduled_for=utc_now(),
                )
            )[0]
            assert repository.try_claim(execution.id, utc_now()) is True

            # The old call passed `now` as the `since` bound, which counted
            # nothing and let the limit be exceeded silently.
            assert repository.count_by_user_status(USER, JobExecutionStatus.RUNNING) >= 1
            assert repository.count_by_user_status(OTHER_USER, JobExecutionStatus.RUNNING) == 0
        finally:
            session.close()


class TestGetOpenByRun:
    def test_finds_the_execution_parked_on_an_approval(self) -> None:
        """The reconciliation hook locates its execution through this.

        A manual run has no execution at all, which is how the hook tells the
        two cases apart, so this must return None rather than raise for an
        unknown run.
        """
        session = SessionFactory()
        try:
            job = _new_job(session, "open by run")
            repository = SqlAlchemyJobExecutionRepository(session)

            # A real run row, because the FK is enforced -- which is itself the
            # assertion that an execution cannot claim to belong to a run that
            # does not exist.
            run = SqlAlchemyAgentRunRepository(session).save(
                AgentRun(agent_id=job.agent_id, user_request="do the thing")
            )

            execution = repository.create_if_absent(
                JobExecution(
                    scheduled_job_id=job.id,
                    user_id=USER,
                    idempotency_key=f"open:{EntityId.new()}",
                    scheduled_for=utc_now(),
                    agent_run_id=run.id,
                )
            )[0]
            repository.try_claim(execution.id, utc_now())

            found = repository.get_open_by_run(execution.agent_run_id)
            assert found is not None
            assert found.id == execution.id

            assert repository.get_open_by_run(EntityId.new()) is None
        finally:
            session.close()