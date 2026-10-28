from __future__ import annotations

import imaplib
from unittest.mock import patch

import pytest

from app.config.settings import Settings
from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.mail.client import (
    EmailAttachment,
    EmailDetail,
    EmailDraft,
    EmailOperationFailed,
    EmailSummary,
    ImapEmailClient,
)
from app.infrastructure.skills.mail.skill import EmailSkill


class FakeEmailClient:
    def __init__(self) -> None:
        self.list_calls: list[dict] = []
        self.read_calls: list[dict] = []
        self.draft_calls: list[dict] = []

    def list_messages(self, *, mailbox, limit, unread_only, query):
        self.list_calls.append(
            {
                "mailbox": mailbox,
                "limit": limit,
                "unread_only": unread_only,
                "query": query,
            }
        )
        return [
            EmailSummary(
                uid=7,
                subject="Estado del deploy",
                sender="ops@example.com",
                recipients="yo@example.com",
                date="Tue, 20 Oct 2026 10:00:00 +0000",
                unread=True,
                mailbox=mailbox or "INBOX",
            )
        ]

    def read_message(self, *, mailbox, uid, max_chars):
        self.read_calls.append(
            {"mailbox": mailbox, "uid": uid, "max_chars": max_chars}
        )
        return EmailDetail(
            uid=uid,
            subject="Estado del deploy",
            sender="ops@example.com",
            recipients="yo@example.com",
            cc="",
            date="Tue, 20 Oct 2026 10:00:00 +0000",
            body="El backend quedó healthy.",
            attachments=[EmailAttachment("run.log", "text/plain", 12)],
            truncated=False,
            mailbox=mailbox or "INBOX",
        )

    def create_draft(self, *, to, subject, body, cc=None, bcc=None):
        self.draft_calls.append(
            {
                "to": to,
                "subject": subject,
                "body": body,
                "cc": cc,
                "bcc": bcc,
            }
        )
        return EmailDraft(mailbox="Drafts", message_id="<draft@example.com>", size=123)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        email_enabled=True,
        email_imap_host="imap.example.com",
        email_imap_username="yo@example.com",
        email_imap_password="secret",
        email_from_address="yo@example.com",
    )


def _tools(client) -> dict[str, object]:
    return {
        tool.definition().name: tool
        for tool in EmailSkill(_settings(), client=client).tools()
    }


def _context() -> ToolContext:
    return ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new())


def test_email_skill_is_read_and_draft_only() -> None:
    tools = _tools(FakeEmailClient())

    assert set(tools) == {"email.list", "email.read", "email.draft"}
    assert tools["email.list"].definition().read_only is True
    assert tools["email.read"].definition().read_only is True
    draft = tools["email.draft"].definition()
    assert draft.side_effect is True
    assert draft.read_only is False
    assert "never sends" in draft.description.lower()


async def test_list_read_and_draft_forward_to_the_client() -> None:
    client = FakeEmailClient()
    tools = _tools(client)
    context = _context()

    listed = await tools["email.list"].execute(
        {"unread_only": True, "query": "deploy", "limit": 5}, context
    )
    assert listed.success is True
    assert listed.data["count"] == 1
    assert listed.data["items"][0]["uid"] == 7
    assert client.list_calls[0]["query"] == "deploy"

    read = await tools["email.read"].execute({"uid": 7, "max_chars": 1000}, context)
    assert read.success is True
    assert "healthy" in read.data["body"]
    assert read.data["attachments"][0]["filename"] == "run.log"

    drafted = await tools["email.draft"].execute(
        {
            "to": ["ops@example.com"],
            "subject": "Gracias",
            "body": "Recibido.",
        },
        context,
    )
    assert drafted.success is True
    assert drafted.data["sent"] is False
    assert drafted.data["mailbox"] == "Drafts"
    assert client.draft_calls[0]["to"] == ["ops@example.com"]


async def test_email_is_not_configured_by_default() -> None:
    settings = Settings(_env_file=None)
    tools = {
        tool.definition().name: tool
        for tool in EmailSkill(settings, client=ImapEmailClient(settings)).tools()
    }

    result = await tools["email.list"].execute({}, _context())

    assert result.success is False
    assert result.error_code == "EMAIL_NOT_CONFIGURED"
    assert "EMAIL_ENABLED" in result.error_message


def test_imap_protocol_errors_become_a_domain_error() -> None:
    class BrokenConnection:
        def select(self, *args, **kwargs):
            raise imaplib.IMAP4.error("server said no")

        def logout(self):
            return None

    client = ImapEmailClient(_settings())
    with patch.object(client, "_connect", return_value=BrokenConnection()):
        with pytest.raises(EmailOperationFailed):
            client.list_messages(
                mailbox=None, limit=5, unread_only=False, query=None
            )
