from app.domain.ports.skill import Skill, SkillCatalog, SkillDefinition
from app.domain.ports.tool import Tool
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.value_objects.skill_permission import SkillPermission


class SkillRegistry(SkillCatalog):
    """Registers skills and keeps the tool registry in sync with their enabled state."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry
        self._skills: dict[str, Skill] = {}
        self._enabled: dict[str, bool] = {}

    def register(self, skill: Skill) -> Skill:
        definition = skill.definition()
        if definition.name in self._skills:
            raise ValueError(f"skill already registered: {definition.name}")
        tools = skill.tools()
        self._validate_tools(definition, tools)
        self._skills[definition.name] = skill
        self._enabled[definition.name] = definition.enabled
        if definition.enabled:
            self._publish(definition.name)
        return skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def definitions(self) -> list[SkillDefinition]:
        return [
            SkillDefinition(
                name=definition.name,
                description=definition.description,
                version=definition.version,
                enabled=self._enabled[definition.name],
                category=definition.category,
                keywords=definition.keywords,
                metadata=definition.metadata,
            )
            for definition in (skill.definition() for skill in self._skills.values())
        ]

    def names(self) -> list[str]:
        return list(self._skills)

    def is_enabled(self, name: str) -> bool:
        return bool(self._enabled.get(name, False))

    def enable(self, name: str) -> None:
        skill = self._require(name)
        if self._enabled[name]:
            return
        self._enabled[name] = True
        self._publish(name)

    def disable(self, name: str) -> None:
        self._require(name)
        if not self._enabled[name]:
            return
        self._enabled[name] = False
        self._withdraw(name)

    def tools_for(self, skill_name: str) -> list[Tool]:
        skill = self._skills.get(skill_name)
        if skill is None or not self.is_enabled(skill_name):
            return []
        return skill.tools()

    def permissions(self) -> list[SkillPermission]:
        return [permission for skill in self._skills.values() for permission in skill.permissions()]

    def _require(self, name: str) -> Skill:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"unknown skill: {name}")
        return skill

    def _publish(self, name: str) -> None:
        for tool in self._skills[name].tools():
            self.tool_registry.register(tool)

    def _withdraw(self, name: str) -> None:
        for tool in self._skills[name].tools():
            self.tool_registry.unregister(tool.definition().name)

    @staticmethod
    def _validate_tools(definition: SkillDefinition, tools: list[Tool]) -> None:
        seen: set[str] = set()
        for tool in tools:
            tool_definition = tool.definition()
            if tool_definition.skill_name != definition.name:
                raise ValueError(
                    f"tool {tool_definition.name} does not belong to skill {definition.name}"
                )
            if tool_definition.name in seen:
                raise ValueError(f"duplicated tool inside skill {definition.name}: {tool_definition.name}")
            seen.add(tool_definition.name)
