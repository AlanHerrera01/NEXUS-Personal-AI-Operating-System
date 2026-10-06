"""Background wiring for the Always-On scheduler.

This module owns the awkward part of running a scheduler inside a web process:
the loop has no request, so it has no request-scoped ``Session``, no resolved
FastAPI dependency and no ``Depends`` to lean on. Everything is built once here
against a session that lives as long as the loop.

Session lifetime is the decision worth flagging. A single long-lived session for
the whole process would hold a transaction open between ticks and eventually
exhaust the connection pool or serve reads from a stale snapshot, so each tick
opens and closes its own session instead. The cost is a fresh connection per
tick, which at a five-second cadence is nothing next to the LLM calls a tick
actually triggers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy.orm import Session

from app.application.always_on.job_dispatcher import DispatchOutcomeType, JobDispatcher
from app.application.always_on.proactive_service import ProactiveAgentService
from app.application.always_on.recovery_service import AlwaysOnRecoveryService
from app.application.always_on.scheduler_service import AlwaysOnSchedulerService
from app.application.agent_runs.create_agent_run import CreateAgentRunUseCase
from app.application.security.approval_service import ApprovalService
from app.application.security.trust_engine import TrustEngine
from app.config.settings import get_settings
from app.domain.services.proactive_evaluation_service import (
    ProactiveContext,
    ProactiveEvaluationService,
)
from app.domain.services.schedule_window_service import ScheduleWindowService
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.infrastructure.persistence.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.persistence.repositories.job_execution_repository import (
    SqlAlchemyJobExecutionRepository,
)
from app.infrastructure.persistence.repositories.permission_repository import (
    SqlPermissionRepository,
)
from app.infrastructure.persistence.repositories.permission_request_repository import (
    SqlPermissionRequestRepository,
)
from app.infrastructure.persistence.repositories.proactive_rule_repository import (
    SqlAlchemyProactiveRuleRepository,
)
from app.infrastructure.persistence.repositories.scheduled_job_repository import (
    SqlAlchemyScheduledJobRepository,
)
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.entity_id import EntityId
from app.presentation.dependencies.agent import build_orchestrator, build_skill_system
from app.presentation.dependencies.identity import LOCAL_USER_ID

logger = logging.getLogger(__name__)


@contextmanager
def tick_session() -> Iterator[Session]:
    """One session per tick, closed even if the tick raises."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def _approval_service(session: Session) -> ApprovalService:
    settings = get_settings()
    return ApprovalService(
        SqlPermissionRequestRepository(session),
        request_ttl_seconds=settings.permission_request_ttl_seconds,
    )


def _trust_engine(session: Session) -> TrustEngine:
    from app.application.security.policy_registry import PolicyRegistry

    settings = get_settings()
    registry = PolicyRegistry(
        permission_checker=None,
        disabled_skills=frozenset(
            name.strip() for name in settings.disabled_skills.split(",") if name.strip()
        ),
    )
    return TrustEngine(
        registry.create_policy_engine(),
        SqlPermissionRepository(session),
        default_decision=PermissionDecision(settings.trust_default_decision),
    )


def build_dispatcher(session: Session) -> JobDispatcher:
    """Assemble the dispatcher on the real orchestrator, sandbox included."""
    settings = get_settings()
    system = build_skill_system(session)
    orchestrator = build_orchestrator(
        session, system, _trust_engine(session), _approval_service(session)
    )

    return JobDispatcher(
        create_agent_run=CreateAgentRunUseCase(
            agent_repository=SqlAlchemyAgentRepository(session),
            agent_run_repository=SqlAlchemyAgentRunRepository(session),
        ),
        orchestrator=orchestrator,
        agent_run_repository=SqlAlchemyAgentRunRepository(session),
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
        job_execution_repository=SqlAlchemyJobExecutionRepository(session),
        window_service=ScheduleWindowService(
            grace_seconds=settings.always_on_grace_seconds
        ),
        max_concurrent_runs_per_user=settings.always_on_max_concurrent_runs,
    )


