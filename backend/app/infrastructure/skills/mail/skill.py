from dataclasses import dataclass

from app.config.settings import Settings
from app.domain.ports.skill import Skill, SkillDefinition
from app.domain.ports.tool import Tool
from app.infrastructure.skills.mail.client import EmailClient, ImapEmailClient
from app.infrastructure.skills.mail.tools.contracts import SKILL_NAME
from app.infrastructure.skills.mail.tools.draft import EmailDraftTool
from app.infrastructure.skills.mail.tools.list import EmailListTool
from app.infrastructure.skills.mail.tools.read import EmailReadTool

KEYWORDS = (
    "email",
    "correo",
    "correos",
    "mail",
    "imap",
    "inbox",
    "bandeja",
    "borrador",
    "borradores",
    "draft",
    "mensaje",
    "mensajes",
)


@dataclass
class EmailSkill(Skill):
    settings: Settings
    client: EmailClient | None = None

    def __post_init__(self) -> None:
        # ``None`` is a legitimate test injection point, so the client is
        # created lazily rather than at import time. The default client only
        # reads IMAP and appends drafts; it cannot send.
        if self.client is None:
            self.client = ImapEmailClient(self.settings)

    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            name=SKILL_NAME,
            description="Read email over IMAP and create drafts without sending.",
            version="1.0.0",
            enabled=True,
            category="email",
            keywords=KEYWORDS,
        )

    def tools(self) -> list[Tool]:
        client = self.client
        if client is None:  # pragma: no cover - __post_init__ always fills it
            raise RuntimeError("email client was not initialized")
        return [
            EmailListTool(client, self.settings),
            EmailReadTool(client, self.settings),
            EmailDraftTool(client, self.settings),
        ]
