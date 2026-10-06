from dataclasses import dataclass

from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.domain.repositories.task_repository import TaskRepository
from app.infrastructure.skills.tasks.tools.complete_task import TaskCompleteTool
from app.infrastructure.skills.tasks.tools.contracts import SKILL_NAME
from app.infrastructure.skills.tasks.tools.create_task import TaskCreateTool
from app.infrastructure.skills.tasks.tools.get_task import TaskGetTool
from app.infrastructure.skills.tasks.tools.list_tasks import TaskListTool
from app.infrastructure.skills.tasks.tools.update_task import TaskUpdateTool

KEYWORDS = ("tarea", "tareas", "task", "todo", "to-do", "recordatorio", "pendiente")


@dataclass
class TaskSkill(Skill):
    repository: TaskRepository

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Manage the user's tasks.",
            version="1.0.0",
            enabled=True,
            category="productivity",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        return [
            TaskCreateTool(self.repository),
            TaskListTool(self.repository),
            TaskGetTool(self.repository),
            TaskUpdateTool(self.repository),
            TaskCompleteTool(self.repository),
        ]
