"""Agent -> ToolCatalog -> Skill -> Tool -> UseCase -> Repository, without any LLM."""

import pytest

from app.application.memory.firewall import MemoryFirewall
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.service import MemoryService
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentDecision
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.tasks.skill import TaskSkill
from tests.support.agent import ScriptedAgentBrain, build_agent, memory_skill, run_async
from tests.support.repositories import FakeTaskRepository, make_task
from tests.unit.application.test_memory_system import FakeMemoryRepository


@pytest.fixture
def task_repository() -> FakeTaskRepository:
    return FakeTaskRepository()


@pytest.fixture
def memory_repository() -> FakeMemoryRepository:
    return FakeMemoryRepository()


@pytest.fixture
def memory_service(memory_repository: FakeMemoryRepository) -> MemoryService:
    return MemoryService(memory_repository, DeterministicMemoryPolicy(), MemoryFirewall())


def test_agent_creates_a_task_through_the_task_skill(task_repository: FakeTaskRepository) -> None:
    brain = ScriptedAgentBrain(
        AgentDecision.tool_call("task.create", {"title": "Revisar NEXUS"}),
        final=AgentDecision.final("Tarea creada"),
    )
    orchestrator, _, tools, _, actions = build_agent([TaskSkill(task_repository)], brain)
    run = AgentRun(agent_id=EntityId.new(), user_request="Crea una tarea llamada revisar NEXUS")

    result = run_async(orchestrator.execute(run))

    assert result.response == "Tarea creada"
    assert run.status is AgentRunStatus.COMPLETED
    assert len(task_repository.items) == 1
    assert next(iter(task_repository.items.values())).title == "Revisar NEXUS"
    assert [action.action_name for action in actions.list_by_run(run.id)] == ["task.create"]
    assert "task.create" in brain.seen_tools
    assert tools.get("task.create") is not None


def test_agent_reports_a_structured_tool_error_to_the_brain(task_repository: FakeTaskRepository) -> None:
    brain = ScriptedAgentBrain(
        AgentDecision.tool_call("task.get", {"task_id": str(EntityId.new())}),
        final=AgentDecision.final("No encontré esa tarea"),
    )
    orchestrator, _, _, _, _ = build_agent([TaskSkill(task_repository)], brain)
    run = AgentRun(agent_id=EntityId.new(), user_request="busca una tarea")

    result = run_async(orchestrator.execute(run))

    observation = result.observations[0]
    assert observation.success is False
    assert "TASK_NOT_FOUND" in observation.error
    assert "Traceback" not in observation.error


def test_agent_is_not_offered_tools_from_unrelated_skills(
    task_repository: FakeTaskRepository, memory_service: MemoryService
) -> None:
    brain = ScriptedAgentBrain(final=AgentDecision.final("ok"))
    orchestrator, _, _, _, _ = build_agent([TaskSkill(task_repository), memory_skill(memory_service)], brain)
    run = AgentRun(agent_id=EntityId.new(), user_request="Crea una tarea para revisar NEXUS")

    run_async(orchestrator.execute(run))

    assert brain.seen_tools == [
        "task.create",
        "task.list",
        "task.get",
        "task.update",
        "task.complete",
    ]


def test_agent_cannot_call_a_tool_outside_the_selected_skills(
    task_repository: FakeTaskRepository, memory_service: MemoryService
) -> None:
    brain = ScriptedAgentBrain(AgentDecision.tool_call("memory.search", {"query": "postgres"}))
    orchestrator, _, _, _, _ = build_agent([TaskSkill(task_repository), memory_skill(memory_service)], brain)
    run = AgentRun(agent_id=EntityId.new(), user_request="Crea una tarea")

    result = run_async(orchestrator.execute(run))

    assert result.response == "Requested tool is not available"
    assert result.observations == []


def test_agent_saves_a_memory_through_the_memory_skill(memory_service: MemoryService, memory_repository) -> None:
    brain = ScriptedAgentBrain(
        AgentDecision.tool_call(
            "memory.save",
            {"content": "The project uses PostgreSQL", "memory_type": "SEMANTIC"},
        ),
        final=AgentDecision.final("Recordado"),
    )
    orchestrator, _, _, _, _ = build_agent([memory_skill(memory_service)], brain)
    run = AgentRun(
        agent_id=EntityId.new(),
        user_request="Recuerda que mi proyecto usa PostgreSQL",
    )

    result = run_async(orchestrator.execute(run))

    assert result.response == "Recordado"
    assert len(memory_repository.items) == 1
    memory = next(iter(memory_repository.items.values()))
    assert memory.agent_id == run.agent_id
    assert memory.content == "The project uses PostgreSQL"


def test_memory_policy_still_decides_when_the_agent_asks_to_remember(
    memory_service: MemoryService, memory_repository: FakeMemoryRepository
) -> None:
    brain = ScriptedAgentBrain(
        AgentDecision.tool_call("memory.save", {"content": "hi", "memory_type": "SEMANTIC"}),
    )
    orchestrator, _, _, _, _ = build_agent([memory_skill(memory_service)], brain)
    run = AgentRun(agent_id=EntityId.new(), user_request="Recuerda algo")

    result = run_async(orchestrator.execute(run))

    assert result.observations[0].success is True
    assert result.observations[0].output["saved"] is False
    assert result.observations[0].output["persistence"] == "DO_NOT_SAVE"
    assert memory_repository.items == {}


def test_agent_lists_tasks_of_its_own_agent_only(task_repository: FakeTaskRepository) -> None:
    task_repository.save(make_task(EntityId.new(), "Task of another agent"))
    brain = ScriptedAgentBrain(AgentDecision.tool_call("task.list", {}))
    orchestrator, _, _, _, _ = build_agent([TaskSkill(task_repository)], brain)
    agent_id = EntityId.new()
    task_repository.save(make_task(agent_id, "My task"))
    run = AgentRun(agent_id=agent_id, user_request="lista mis tareas")

    result = run_async(orchestrator.execute(run))

    assert result.observations[0].output["count"] == 1
    assert result.observations[0].output["items"][0]["title"] == "My task"


def test_disabling_a_skill_removes_its_tools_from_the_agent(task_repository: FakeTaskRepository) -> None:
    brain = ScriptedAgentBrain(AgentDecision.tool_call("task.create", {"title": "x"}))
    orchestrator, skills, tools, _, _ = build_agent([TaskSkill(task_repository)], brain)
    skills.disable("tasks")

    result = run_async(orchestrator.execute(AgentRun(agent_id=EntityId.new(), user_request="crea una tarea")))

    assert tools.definitions() == []
    assert result.response == "Requested tool is not available"
    assert task_repository.items == {}


def test_agent_context_carries_a_trusted_tool_context(task_repository: FakeTaskRepository) -> None:
    seen: list[object] = []

    class SpyTaskSkill(TaskSkill):
        def tools(self):
            tools = super().tools()
            original = tools[0].execute

            async def spy(arguments, context):
                seen.append(context)
                return await original(arguments, context)

            tools[0].execute = spy
            return tools

    brain = ScriptedAgentBrain(AgentDecision.tool_call("task.create", {"title": "x"}))
    orchestrator, _, _, _, _ = build_agent([SpyTaskSkill(task_repository)], brain)
    agent_id = EntityId.new()
    run = AgentRun(agent_id=agent_id, user_request="crea una tarea")

    run_async(orchestrator.execute(run))

    context = seen[0]
    assert context.agent_id == agent_id
    assert context.agent_run_id == run.id
    assert context.user_request == "crea una tarea"
    assert context.correlation_id == str(run.id)
    assert context.skill_names == frozenset({"tasks"})
