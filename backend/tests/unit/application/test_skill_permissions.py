import pytest

from app.application.skills.catalog import SkillAwareToolCatalog
from app.application.skills.registry import SkillRegistry
from app.application.skills.selector import KeywordSkillSelector
from app.application.tools.registry import InMemoryToolRegistry
from app.domain.ports.skill import Skill
from app.domain.ports.tool import Tool, ToolContext, ToolDefinition, ToolResult
from app.domain.value_objects.skill_permission import SkillPermission
from tests.unit.application.test_skill_registry import EchoTool


class ReadOnlyDemoSkill(Skill):
    def __init__(self, actions: frozenset[str]) -> None:
        self._permission = SkillPermission("demo", actions=actions)

    def definition(self):
        from app.domain.ports.skill import SkillDefinition

        return SkillDefinition("demo", "Demo capability", keywords=("demo",))

    def tools(self) -> list[Tool]:
        return [EchoTool("demo.read", "demo"), EchoTool("demo.write", "demo")]

    def permissions(self) -> tuple[SkillPermission, ...]:
        return (self._permission,)


def build(skill: Skill) -> SkillAwareToolCatalog:
    tools = InMemoryToolRegistry()
    skills = SkillRegistry(tools)
    skills.register(skill)
    return SkillAwareToolCatalog(skills, tools, KeywordSkillSelector())


def test_skill_without_permissions_exposes_every_action() -> None:
    from tests.unit.application.test_skill_registry import DemoSkill

    catalog = build(DemoSkill("demo"))

    assert [definition.action for definition in catalog.available_definitions("demo")] == ["echo"]


def test_skill_permissions_restrict_the_actions_exposed_to_the_agent() -> None:
    catalog = build(ReadOnlyDemoSkill(frozenset({"read"})))

    assert [definition.action for definition in catalog.available_definitions("demo")] == ["read"]


def test_wildcard_permission_allows_every_action() -> None:
    catalog = build(ReadOnlyDemoSkill(frozenset({"*"})))

    assert len(catalog.available_definitions("demo")) == 2


def test_revoked_skill_exposes_nothing() -> None:
    class RevokedSkill(ReadOnlyDemoSkill):
        def permissions(self) -> tuple[SkillPermission, ...]:
            return (SkillPermission("demo", actions=frozenset({"read"}), granted=False),)

    catalog = build(RevokedSkill(frozenset({"read"})))

    assert catalog.available_definitions("demo") == []


def test_registry_exposes_skill_permissions() -> None:
    tools = InMemoryToolRegistry()
    skills = SkillRegistry(tools)
    skills.register(ReadOnlyDemoSkill(frozenset({"read"})))

    assert [permission.skill_name for permission in skills.permissions()] == ["demo"]


def test_skill_permission_requires_a_name() -> None:
    with pytest.raises(ValueError):
        SkillPermission("  ")
