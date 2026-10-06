from app.domain.ports.skill import SkillCatalog
from app.domain.ports.skill_selector import SkillSelector
from app.domain.ports.tool import ToolDefinition
from app.domain.ports.tool_catalog import ToolCatalog
from app.domain.ports.tool_registry import ToolRegistry
from app.domain.value_objects.skill_permission import SkillPermission


class SkillAwareToolCatalog(ToolCatalog):
    """Resolves the tools an agent may use: enabled, relevant and granted skills."""

    def __init__(self, skills: SkillCatalog, tools: ToolRegistry, selector: SkillSelector) -> None:
        self.skills = skills
        self.tools = tools
        self.selector = selector

    def available_definitions(self, request: str) -> list[ToolDefinition]:
        selected = self.selector.select(request, self.skills.definitions())
        granted = {permission.skill_name: permission for permission in self.skills.permissions()}
        definitions = self.tools.list_available({definition.name for definition in selected})
        return [
            definition
            for definition in definitions
            if _is_granted(granted.get(definition.skill_name), definition.action)
        ]

    def available_skill_names(self, request: str) -> list[str]:
        return [definition.name for definition in self.selector.select(request, self.skills.definitions())]


def _is_granted(permission: SkillPermission | None, action: str) -> bool:
    return permission is None or permission.allows(action)
