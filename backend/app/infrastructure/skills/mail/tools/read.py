"""``email.read``: read one message body and attachment metadata."""

from __future__ import annotations

import asyncio

from pydantic import Field

from app.application.security.injection import fence
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
    EmailAttachmentOutput,
    EmailReadOutput,
)

MIN_CHARS = 500
MAX_CHARS = 50_000

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "uid": {
            "type": "integer",
            "minimum": 1,
            "description": "IMAP UID returned by email.list",
        },
        "mailbox": {
            "type": ["string", "null"],
            "maxLength": 200,
            "description": "Mailbox to read; defaults to EMAIL_DEFAULT_MAILBOX",
        },
        "max_chars": {
            "type": ["integer", "null"],
            "minimum": MIN_CHARS,
            "maximum": MAX_CHARS,
            "description": "Maximum body characters to return",
        },
    },
    "required": ["uid"],
    "additionalProperties": False,
}


class EmailReadInput(ToolInput):
    uid: int = Field(ge=1)
    mailbox: str | None = Field(default=None, max_length=200)
    max_chars: int | None = Field(default=None, ge=MIN_CHARS, le=MAX_CHARS)


class EmailReadTool(UseCaseTool):
    def __init__(self, client: EmailClient, settings: Settings) -> None:
        super().__init__(
            name="email.read",
            description=(
                "Read one email by UID, including a bounded body and attachment "
                "metadata. Attachments are never opened."
            ),
            skill_name=SKILL_NAME,
            input_model=EmailReadInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            category="email",
        )
        self.client = client
        self.settings = settings

    async def run(self, payload: EmailReadInput, context: ToolContext) -> EmailReadOutput:
        limit = min(payload.max_chars or 20_000, self.settings.email_max_body_chars)
        try:
            detail = await asyncio.to_thread(
                self.client.read_message,
                mailbox=payload.mailbox,
                uid=payload.uid,
                max_chars=limit,
            )
        except EmailNotConfigured as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_NOT_CONFIGURED, str(error)) from error
        except EmailInvalidAddress as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_INVALID_ADDRESS, str(error)) from error
        except EmailOperationFailed as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_OPERATION_FAILED, str(error)) from error

        return EmailReadOutput(
            uid=detail.uid,
            subject=detail.subject,
            sender=detail.sender,
            recipients=detail.recipients,
            cc=detail.cc,
            date=detail.date,
            body=fence(
                detail.body,
                source=f"email.read uid={detail.uid}",
                max_chars=limit,
            ),
            attachments=[
                EmailAttachmentOutput(
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    size=attachment.size,
                )
                for attachment in detail.attachments
            ],
            truncated=detail.truncated,
            mailbox=detail.mailbox,
        )
