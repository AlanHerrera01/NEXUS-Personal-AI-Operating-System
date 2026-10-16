from datetime import datetime, timedelta

from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolInput, ToolOutput


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
    location: str | None = None
    url: str | None = None


class CreateCalendarEventTool(UseCaseTool):
    """Crea un evento en el calendario - SIMULATION MODE.

    En modo simulation, crea un evento con una fecha futura y devuelve
    una URL simulada. En producción real, conectaría con Google Calendar
    u otro proveedor de calendario.
    """

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
        # SIMULATION: En modo development, simulamos la creación de un evento
        # con una fecha 1 hora en el futuro si no se especifica
        now = datetime.now()
        event_start = payload.start if payload.start > now else now + timedelta(hours=1)
        event_end = payload.end if payload.end > event_start else event_start + timedelta(hours=1)

        # Generar ID y URL simulados
        import hashlib
        event_hash = hashlib.md5(f"{payload.title}{event_start}".encode()).hexdigest()[:8]
        event_id = f"event_{event_hash}"
        url = f"https://calendar.example.com/event/{event_hash}"

        return CalendarCreateOutput(
            event_id=event_id,
            title=payload.title,
            start=event_start,
            end=event_end,
            location=payload.location,
            url=url,
        )