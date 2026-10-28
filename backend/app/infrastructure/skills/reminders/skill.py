from dataclasses import dataclass

from app.application.reminders.create_reminder import CreateReminderUseCase
from app.application.reminders.list_reminders import ListRemindersUseCase
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.domain.repositories.reminder_repository import ReminderRepository
from app.infrastructure.skills.reminders.tools.contracts import SKILL_NAME
from app.infrastructure.skills.reminders.tools.create import CreateReminderTool
from app.infrastructure.skills.reminders.tools.list import ListRemindersTool

KEYWORDS = (
    "recordatorio",
    "recordatorios",
    "recordame",
    "recordar",
    "remind",
    "reminder",
    "alarma",
    "aviso",
    "avísame",
    "avisame",
)


@dataclass
class ReminderSkill(Skill):
    repository: ReminderRepository

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Create and list one-shot, time-based reminders.",
            version="1.0.0",
            enabled=True,
            category="reminders",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        return [
            CreateReminderTool(CreateReminderUseCase(self.repository)),
            ListRemindersTool(ListRemindersUseCase(self.repository)),
        ]
