import pytest

from app.application.skills.registry import SkillRegistry
from app.application.tools.registry import InMemoryToolRegistry
from tests.unit.application.test_skill_registry import DemoSkill, EchoTool


def test_register_and_get_tool() -> None:
    registry = InMemoryToolRegistry()
    tool = EchoTool()

    assert registry.register(tool) is tool
    assert registry.get("demo.echo") is tool
    assert registry.get("missing.echo") is None


def test_register_tool_on_construction() -> None:
    registry = InMemoryToolRegistry([EchoTool("demo.echo"), EchoTool("demo.other")])

    assert [definition.name for definition in registry.definitions()] == ["demo.echo", "demo.other"]


def test_duplicate_tool_is_rejected() -> None:
    registry = InMemoryToolRegistry([EchoTool()])

    with pytest.raises(ValueError, match="tool already registered"):
        registry.register(EchoTool())


def test_unregister_removes_the_tool() -> None:
    registry = InMemoryToolRegistry([EchoTool()])

    assert registry.unregister("demo.echo") is True
    assert registry.unregister("demo.echo") is False
    assert registry.get("demo.echo") is None


def test_list_available_filters_by_skill() -> None:
    registry = InMemoryToolRegistry([EchoTool("tasks.list", "tasks"), EchoTool("memory.search", "memory")])

    assert [definition.name for definition in registry.list_available(["memory"])] == ["memory.search"]
    assert [definition.name for definition in registry.definitions_for_skill("tasks")] == ["tasks.list"]
    assert len(registry.list_available()) == 2


def test_tools_of_a_disabled_skill_are_not_listed() -> None:
    registry = InMemoryToolRegistry()
    skills = SkillRegistry(registry)
    skills.register(DemoSkill("tasks"))
    skills.register(DemoSkill("memory"))

    skills.disable("memory")

    assert [definition.name for definition in registry.list_available()] == ["tasks.echo"]
    assert [definition.name for definition in registry.list_available(["memory"])] == []
    assert [tool.definition().name for tool in skills.tools_for("memory")] == []


def test_tool_metadata_is_complete() -> None:
    registry = InMemoryToolRegistry([EchoTool("tasks.list", "tasks")])

    definition = registry.definitions()[0]

    assert definition.name == "tasks.list"
    assert definition.action == "list"
    assert definition.skill_name == "tasks"
    assert definition.risk_level is not None
    assert definition.read_only is True
    assert definition.side_effect is False
    assert definition.input_schema["type"] == "object"
