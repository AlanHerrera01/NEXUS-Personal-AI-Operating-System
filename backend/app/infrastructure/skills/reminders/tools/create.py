"""``reminder.create``: persist a one-shot, time-based reminder."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.application.reminders.create_reminder import (
    MAX_NOTES_LENGTH,
    MAX_TITLE_LENGTH,
    CreateReminderUseCase,
)
from app.application.reminders.errors import InvalidReminderError
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.reminders.tools.contracts import (
    SKILL_NAME,
    ReminderSummary,
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_TITLE_LENGTH,
            "description": "What to remind the user about",
        },
        "remind_at": {
            "type": "string",
            "format": "date-time",
            "description": "ISO-8601 instant with a timezone offset",
        },
        "notes": {
            "type": "string",
            "maxLength": MAX_NOTES_LENGTH,
            "description": "Optional extra detail",
        },
    },
    "required": ["title", "remind_at"],
    "additionalProperties": False,
}


class CreateReminderInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    remind_at: datetime
    notes: str = Field(default="", max_length=MAX_NOTES_LENGTH)


class CreateReminderTool(UseCaseTool):
    def __init__(self, use_case: CreateReminderUseCase) -> None:
        super().__init__(
            name="reminder.create",
            description=(
                "Create a one-shot reminder at a specific instant. This is not "
                "a task: it has no workflow state, only a time to surface it."
            ),
            skill_name=SKILL_NAME,
            input_model=CreateReminderInput,
            input_schema=INPUT_SCHEMA,
            risk_level=RiskLevel.MEDIUM,
            side_effect=True,
            category="reminders",
        )
        self.use_case = use_case

    async def run(
        self, payload: CreateReminderInput, context: ToolContext
    ) -> ReminderSummary:
        try:
            reminder = self.use_case.execute(
                agent_id=context.agent_id,
                user_id=context.user_id,
                title=payload.title,
                remind_at=payload.remind_at,
                notes=payload.notes,
            )
        except InvalidReminderError as error:
            raise ToolExecutionError(ToolErrorCode.REMINDER_INVALID, str(error)) from error
        return ReminderSummary(
            reminder_id=str(reminder.id),
            title=reminder.title,
            notes=reminder.notes,
            remind_at=reminder.remind_at,
            status=reminder.status,
            created_at=reminder.created_at,
        )
