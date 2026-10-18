from dataclasses import dataclass

from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.domain.repositories.calendar_event_repository import CalendarEventRepository
from app.infrastructure.skills.calendar.tools.contracts import SKILL_NAME
from app.infrastructure.skills.calendar.tools.create_event import CreateCalendarEventTool
from app.infrastructure.skills.calendar.tools.list_events import ListCalendarEventsTool


@dataclass
class CalendarSkill(Skill):
    """The user's own calendar, stored in NEXUS.

    Backed by a repository like Tasks and Memory are -- there is no external
    provider behind it, so an event written here is the event.
    """

    repository: CalendarEventRepository

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Manage calendar events and schedules.",
            version="1.0.0",
            enabled=True,
            category="productivity",
            keywords=("calendar", "calendario", "event", "cita", "reunion", "agenda", "programar"),
        )

    def tools(self) -> list[Tool]:
        return [
            CreateCalendarEventTool(self.repository),
            ListCalendarEventsTool(self.repository),
        ]
