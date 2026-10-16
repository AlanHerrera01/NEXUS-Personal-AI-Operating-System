from datetime import datetime

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput

SKILL_NAME = "calendar"


class CalendarEventSummary(ToolOutput):
    event_id: str
    title: str
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    url: str | None = None


class CalendarCreateInput(ToolInput):
    title: str
    description: str | None = None
    start: datetime
    end: datetime
    location: str | None = None


class CalendarCreateOutput(ToolOutput):
    event_id: str
    title: str
    start: datetime
    end: datetime
    url: str | None = None


class CreateCalendarEventTool(UseCaseTool):
    """Crea un evento en el calendario."""

    def __init__(self) -> None:
        super().__init__(
            name="calendar.create_event",
            description="Create a calendar event",
            skill_name="calendar",
            input_model=CalendarCreateInput,
            input_schema=CalendarCreateInput.model_json_schema(),
            risk_level="LOW",
            read_only=False,
            side_effect=True,
            requires_confirmation=True,
        )

    async def run(self, payload: CalendarCreateInput, context: object) -> CalendarCreateOutput:
        # Placeholder: en implementación real conectaríamos con Google Calendar u otro proveedor
        return CalendarCreateOutput(
            event_id="1",
            title=payload.title,
            start=payload.start,
            end=payload.end,
            url=f"https://calendar.example.com/event/{payload.title.lower().replace(' ', '-')}",
        )


class CalendarListInput(ToolInput):
    start: datetime | None = None
    end: datetime | None = None


class ListCalendarEventsOutput(ToolOutput):
    events: list[CalendarEventSummary]


class ListCalendarEventsTool(UseCaseTool):
    """Lista eventos del calendario."""

    def __init__(self) -> None:
        super().__init__(
            name="calendar.list_events",
            description="List calendar events",
            skill_name="calendar",
            input_model=CalendarListInput,
            input_schema=CalendarListInput.model_json_schema(),
            risk_level="LOW",
            read_only=True,
            side_effect=False,
            requires_confirmation=False,
        )

    async def run(self, payload: CalendarListInput, context: object) -> list[CalendarEventSummary]:
        # Placeholder: en implementación real conectaríamos con la API de calendario
        now = datetime.now()
        return [
            CalendarEventSummary(
                event_id="1",
                title="Reunion de equipo",
                description="Reunion semanal del equipo de NEXUS",
                start_time=now,
                end_time=now,
                url="https://calendar.example.com/event/1",
            ),
        ]