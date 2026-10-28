from app.domain.ports.tool import ToolOutput

SKILL_NAME = "email"


class EmailSummaryOutput(ToolOutput):
    uid: int
    subject: str
    sender: str
    recipients: str
    date: str
    unread: bool
    mailbox: str


class EmailListOutput(ToolOutput):
    items: list[EmailSummaryOutput]
    count: int


class EmailAttachmentOutput(ToolOutput):
    filename: str
    content_type: str
    size: int


class EmailReadOutput(ToolOutput):
    uid: int
    subject: str
    sender: str
    recipients: str
    cc: str
    date: str
    body: str
    attachments: list[EmailAttachmentOutput]
    truncated: bool
    mailbox: str


class EmailDraftOutput(ToolOutput):
    mailbox: str
    message_id: str
    size: int
    sent: bool = False