class AlwaysOnTickHandler:
    """What the polling loop calls once per interval."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def recover(self) -> None:
        """Mark executions abandoned by a dead process as FAILED.

        Called once at startup, before the first tick. Runs left RUNNING by a
        crash are never retried -- the user may already have acted on the run's
        side effects, and re-running it would repeat them. Failing them is the
        honest outcome; the schedule moves on to its next slot.
        """
        with tick_session() as session:
            report = AlwaysOnRecoveryService(
                job_execution_repository=SqlAlchemyJobExecutionRepository(session),
                stale_after=_stale_after(self.settings.always_on_stale_execution_seconds),
            ).recover()

        if report.failed_stale or report.skipped_waiting:
            logger.warning(
                "recovery sweep: %d stale execution(s) failed, %d left waiting "
                "on a human decision",
                report.failed_stale,
                report.skipped_waiting,
            )

    async def tick(self, now: datetime) -> None:
        """One scheduler pass.

        Clock jobs first, then proactive evaluation. A proactive rule that fires
        in the same window is evaluated after the clock work has claimed its
        executions, so the concurrency check sees them and defers instead of
        overshooting the per-user limit.
        """
        with tick_session() as session:
            dispatcher = build_dispatcher(session)
            approval_service = _approval_service(session)

            scheduler = AlwaysOnSchedulerService(
                scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
                job_execution_repository=SqlAlchemyJobExecutionRepository(session),
                dispatcher=dispatcher,
                approval_service=approval_service,
                max_jobs_per_tick=self.settings.always_on_max_jobs_per_tick,
            )
            report = await scheduler.tick(now)

            dispatched = sum(
                1
                for item in report.outcomes
                if item.outcome is DispatchOutcomeType.DISPATCHED
            )
            skipped = sum(
                1
                for item in report.outcomes
                if item.outcome is DispatchOutcomeType.SKIPPED
            )
            duplicates = sum(
                1
                for item in report.outcomes
                if item.outcome is DispatchOutcomeType.DUPLICATE
            )
            if dispatched or skipped or duplicates:
                logger.info(
                    "always-on tick: %d considered, %d dispatched, %d skipped, "
                    "%d already handled",
                    report.considered,
                    dispatched,
                    skipped,
                    duplicates,
                )

            await self._evaluate_proactive(session, dispatcher, now)

    async def _evaluate_proactive(
        self, session: Session, dispatcher: JobDispatcher, now: datetime
    ) -> None:
        settings = self.settings
        service = ProactiveAgentService(
            proactive_rule_repository=SqlAlchemyProactiveRuleRepository(session),
            evaluation_service=ProactiveEvaluationService(),
            create_agent_run=CreateAgentRunUseCase(
                agent_repository=SqlAlchemyAgentRepository(session),
                agent_run_repository=SqlAlchemyAgentRunRepository(session),
            ),
            orchestrator=dispatcher.orchestrator,
            max_rules_per_pass=settings.always_on_max_jobs_per_tick,
        )

        # Only wall-clock facts are known here. Proactive conditions that need real
        # activity -- an idle timer, an overdue task -- cannot be evaluated from
        # an empty context, and inventing activity to satisfy a rule would make
        # the agent act on fiction. Zero counts mean those conditions simply do
        # not match, which is the honest answer.
        context = ProactiveContext(
            now=now,
            last_activity_at=None,
            pending_task_count=0,
            overdue_task_count=0,
            user_id=EntityId(LOCAL_USER_ID),
        )
        report = await service.evaluate(EntityId(LOCAL_USER_ID), context, now=now)

        if report.fired or report.suggestions:
            logger.info(
                "proactive pass: %d evaluated, %d fired, %d suggestions",
                report.evaluated,
                len(report.fired),
                len(report.suggestions),
            )


def _stale_after(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


def build_tick_handler() -> AlwaysOnTickHandler:
    return AlwaysOnTickHandler()