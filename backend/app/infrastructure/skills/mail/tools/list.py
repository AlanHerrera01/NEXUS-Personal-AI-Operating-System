"""``email.list``: read message headers from an IMAP mailbox."""

from __future__ import annotations

import asyncio

from pydantic import Field

from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.mail.client import (
    EmailClient,
    EmailInvalidAddress,
    EmailNotConfigured,
    EmailOperationFailed,
)
from app.infrastructure.skills.mail.tools.contracts import (
    SKILL_NAME,
    EmailListOutput,
    EmailSummaryOutput,
)

MAX_LIMIT = 50
MAX_QUERY_LENGTH = 200

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "mailbox": {
            "type": ["string", "null"],
            "maxLength": 200,
            "description": "Mailbox to read; defaults to EMAIL_DEFAULT_MAILBOX",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LIMIT,
            "description": "Maximum messages, newest first",
        },
        "unread_only": {
            "type": "boolean",
            "description": "Only messages without the \\\\Seen flag",
        },
        "query": {
            "type": ["string", "null"],
            "maxLength": MAX_QUERY_LENGTH,
            "description": "Optional IMAP TEXT search",
        },
    },
    "required": [],
    "additionalProperties": False,
}


class EmailListInput(ToolInput):
    mailbox: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    unread_only: bool = False
    query: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH)


class EmailListTool(UseCaseTool):
    def __init__(self, client: EmailClient, settings: Settings) -> None:
        super().__init__(
            name="email.list",
            description=(
                "List recent email headers from IMAP. Read-only; message bodies "
                "are fetched only by email.read."
            ),
            skill_name=SKILL_NAME,
            input_model=EmailListInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="email",
        )
        self.client = client
        self.settings = settings

    async def run(self, payload: EmailListInput, context: ToolContext) -> EmailListOutput:
        limit = min(payload.limit, self.settings.email_max_messages)
        try:
            summaries = await asyncio.to_thread(
                self.client.list_messages,
                mailbox=payload.mailbox,
                limit=limit,
                unread_only=payload.unread_only,
                query=payload.query,
            )
        except EmailNotConfigured as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_NOT_CONFIGURED, str(error)) from error
        except EmailInvalidAddress as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_INVALID_ADDRESS, str(error)) from error
        except EmailOperationFailed as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_OPERATION_FAILED, str(error)) from error

        items = [
            EmailSummaryOutput(
                uid=item.uid,
                subject=item.subject,
                sender=item.sender,
                recipients=item.recipients,
                date=item.date,
                unread=item.unread,
                mailbox=item.mailbox,
            )
            for item in summaries
        ]
        return EmailListOutput(items=items, count=len(items))
