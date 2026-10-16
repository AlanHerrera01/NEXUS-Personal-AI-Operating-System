from datetime import datetime, timedelta

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput


class CalendarListInput(ToolInput):
    start: datetime | None = None
    end: datetime | None = None


class CalendarEventOutput(ToolOutput):
    event_id: str
    title: str
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    url: str | None = None


class ListCalendarEventsTool(UseCaseTool):
    """Lista eventos del calendario - SIMULATION MODE.

    En modo simulation, devuelve eventos de ejemplo con fechas próximas.
    En producción real, conectaría con Google Calendar u otro proveedor.
    """

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

    async def run(self, payload: CalendarListInput, context: object) -> list[CalendarEventOutput]:
        # SIMULATION: Devolver eventos de ejemplo según el contexto
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        # Events for today and tomorrow
        events = [
            CalendarEventOutput(
                event_id="1",
                title="Reunion de equipo NEXUS",
                description="Discusion semanal del progreso del proyecto",
                start_time=now + timedelta(minutes=30),
                end_time=now + timedelta(hours=1),
                url="https://calendar.example.com/event/team-meeting",
            ),
            CalendarEventOutput(
                event_id="2",
                title="Cita con inversor",
                description="Reunion para discutir el siguiente hito del proyecto",
                start_time=tomorrow_start + timedelta(hours=10),
                end_time=tomorrow_start + timedelta(hours=11),
                url="https://calendar.example.com/event/investor-meeting",
            ),
            CalendarEventOutput(
                event_id="3",
                title="Hora de almuerzo",
                description="Almuerzo con el equipo de desarrollo",
                start_time=now + timedelta(hours=2),
                end_time=now + timedelta(hours=3),
                url="https://calendar.example.com/event/lunch",
            ),
        ]

        # Filtrar por rango si se especifica
        if payload.start:
            events = [e for e in events if e.start_time >= payload.start]
        if payload.end:
            events = [e for e in events if e.start_time <= payload.end]

        return events