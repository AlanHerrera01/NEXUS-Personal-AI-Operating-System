"""``reminder.list``: read the user's reminders in time order."""

from __future__ import annotations

from pydantic import Field

from app.application.reminders.errors import InvalidReminderError
from app.application.reminders.list_reminders import MAX_LIMIT, ListRemindersUseCase
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.reminder_status import ReminderStatus
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.reminders.tools.contracts import (
    SKILL_NAME,
    ReminderListOutput,
    ReminderSummary,
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": ["string", "null"],
            "enum": ["PENDING", "SENT", "CANCELLED", None],
            "description": "Optional status filter",
        },
        "upcoming_only": {
            "type": "boolean",
            "description": "Only reminders at or after the current time",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LIMIT,
            "description": "Maximum reminders to return",
        },
    },
    "required": [],
    "additionalProperties": False,
}


class ListRemindersInput(ToolInput):
    status: ReminderStatus | None = None
    upcoming_only: bool = False
    limit: int = Field(default=20, ge=1, le=MAX_LIMIT)


class ListRemindersTool(UseCaseTool):
    def __init__(self, use_case: ListRemindersUseCase) -> None:
        super().__init__(
            name="reminder.list",
            description=(
                "List reminders in chronological order, optionally only the "
                "upcoming ones."
            ),
            skill_name=SKILL_NAME,
            input_model=ListRemindersInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="reminders",
        )
        self.use_case = use_case

    async def run(
        self, payload: ListRemindersInput, context: ToolContext
    ) -> ReminderListOutput:
        try:
            reminders = self.use_case.execute(
                agent_id=context.agent_id,
                user_id=context.user_id,
                status=payload.status,
                upcoming_only=payload.upcoming_only,
                limit=payload.limit,
            )
        except InvalidReminderError as error:
            raise ToolExecutionError(ToolErrorCode.REMINDER_INVALID, str(error)) from error

        items = [
            ReminderSummary(
                reminder_id=str(reminder.id),
                title=reminder.title,
                notes=reminder.notes,
                remind_at=reminder.remind_at,
                status=reminder.status,
                created_at=reminder.created_at,
            )
            for reminder in reminders
        ]
        return ReminderListOutput(items=items, count=len(items))
