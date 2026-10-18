from datetime import datetime

from pydantic import Field

from app.application.calendar.errors import InvalidEventError
from app.application.calendar.list_events import ListCalendarEventsUseCase
from app.application.calendar.validation import MAX_LIMIT
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolContext, ToolInput, ToolOutput
from app.domain.repositories.calendar_event_repository import CalendarEventRepository
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.calendar.tools.contracts import SKILL_NAME, CalendarEventSummary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {
            "type": ["string", "null"],
            "description": "Window opens here; events ending after it are returned (ISO-8601 with offset)",
        },
        "end": {
            "type": ["string", "null"],
            "description": "Window closes here; events starting before it are returned",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LIMIT,
            "description": "Maximum events to return",
        },
    },
    "required": [],
    "additionalProperties": False,
}


class CalendarListInput(ToolInput):
    start: datetime | None = None
    end: datetime | None = None
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)


class CalendarListOutput(ToolOutput):
    items: list[CalendarEventSummary]
    count: int


class ListCalendarEventsTool(UseCaseTool[CalendarListInput, CalendarListOutput]):
    def __init__(self, repository: CalendarEventRepository) -> None:
        super().__init__(
            name="calendar.list_events",
            description=(
                "List events on the user's own NEXUS calendar, optionally within "
                "a time window. Overlapping events are included."
            ),
            skill_name=SKILL_NAME,
            input_model=CalendarListInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            category="calendar",
            error_codes={InvalidEventError: ToolErrorCode.CALENDAR_EVENT_INVALID},
        )
        self.use_case = ListCalendarEventsUseCase(repository)

    async def run(self, payload: CalendarListInput, context: ToolContext) -> CalendarListOutput:
        events = self.use_case.execute(
            agent_id=context.agent_id,
            start=payload.start,
            end=payload.end,
            limit=payload.limit,
        )
        return CalendarListOutput(
            items=[
                CalendarEventSummary(
                    event_id=str(event.id),
                    title=event.title,
                    description=event.description,
                    start_at=event.start_at,
                    end_at=event.end_at,
                    location=event.location,
                    created_at=event.created_at,
                )
                for event in events
            ],
            count=len(events),
        )
