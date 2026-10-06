"""Open/Closed proof: a new Skill is usable without touching the agent core."""

import inspect
import pkgutil

import pytest

from app.application.agents.orchestrator import AgentOrchestrator
from app.domain.entities.agent_run import AgentRun
from app.domain.ports.agent_brain import AgentDecision
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool, ToolContext, ToolDefinition, ToolInput, ToolOutput, ToolResult
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel
from app.infrastructure.skills.tasks.skill import TaskSkill
from tests.support.agent import ScriptedAgentBrain, build_agent, run_async
from tests.support.repositories import FakeTaskRepository


class EchoInput(ToolInput):
    message: str


class EchoOutput(ToolOutput):
    echoed: str


class EchoTool(Tool):
    """A brand new action, written from scratch, with no core changes."""

    def __init__(self) -> None:
        self._definition = ToolDefinition(
            name="test.echo",
            description="Echo a message back to the caller.",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Message to echo"}},
                "required": ["message"],
                "additionalProperties": False,
            },
            skill_name="test",
            risk_level=RiskLevel.LOW,
            read_only=True,
            category="testing",
        )

    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        payload = EchoInput.model_validate(arguments)
        return ToolResult(True, "test.echo", EchoOutput(echoed=payload.message).model_dump())


class TestSkill(Skill):
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name="test",
            description="Testing capability used to prove extensibility.",
            version="1.0.0",
            enabled=True,
            keywords=("echo", "test"),
        )

    def tools(self) -> list[Tool]:
        return [EchoTool()]


def test_agent_uses_a_new_skill_registered_at_composition_time() -> None:
    brain = ScriptedAgentBrain(
        AgentDecision.tool_call("test.echo", {"message": "hola NEXUS"}),
        final=AgentDecision.final("echoed"),
    )
    orchestrator, skills, tools, _, _ = build_agent([TaskSkill(FakeTaskRepository()), TestSkill()], brain)

    result = run_async(orchestrator.execute(AgentRun(agent_id=EntityId.new(), user_request="echo hola NEXUS")))

    assert result.response == "echoed"
    assert result.observations[0].output == {"echoed": "hola NEXUS"}
    assert skills.is_enabled("test") is True
    assert tools.get("test.echo") is not None
    assert brain.seen_tools == ["test.echo"]


def test_new_skill_appears_in_the_catalog_and_can_be_disabled() -> None:
    brain = ScriptedAgentBrain()
    _, skills, tools, _, _ = build_agent([TestSkill()], brain)

    assert [definition.name for definition in skills.definitions()] == ["test"]
    assert [definition.name for definition in tools.definitions()] == ["test.echo"]

    skills.disable("test")

    assert tools.definitions() == []


def test_agent_core_has_no_knowledge_of_concrete_skills() -> None:
    source = inspect.getsource(AgentOrchestrator)

    for forbidden in ("task.", "memory.", "TaskSkill", "MemorySkill", "SkillRegistry", "github.", "calendar."):
        assert forbidden not in source


def test_new_skill_does_not_require_changing_the_brain_or_planner() -> None:
    brain = ScriptedAgentBrain(AgentDecision.tool_call("test.echo", {"message": "x"}))
    orchestrator, _, _, _, _ = build_agent([TestSkill()], brain)

    assert orchestrator.tool_catalog is not None
    assert [definition.name for definition in orchestrator.available_tools("echo")] == ["test.echo"]


@pytest.mark.parametrize("skill_name", ["calendar", "github", "documents", "web"])
def test_external_integrations_are_not_implemented_yet(skill_name: str) -> None:
    import app.infrastructure.skills as skills_package

    available = {package.name for package in pkgutil.iter_modules(skills_package.__path__)}

    assert available == {"tasks", "memory"}
    assert skill_name not in available
