import pytest

from app.application.skills.registry import SkillRegistry
from app.application.tools.registry import InMemoryToolRegistry
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool, ToolContext, ToolDefinition, ToolInput, ToolOutput, ToolResult
from app.domain.value_objects.risk_level import RiskLevel


class EchoInput(ToolInput):
    value: str = ""


class EchoOutput(ToolOutput):
    value: str = ""


class EchoTool(Tool):
    def __init__(self, name: str = "demo.echo", skill_name: str = "demo") -> None:
        self._definition = ToolDefinition(
            name=name,
            description="Echo",
            input_schema={"type": "object", "properties": {}},
            skill_name=skill_name,
            risk_level=RiskLevel.LOW,
            read_only=True,
        )

    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        return ToolResult(True, self._definition.name, {"value": "echo"})


class DemoSkill(Skill):
    def __init__(
        self,
        name: str = "demo",
        enabled: bool = True,
        tools: list[Tool] | None = None,
        keywords: tuple[str, ...] | None = None,
    ) -> None:
        self._definition = SkillDefinition(
            name=name,
            description="Demo capability",
            version="1.0.0",
            enabled=enabled,
            keywords=keywords if keywords is not None else (name,),
        )
        self._tools = tools if tools is not None else [EchoTool(f"{name}.echo", name)]

    def definition(self) -> SkillDefinition:
        return self._definition

    def tools(self) -> list[Tool]:
        return self._tools


@pytest.fixture
def tool_registry() -> InMemoryToolRegistry:
    return InMemoryToolRegistry()


@pytest.fixture
def skills(tool_registry: InMemoryToolRegistry) -> SkillRegistry:
    return SkillRegistry(tool_registry)


def test_register_skill_publishes_its_tools(skills: SkillRegistry, tool_registry: InMemoryToolRegistry) -> None:
    skills.register(DemoSkill())

    assert skills.names() == ["demo"]
    assert skills.get("demo") is not None
    assert [definition.name for definition in tool_registry.definitions()] == ["demo.echo"]
    assert [tool.definition().name for tool in skills.tools_for("demo")] == ["demo.echo"]


def test_get_and_list_skills(skills: SkillRegistry) -> None:
    skills.register(DemoSkill("tasks"))
    skills.register(DemoSkill("memory"))

    definitions = skills.definitions()

    assert [definition.name for definition in definitions] == ["tasks", "memory"]
    assert all(definition.enabled for definition in definitions)
    assert skills.get("unknown") is None


def test_duplicate_skill_is_rejected(skills: SkillRegistry) -> None:
    skills.register(DemoSkill("demo"))

    with pytest.raises(ValueError, match="skill already registered"):
        skills.register(DemoSkill("demo"))


def test_unknown_skill_lookup_returns_nothing(skills: SkillRegistry) -> None:
    assert skills.get("calendar") is None
    assert skills.is_enabled("calendar") is False
    assert skills.tools_for("calendar") == []
    with pytest.raises(KeyError):
        skills.enable("calendar")
    with pytest.raises(KeyError):
        skills.disable("calendar")


def test_disabled_skill_is_not_exposed_to_the_agent(
    skills: SkillRegistry, tool_registry: InMemoryToolRegistry
) -> None:
    skills.register(DemoSkill("demo", enabled=False))

    assert skills.is_enabled("demo") is False
    assert skills.tools_for("demo") == []
    assert tool_registry.definitions() == []


def test_disabled_skill_can_be_enabled_and_disabled_at_runtime(
    skills: SkillRegistry, tool_registry: InMemoryToolRegistry
) -> None:
    skills.register(DemoSkill("demo", enabled=False))

    skills.enable("demo")
    assert skills.is_enabled("demo") is True
    assert tool_registry.get("demo.echo") is not None

    skills.disable("demo")
    assert skills.is_enabled("demo") is False
    assert tool_registry.get("demo.echo") is None
    assert tool_registry.definitions() == []


def test_enabling_and_disabling_twice_is_idempotent(skills: SkillRegistry, tool_registry: InMemoryToolRegistry) -> None:
    skills.register(DemoSkill("demo"))

    skills.enable("demo")
    skills.disable("demo")
    skills.disable("demo")
    skills.enable("demo")

    assert [definition.name for definition in tool_registry.definitions()] == ["demo.echo"]


def test_skill_cannot_own_tools_of_another_skill(skills: SkillRegistry) -> None:
    foreign = EchoTool("other.echo", "other")

    with pytest.raises(ValueError, match="does not belong to skill"):
        skills.register(DemoSkill("demo", tools=[foreign]))


def test_skill_cannot_expose_duplicate_tools(skills: SkillRegistry) -> None:
    duplicated = [EchoTool("demo.echo", "demo"), EchoTool("demo.echo", "demo")]

    with pytest.raises(ValueError, match="duplicated tool"):
        skills.register(DemoSkill("demo", tools=duplicated))
