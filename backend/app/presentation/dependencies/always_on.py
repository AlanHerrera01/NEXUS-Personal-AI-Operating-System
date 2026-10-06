"""Dependency providers for the Always-On feature.

Two conventions from the existing package are followed here: repositories take
the request-scoped :func:`session_dependency`, and the orchestrator is obtained
from the existing :func:`orchestrator_dependency` rather than rebuilt. That
second point is the one that matters -- reusing the real orchestrator provider is
what guarantees a scheduled run is wired with the same Trust Engine, the same
approval service and the same sandboxed tool executor as a run started from the
chat UI. A dispatcher built from its own orchestrator would be a second
execution pipeline with its own, unknowable, policy.

The services that need several repositories take the ``Session`` directly and
build them inline, rather than taking four separate ``Depends``. That keeps each
service on one session, which matters because the repositories commit
individually and there is no unit of work in this codebase.

The scheduler itself is deliberately *not* a FastAPI dependency: it holds a
background task for the life of the process, so it is built once in the lifespan
hook. Only per-request services are resolved through ``Depends``.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.agent_runs.create_agent_run import CreateAgentRunUseCase
from app.application.always_on.create_scheduled_job import CreateScheduledJobUseCase
from app.application.always_on.execution_coordinator import JobExecutionCoordinator
from app.application.always_on.job_dispatcher import JobDispatcher
from app.application.always_on.manage_proactive_rule import (
    CreateProactiveRuleUseCase,
    DeleteProactiveRuleUseCase,
    GetProactiveRuleUseCase,
    ListProactiveRulesUseCase,
    SetProactiveRuleEnabledUseCase,
)
from app.application.always_on.manage_scheduled_job import (
    CancelScheduledJobUseCase,
    GetJobExecutionUseCase,
    GetScheduledJobUseCase,
    ListJobExecutionsUseCase,
    ListScheduledJobsUseCase,
    PauseScheduledJobUseCase,
    ResumeScheduledJobUseCase,
    UpdateScheduledJobUseCase,
)
from app.application.always_on.proactive_service import ProactiveAgentService
from app.application.always_on.scheduler_service import AlwaysOnSchedulerService
from app.application.always_on.trigger_event_service import TriggerEventService
from app.config.settings import Settings, get_settings
from app.domain.services.proactive_evaluation_service import ProactiveEvaluationService
from app.domain.services.schedule_window_service import ScheduleWindowService
from app.infrastructure.always_on.event_source import IngressAuthenticator
from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.infrastructure.persistence.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.persistence.repositories.job_execution_repository import (
    SqlAlchemyJobExecutionRepository,
)
from app.infrastructure.persistence.repositories.proactive_rule_repository import (
    SqlAlchemyProactiveRuleRepository,
)
from app.infrastructure.persistence.repositories.scheduled_job_repository import (
    SqlAlchemyScheduledJobRepository,
)
from app.infrastructure.persistence.repositories.trigger_event_repository import (
    SqlAlchemyTriggerEventRepository,
)
from app.presentation.dependencies.agent import orchestrator_dependency
from app.presentation.dependencies.persistence import session_dependency
from app.presentation.dependencies.security import get_approval_service


# -- repositories -----------------------------------------------------


def get_scheduled_job_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyScheduledJobRepository:
    return SqlAlchemyScheduledJobRepository(session)


def get_job_execution_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyJobExecutionRepository:
    return SqlAlchemyJobExecutionRepository(session)


def get_trigger_event_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyTriggerEventRepository:
    return SqlAlchemyTriggerEventRepository(session)


def get_proactive_rule_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyProactiveRuleRepository:
    return SqlAlchemyProactiveRuleRepository(session)


def get_agent_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRepository:
    return SqlAlchemyAgentRepository(session)


def get_agent_run_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRunRepository:
    return SqlAlchemyAgentRunRepository(session)


# -- shared collaborators ---------------------------------------------


def get_schedule_window_service(
    settings: Settings = Depends(get_settings),
) -> ScheduleWindowService:
    return ScheduleWindowService(grace_seconds=settings.always_on_grace_seconds)


def get_proactive_evaluation_service() -> ProactiveEvaluationService:
    return ProactiveEvaluationService()


def get_ingress_authenticator(
    settings: Settings = Depends(get_settings),
) -> IngressAuthenticator:
    return IngressAuthenticator(settings.always_on_event_ingress_secret)


def get_create_agent_run_use_case(
    session: Session = Depends(session_dependency),
) -> CreateAgentRunUseCase:
    return CreateAgentRunUseCase(
        agent_repository=SqlAlchemyAgentRepository(session),
        agent_run_repository=SqlAlchemyAgentRunRepository(session),
    )


# -- core services ----------------------------------------------------


def get_job_dispatcher(
    session: Session = Depends(session_dependency),
    orchestrator=Depends(orchestrator_dependency),
    window_service: ScheduleWindowService = Depends(get_schedule_window_service),
    settings: Settings = Depends(get_settings),
) -> JobDispatcher:
    return JobDispatcher(
        create_agent_run=CreateAgentRunUseCase(
            agent_repository=SqlAlchemyAgentRepository(session),
            agent_run_repository=SqlAlchemyAgentRunRepository(session),
        ),
        orchestrator=orchestrator,
        agent_run_repository=SqlAlchemyAgentRunRepository(session),
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
        job_execution_repository=SqlAlchemyJobExecutionRepository(session),
        window_service=window_service,
        max_concurrent_runs_per_user=settings.always_on_max_concurrent_runs,
    )


def get_job_execution_coordinator(
    session: Session = Depends(session_dependency),
    orchestrator=Depends(orchestrator_dependency),
) -> JobExecutionCoordinator:
    return JobExecutionCoordinator(
        orchestrator=orchestrator,
        agent_run_repository=SqlAlchemyAgentRunRepository(session),
        job_execution_repository=SqlAlchemyJobExecutionRepository(session),
    )


def get_always_on_scheduler_service(
    session: Session = Depends(session_dependency),
    dispatcher: JobDispatcher = Depends(get_job_dispatcher),
    approval_service=Depends(get_approval_service),
    settings: Settings = Depends(get_settings),
) -> AlwaysOnSchedulerService:
    return AlwaysOnSchedulerService(
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
        job_execution_repository=SqlAlchemyJobExecutionRepository(session),
        dispatcher=dispatcher,
        approval_service=approval_service,
        max_jobs_per_tick=settings.always_on_max_jobs_per_tick,
    )


def get_trigger_event_service(
    session: Session = Depends(session_dependency),
    dispatcher: JobDispatcher = Depends(get_job_dispatcher),
    settings: Settings = Depends(get_settings),
) -> TriggerEventService:
    return TriggerEventService(
        trigger_event_repository=SqlAlchemyTriggerEventRepository(session),
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
        dispatcher=dispatcher,
        max_events_per_minute=settings.always_on_max_events_per_minute,
        max_jobs_per_event=settings.always_on_max_jobs_per_event,
    )


def get_proactive_agent_service(
    session: Session = Depends(session_dependency),
    orchestrator=Depends(orchestrator_dependency),
) -> ProactiveAgentService:
    return ProactiveAgentService(
        proactive_rule_repository=SqlAlchemyProactiveRuleRepository(session),
        evaluation_service=ProactiveEvaluationService(),
        create_agent_run=CreateAgentRunUseCase(
            agent_repository=SqlAlchemyAgentRepository(session),
            agent_run_repository=SqlAlchemyAgentRunRepository(session),
        ),
        orchestrator=orchestrator,
    )


# -- scheduled job use cases -------------------------------------------


def get_create_scheduled_job_use_case(
    session: Session = Depends(session_dependency),
    settings: Settings = Depends(get_settings),
) -> CreateScheduledJobUseCase:
    return CreateScheduledJobUseCase(
        agent_repository=SqlAlchemyAgentRepository(session),
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
        max_active_jobs_per_user=settings.always_on_max_active_jobs_per_user,
        min_interval_seconds=settings.always_on_min_interval_seconds,
    )


def get_get_scheduled_job_use_case(
    session: Session = Depends(session_dependency),
) -> GetScheduledJobUseCase:
    return GetScheduledJobUseCase(SqlAlchemyScheduledJobRepository(session))


def get_list_scheduled_jobs_use_case(
    session: Session = Depends(session_dependency),
) -> ListScheduledJobsUseCase:
    return ListScheduledJobsUseCase(SqlAlchemyScheduledJobRepository(session))


def get_pause_scheduled_job_use_case(
    session: Session = Depends(session_dependency),
) -> PauseScheduledJobUseCase:
    return PauseScheduledJobUseCase(SqlAlchemyScheduledJobRepository(session))


def get_resume_scheduled_job_use_case(
    session: Session = Depends(session_dependency),
) -> ResumeScheduledJobUseCase:
    return ResumeScheduledJobUseCase(SqlAlchemyScheduledJobRepository(session))


def get_cancel_scheduled_job_use_case(
    session: Session = Depends(session_dependency),
) -> CancelScheduledJobUseCase:
    return CancelScheduledJobUseCase(SqlAlchemyScheduledJobRepository(session))


def get_update_scheduled_job_use_case(
    session: Session = Depends(session_dependency),
) -> UpdateScheduledJobUseCase:
    return UpdateScheduledJobUseCase(SqlAlchemyScheduledJobRepository(session))


def get_list_job_executions_use_case(
    session: Session = Depends(session_dependency),
) -> ListJobExecutionsUseCase:
    return ListJobExecutionsUseCase(
        job_execution_repository=SqlAlchemyJobExecutionRepository(session),
        scheduled_job_repository=SqlAlchemyScheduledJobRepository(session),
    )


def get_get_job_execution_use_case(
    session: Session = Depends(session_dependency),
) -> GetJobExecutionUseCase:
    return GetJobExecutionUseCase(SqlAlchemyJobExecutionRepository(session))


# -- proactive rule use cases -----------------------------------------


def get_create_proactive_rule_use_case(
    session: Session = Depends(session_dependency),
    settings: Settings = Depends(get_settings),
) -> CreateProactiveRuleUseCase:
    return CreateProactiveRuleUseCase(
        proactive_rule_repository=SqlAlchemyProactiveRuleRepository(session),
        agent_repository=SqlAlchemyAgentRepository(session),
        max_rules_per_user=settings.always_on_max_proactive_rules_per_user,
    )


def get_list_proactive_rules_use_case(
    session: Session = Depends(session_dependency),
) -> ListProactiveRulesUseCase:
    return ListProactiveRulesUseCase(SqlAlchemyProactiveRuleRepository(session))


def get_get_proactive_rule_use_case(
    session: Session = Depends(session_dependency),
) -> GetProactiveRuleUseCase:
    return GetProactiveRuleUseCase(SqlAlchemyProactiveRuleRepository(session))


def get_set_proactive_rule_enabled_use_case(
    session: Session = Depends(session_dependency),
) -> SetProactiveRuleEnabledUseCase:
    return SetProactiveRuleEnabledUseCase(SqlAlchemyProactiveRuleRepository(session))


def get_delete_proactive_rule_use_case(
    session: Session = Depends(session_dependency),
) -> DeleteProactiveRuleUseCase:
    return DeleteProactiveRuleUseCase(SqlAlchemyProactiveRuleRepository(session))