from dataclasses import dataclass

from app.application.memory.delete_memory import DeleteMemoryUseCase
from app.application.memory.get_memory import GetMemoryUseCase
from app.application.memory.save_memory import SaveMemoryUseCase
from app.application.memory.search_memories import SearchMemoriesUseCase
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.memory.tools.contracts import SKILL_NAME
from app.infrastructure.skills.memory.tools.delete_memory import MemoryDeleteTool
from app.infrastructure.skills.memory.tools.get_memory import MemoryGetTool
from app.infrastructure.skills.memory.tools.save_memory import MemorySaveTool
from app.infrastructure.skills.memory.tools.search_memory import MemorySearchTool

KEYWORDS = ("memoria", "memorias", "memory", "memorize", "recuerda", "recordar", "remember")


@dataclass
class MemorySkill(Skill):
    search_memories: SearchMemoriesUseCase
    get_memory: GetMemoryUseCase
    save_memory: SaveMemoryUseCase
    delete_memory: DeleteMemoryUseCase

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Search and manage the user's memories.",
            version="1.0.0",
            enabled=True,
            category="knowledge",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        return [
            MemorySearchTool(self.search_memories),
            MemoryGetTool(self.get_memory),
            MemorySaveTool(self.save_memory),
            MemoryDeleteTool(self.delete_memory),
        ]
