from datetime import datetime

from pydantic import Field

from app.application.calendar.create_event import CreateCalendarEventUseCase
from app.application.calendar.errors import InvalidEventError
from app.application.calendar.validation import (
    MAX_DESCRIPTION_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_TITLE_LENGTH,
)
from app.application.tools.base import UseCaseTool
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.repositories.calendar_event_repository import CalendarEventRepository
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.calendar.tools.contracts import SKILL_NAME, CalendarEventSummary

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_TITLE_LENGTH,
            "description": "Short event title",
        },
        "start": {
            "type": "string",
            "description": "Start instant, ISO-8601 with an offset, e.g. 2026-10-19T10:00:00-05:00",
        },
        "end": {
            "type": "string",
            "description": "End instant, after the start, in the same format",
        },
        "description": {
            "type": "string",
            "maxLength": MAX_DESCRIPTION_LENGTH,
            "description": "Optional event description",
        },
        "location": {
            "type": ["string", "null"],
            "maxLength": MAX_LOCATION_LENGTH,
            "description": "Optional place",
        },
    },
    "required": ["title", "start", "end"],
    "additionalProperties": False,
}


class CalendarCreateInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    start: datetime
    end: datetime
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    location: str | None = Field(default=None, max_length=MAX_LOCATION_LENGTH)


class CreateCalendarEventTool(UseCaseTool[CalendarCreateInput, CalendarEventSummary]):
    def __init__(self, repository: CalendarEventRepository) -> None:
        super().__init__(
            name="calendar.create_event",
            description="Schedule an event on the user's own NEXUS calendar.",
            skill_name=SKILL_NAME,
            input_model=CalendarCreateInput,
            input_schema=INPUT_SCHEMA,
            read_only=False,
            side_effect=True,
            requires_confirmation=True,
            category="calendar",
            error_codes={InvalidEventError: ToolErrorCode.CALENDAR_EVENT_INVALID},
        )
        self.use_case = CreateCalendarEventUseCase(repository)

    async def run(self, payload: CalendarCreateInput, context: ToolContext) -> CalendarEventSummary:
        event = self.use_case.execute(
            agent_id=context.agent_id,
            title=payload.title,
            start=payload.start,
            end=payload.end,
            description=payload.description,
            location=payload.location,
        )
        return CalendarEventSummary(
            event_id=str(event.id),
            title=event.title,
            description=event.description,
            start_at=event.start_at,
            end_at=event.end_at,
            location=event.location,
            created_at=event.created_at,
        )
