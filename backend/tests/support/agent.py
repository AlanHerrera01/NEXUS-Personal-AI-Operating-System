import asyncio

from app.application.agents.context_builder import AgentContextBuilder
from app.application.agents.orchestrator import AgentOrchestrator
from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.memory.firewall import MemoryFirewall
from app.application.memory.get_memory import GetMemoryUseCase
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.memory.search_memories import SearchMemoriesUseCase
from app.application.memory.service import MemoryService
from app.application.skills.catalog import SkillAwareToolCatalog
from app.application.skills.registry import SkillRegistry
from app.application.skills.selector import KeywordSkillSelector
from app.application.tools.executor import RegistryToolExecutor
from app.application.tools.registry import InMemoryToolRegistry
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_action_repository import AgentActionRepository
from app.domain.ports.agent_brain import AgentBrain, AgentDecision
from app.domain.ports.skill import Skill
from app.domain.ports.skill_selector import SkillSelector
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.infrastructure.security.trust_engine import DeterministicTrustEngine
from app.infrastructure.skills.memory.skill import MemorySkill
from app.infrastructure.skills.tasks.skill import TaskSkill


class ScriptedAgentBrain(AgentBrain):
    """Fake brain: no LLM, no credits, just the decisions the test declares."""

    def __init__(self, *decisions: AgentDecision, final: AgentDecision | None = None) -> None:
        self.decisions = list(decisions)
        self.final = final or AgentDecision.final("done")
        self.seen_tools: list[str] = []

    async def decide(self, agent_run, context, tool_definitions):
        self.seen_tools = [definition.name for definition in tool_definitions]
        return self.decisions.pop(0) if self.decisions else self.final


class FakeRunRepository(AgentRunRepository):
    def __init__(self) -> None:
        self.items: dict[object, AgentRun] = {}

    def save(self, run: AgentRun) -> AgentRun:
        self.items[run.id] = run
        return run

    def get_by_id(self, run_id):
        return self.items.get(run_id)


class FakeActionRepository(AgentActionRepository):
    def __init__(self) -> None:
        self.items: dict[object, AgentAction] = {}

    def save(self, action: AgentAction) -> AgentAction:
        self.items[action.id] = action
        return action

    def list_by_run(self, agent_run_id):
        return [action for action in self.items.values() if action.agent_run_id == agent_run_id]


def memory_skill(service: MemoryService) -> MemorySkill:
    return MemorySkill(
        search_memories=SearchMemoriesUseCase(service),
        get_memory=GetMemoryUseCase(service),
        save_memory=SaveMemoryUseCase(service),
        delete_memory=DeleteMemoryUseCase(service),
    )


def build_agent(
    skills: list[Skill],
    brain: AgentBrain,
    selector: SkillSelector | None = None,
) -> tuple[AgentOrchestrator, SkillRegistry, InMemoryToolRegistry, FakeRunRepository, FakeActionRepository]:
    tools = InMemoryToolRegistry()
    skill_registry = SkillRegistry(tools)
    for skill in skills:
        skill_registry.register(skill)
    runs = FakeRunRepository()
    actions = FakeActionRepository()
    orchestrator = AgentOrchestrator(
        agent_brain=brain,
        context_builder=AgentContextBuilder(None, tools),
        tool_registry=tools,
        tool_executor=RegistryToolExecutor(tools),
        trust_engine=DeterministicTrustEngine(),
        agent_run_repository=runs,
        agent_action_repository=actions,
        tool_catalog=SkillAwareToolCatalog(skill_registry, tools, selector or KeywordSkillSelector()),
    )
    return orchestrator, skill_registry, tools, runs, actions


def run_async(coroutine):
    return asyncio.run(coroutine)
