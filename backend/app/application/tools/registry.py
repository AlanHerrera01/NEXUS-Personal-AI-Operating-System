from collections.abc import Collection

from app.domain.ports.tool import Tool, ToolDefinition
from app.domain.ports.tool_registry import ToolRegistry


class InMemoryToolRegistry(ToolRegistry):
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        name = tool.definition().name
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool
        return tool

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition() for tool in self._tools.values()]

    def list_available(self, skill_names: Collection[str] | None = None) -> list[ToolDefinition]:
        definitions = self.definitions()
        if skill_names is None:
            return definitions
        wanted = set(skill_names)
        return [definition for definition in definitions if definition.skill_name in wanted]
