"""``email.draft``: append a message to the Drafts mailbox. Never sends."""

from __future__ import annotations

import asyncio

from pydantic import Field

from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.mail.client import (
    EmailClient,
    EmailInvalidAddress,
    EmailNotConfigured,
    EmailOperationFailed,
)
from app.infrastructure.skills.mail.tools.contracts import SKILL_NAME, EmailDraftOutput

MAX_RECIPIENTS = 20
MAX_SUBJECT_LENGTH = 300
MAX_BODY_LENGTH = 20_000

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "to": {
            "type": "array",
            "items": {"type": "string", "maxLength": 320},
            "minItems": 1,
            "maxItems": MAX_RECIPIENTS,
            "description": "Bare recipient addresses",
        },
        "cc": {
            "type": ["array", "null"],
            "items": {"type": "string", "maxLength": 320},
            "maxItems": MAX_RECIPIENTS,
        },
        "bcc": {
            "type": ["array", "null"],
            "items": {"type": "string", "maxLength": 320},
            "maxItems": MAX_RECIPIENTS,
        },
        "subject": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_SUBJECT_LENGTH,
        },
        "body": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_BODY_LENGTH,
        },
    },
    "required": ["to", "subject", "body"],
    "additionalProperties": False,
}


class EmailDraftInput(ToolInput):
    to: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    cc: list[str] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    bcc: list[str] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT_LENGTH)
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)


class EmailDraftTool(UseCaseTool):
    def __init__(self, client: EmailClient, settings: Settings) -> None:
        super().__init__(
            name="email.draft",
            description=(
                "Create a draft in the IMAP Drafts mailbox. This tool never "
                "sends; it reports sent=false and leaves the message editable."
            ),
            skill_name=SKILL_NAME,
            input_model=EmailDraftInput,
            input_schema=INPUT_SCHEMA,
            risk_level=RiskLevel.MEDIUM,
            side_effect=True,
            category="email",
        )
        self.client = client
        self.settings = settings

    async def run(self, payload: EmailDraftInput, context: ToolContext) -> EmailDraftOutput:
        try:
            draft = await asyncio.to_thread(
                self.client.create_draft,
                to=payload.to,
                cc=payload.cc,
                bcc=payload.bcc,
                subject=payload.subject,
                body=payload.body,
            )
        except EmailNotConfigured as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_NOT_CONFIGURED, str(error)) from error
        except EmailInvalidAddress as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_INVALID_ADDRESS, str(error)) from error
        except EmailOperationFailed as error:
            raise ToolExecutionError(ToolErrorCode.EMAIL_OPERATION_FAILED, str(error)) from error

        return EmailDraftOutput(
            mailbox=draft.mailbox,
            message_id=draft.message_id,
            size=draft.size,
            sent=False,
        )
