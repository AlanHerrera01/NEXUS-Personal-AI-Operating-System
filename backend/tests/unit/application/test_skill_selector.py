import pytest

from app.application.skills.catalog import SkillAwareToolCatalog
from app.application.skills.registry import SkillRegistry
from app.application.skills.selector import AllEnabledSkillSelector, KeywordSkillSelector
from app.application.tools.registry import InMemoryToolRegistry
from app.domain.ports.skill import SkillDefinition
from app.domain.ports.tool import ToolDefinition
from app.domain.value_objects.risk_level import RiskLevel
from tests.unit.application.test_skill_registry import DemoSkill, EchoTool


def build_catalog(selector=None) -> tuple[SkillAwareToolCatalog, SkillRegistry]:
    tools = InMemoryToolRegistry()
    skills = SkillRegistry(tools)
    skills.register(DemoSkill("tasks", keywords=("task", "tarea")))
    skills.register(DemoSkill("memory", keywords=("memory", "memoria")))
    catalog = SkillAwareToolCatalog(skills, tools, selector or KeywordSkillSelector())
    return catalog, skills


def test_selector_matches_only_relevant_skills() -> None:
    catalog, _ = build_catalog()

    available = catalog.available_definitions("create a new task")

    assert [definition.name for definition in available] == ["tasks.echo"]


def test_selector_falls_back_to_every_enabled_skill() -> None:
    catalog, _ = build_catalog()

    available = catalog.available_definitions("something completely unrelated")

    assert {definition.name for definition in available} == {"tasks.echo", "memory.echo"}


def test_selector_can_be_strict() -> None:
    catalog, _ = build_catalog(KeywordSkillSelector(fallback_to_all=False))

    assert catalog.available_definitions("something unrelated") == []


def test_disabled_skills_are_never_offered() -> None:
    catalog, skills = build_catalog()
    skills.disable("memory")

    available = catalog.available_definitions("task and memory")

    assert [definition.name for definition in available] == ["tasks.echo"]


def test_registry_with_only_disabled_skills_offers_nothing() -> None:
    tools = InMemoryToolRegistry()
    skills = SkillRegistry(tools)
    skills.register(DemoSkill("tasks", enabled=False))
    catalog = SkillAwareToolCatalog(skills, tools, KeywordSkillSelector())

    assert catalog.available_definitions("anything") == []


def test_all_enabled_selector_exposes_every_enabled_skill() -> None:
    catalog, skills = build_catalog(AllEnabledSkillSelector())
    skills.disable("memory")

    assert {definition.name for definition in catalog.available_definitions("")} == {"tasks.echo"}


def test_available_skill_names_are_reported() -> None:
    catalog, _ = build_catalog()

    assert catalog.available_skill_names("search my memory") == ["memory"]


def test_selection_ignores_disabled_definitions() -> None:
    selector = KeywordSkillSelector()

    selected = selector.select(
        "task",
        [
            SkillDefinition("tasks", "Tasks", enabled=True),
            SkillDefinition("memory", "Memory", enabled=False, keywords=("task",)),
        ],
    )

    assert [definition.name for definition in selected] == ["tasks"]


def test_skill_definition_requires_a_name() -> None:
    with pytest.raises(ValueError):
        SkillDefinition("  ", "Tasks")


def test_tool_definition_must_be_namespaced() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        ToolDefinition("create", "Create", {"type": "object"}, "tasks", RiskLevel.LOW)
