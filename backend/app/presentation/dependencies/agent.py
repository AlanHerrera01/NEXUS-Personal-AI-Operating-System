from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.agents.context_builder import AgentContextBuilder
from app.application.agents.orchestrator import AgentOrchestrator
from app.application.agents.rule_based_brain import RuleBasedAgentBrain
from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.memory.firewall import MemoryFirewall
from app.application.memory.get_memory import GetMemoryUseCase
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.memory.search_memories import SearchMemoriesUseCase
from app.application.memory.service import MemoryService
from app.application.agent_runtime.plan_validator import DefaultPlanValidator
from app.application.security.approval_service import ApprovalService
from app.application.security.trust_engine import TrustEngine
from app.application.skills.catalog import SkillAwareToolCatalog
from app.application.skills.registry import SkillRegistry
from app.application.skills.selector import KeywordSkillSelector
from app.application.tools.executor import RegistryToolExecutor
from app.application.tools.registry import InMemoryToolRegistry
from app.config.settings import get_settings
from app.domain.ports.skill import Skill
from app.domain.ports.skill_selector import SkillSelector
from app.infrastructure.persistence.repositories.agent_action_repository import SqlAlchemyAgentActionRepository
from app.infrastructure.persistence.repositories.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.repositories.memory_repository import SqlAlchemyMemoryRepository
from app.infrastructure.persistence.repositories.task_repository import SqlAlchemyTaskRepository
from app.infrastructure.skills.memory.skill import MemorySkill
from app.infrastructure.skills.tasks.skill import TaskSkill
from app.presentation.dependencies.persistence import session_dependency
from app.presentation.dependencies.runtime import build_runtime_tool_executor
from app.presentation.dependencies.security import (
    get_approval_service,
    get_security_audit,
    get_trust_engine,
)


@dataclass(frozen=True)
class SkillSystem:
    """Everything the agent needs to discover capabilities, wired once."""

    skills: SkillRegistry
    tools: InMemoryToolRegistry
    catalog: SkillAwareToolCatalog
    selector: SkillSelector


def build_skills(task_repository: SqlAlchemyTaskRepository, memory_service: MemoryService) -> list[Skill]:
    """Composition root for capabilities. Adding a skill means adding one line here."""
    return [
        TaskSkill(task_repository),
        MemorySkill(
            search_memories=SearchMemoriesUseCase(memory_service),
            get_memory=GetMemoryUseCase(memory_service),
            save_memory=SaveMemoryUseCase(memory_service),
            delete_memory=DeleteMemoryUseCase(memory_service),
        ),
    ]


def build_skill_system(session: Session, selector: SkillSelector | None = None) -> SkillSystem:
    tools = InMemoryToolRegistry()
    skills = SkillRegistry(tools)
    memory_service = MemoryService(
        SqlAlchemyMemoryRepository(session),
        DeterministicMemoryPolicy(),
        MemoryFirewall(),
    )
    for skill in build_skills(SqlAlchemyTaskRepository(session), memory_service):
        skills.register(skill)
    skill_selector = selector or KeywordSkillSelector()
    return SkillSystem(
        skills=skills,
        tools=tools,
        catalog=SkillAwareToolCatalog(skills, tools, skill_selector),
        selector=skill_selector,
    )


def skill_system_dependency(session: Session = Depends(session_dependency)) -> SkillSystem:
    return build_skill_system(session)


def build_orchestrator(
    session: Session,
    system: SkillSystem,
    trust_engine: TrustEngine,
    approval_service: ApprovalService,
) -> AgentOrchestrator:
    """Wire the agent pipeline for one session.

    Extracted from the FastAPI dependency so the Always-On background loop can
    build *the same* orchestrator against its own long-lived session. That reuse
    is the point: a scheduled run must go through the identical Trust Engine,
    approval service and sandboxed executor as an interactive one, and a second
    wiring of this graph would be a second, unaudited execution path.
    """
    # The orchestrator's executor is the sandboxing one, not the raw registry
    # executor. Phase 10 existed as a composition-root builder that nothing
    # called, so every tool ran in the API process and no sandbox was ever
    # created. The registry executor stays underneath as the delegate, which is
    # what keeps non-sandboxed tools behaving exactly as they did in Phases 1-9.
    return AgentOrchestrator(
        agent_brain=RuleBasedAgentBrain(),
        context_builder=AgentContextBuilder(SqlAlchemyMemoryRepository(session), system.tools),
        tool_registry=system.tools,
        tool_executor=build_runtime_tool_executor(
            delegate=RegistryToolExecutor(system.tools),
            definitions={
                definition.name: definition for definition in system.tools.definitions()
            },
        ),
        trust_engine=trust_engine,
        agent_run_repository=SqlAlchemyAgentRunRepository(session),
        agent_action_repository=SqlAlchemyAgentActionRepository(session),
        approval_service=approval_service,
        tool_catalog=system.catalog,
        # The Plan Validator runs before the Trust Engine on every action. It was
        # implemented and then never constructed, so the gate existed only in the
        # test suite. Wired here so the pipeline is the documented one.
        plan_validator=DefaultPlanValidator(max_actions=get_settings().agent_max_iterations),
        security_audit=get_security_audit(),
        max_iterations=get_settings().agent_max_iterations,
        max_tool_calls=get_settings().agent_max_tool_calls,
        max_permission_requests=get_settings().agent_max_permission_requests,
        max_denied_actions=get_settings().agent_max_denied_actions,
        max_runtime_seconds=float(get_settings().agent_max_runtime_seconds),
    )


def orchestrator_dependency(
    system: SkillSystem = Depends(skill_system_dependency),
    session: Session = Depends(session_dependency),
    trust_engine: TrustEngine = Depends(get_trust_engine),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> AgentOrchestrator:
    return build_orchestrator(session, system, trust_engine, approval_service)
