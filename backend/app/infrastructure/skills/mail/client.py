"""A deliberately small IMAP client: read messages and append drafts.

There is no SMTP code in this module and no ``send`` method. Draft creation is
an IMAP ``APPEND`` into the Drafts mailbox, which is why the feature can be
useful without giving the agent the ability to send mail on the user's behalf.
"""

from __future__ import annotations

import imaplib
import re
import time
from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.utils import formatdate, make_msgid
from typing import Protocol

from app.config.settings import Settings
from app.infrastructure.skills.web.tools.html import extract_html_text


class EmailError(Exception):
    """Base class for email operations that the tool layer can explain."""


class EmailNotConfigured(EmailError):
    """The deployment has not supplied (complete) IMAP settings."""


class EmailOperationFailed(EmailError):
    """The IMAP server refused or failed an operation."""


class EmailInvalidAddress(EmailError):
    """An address, subject or mailbox is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class EmailSummary:
    uid: int
    subject: str
    sender: str
    recipients: str
    date: str
    unread: bool
    mailbox: str


@dataclass(frozen=True, slots=True)
class EmailAttachment:
    filename: str
    content_type: str
    size: int


@dataclass(frozen=True, slots=True)
class EmailDetail:
    uid: int
    subject: str
    sender: str
    recipients: str
    cc: str
    date: str
    body: str
    attachments: list[EmailAttachment]
    truncated: bool
    mailbox: str


@dataclass(frozen=True, slots=True)
class EmailDraft:
    mailbox: str
    message_id: str
    size: int


class EmailClient(Protocol):
    def list_messages(
        self,
        *,
        mailbox: str | None,
        limit: int,
        unread_only: bool,
        query: str | None,
    ) -> list[EmailSummary]: ...

    def read_message(
        self, *, mailbox: str | None, uid: int, max_chars: int
    ) -> EmailDetail: ...

    def create_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> EmailDraft: ...


class ImapEmailClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def list_messages(
        self,
        *,
        mailbox: str | None,
        limit: int,
        unread_only: bool,
        query: str | None,
    ) -> list[EmailSummary]:
        self._require_config()
        selected_mailbox = self._safe_mailbox(mailbox or self.settings.email_default_mailbox)
        connection = self._connect()
        try:
            status, _ = connection.select(selected_mailbox, readonly=True)
            if status != "OK":
                raise EmailOperationFailed(
                    f"the mailbox {selected_mailbox!r} could not be opened"
                )
            criteria = ["UNSEEN"] if unread_only else ["ALL"]
            if query:
                criteria += ["TEXT", f'"{_quote_imap(query)}"']
            status, data = connection.uid("SEARCH", None, *criteria)
            if status != "OK":
                raise EmailOperationFailed("the IMAP search was rejected")
            raw = data[0] if data and isinstance(data[0], bytes) else b""
            uids = [int(value) for value in raw.split() if value.isdigit()]
            selected = list(reversed(uids))[:limit]
            summaries: list[EmailSummary] = []
            for uid in selected:
                status, parts = connection.uid(
                    "FETCH",
                    str(uid),
                    "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)] FLAGS)",
                )
                if status != "OK":
                    continue
                header = _fetch_payload(parts)
                flags = _fetch_flags(parts)
                message = message_from_bytes(header)
                summaries.append(
                    EmailSummary(
                        uid=uid,
                        subject=_header(message, "Subject"),
                        sender=_header(message, "From"),
                        recipients=_header(message, "To"),
                        date=_header(message, "Date"),
                        unread=b"\\Seen" not in flags,
                        mailbox=selected_mailbox,
                    )
                )
            return summaries
        except EmailError:
            raise
        except Exception as error:
            raise EmailOperationFailed(
                f"the IMAP operation failed ({type(error).__name__})"
            ) from error
        finally:
            _logout(connection)

    def read_message(
        self, *, mailbox: str | None, uid: int, max_chars: int
    ) -> EmailDetail:
        self._require_config()
        selected_mailbox = self._safe_mailbox(mailbox or self.settings.email_default_mailbox)
        connection = self._connect()
        try:
            status, _ = connection.select(selected_mailbox, readonly=True)
            if status != "OK":
                raise EmailOperationFailed(
                    f"the mailbox {selected_mailbox!r} could not be opened"
                )
            status, parts = connection.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if status != "OK":
                raise EmailOperationFailed(f"message {uid} could not be read")
            raw = _fetch_payload(parts)
            if not raw:
                raise EmailOperationFailed(f"message {uid} was empty or missing")
            message = message_from_bytes(raw)
            body, attachments = _body_and_attachments(message)
            truncated = len(body) > max_chars
            return EmailDetail(
                uid=uid,
                subject=_header(message, "Subject"),
                sender=_header(message, "From"),
                recipients=_header(message, "To"),
                cc=_header(message, "Cc"),
                date=_header(message, "Date"),
                body=body[:max_chars],
                attachments=attachments,
                truncated=truncated,
                mailbox=selected_mailbox,
            )
        except EmailError:
            raise
        except Exception as error:
            raise EmailOperationFailed(
                f"the IMAP operation failed ({type(error).__name__})"
            ) from error
        finally:
            _logout(connection)

    def create_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> EmailDraft:
        self._require_config(need_sender=True)
        recipients = [_validate_address(address) for address in to]
        carbon_copy = [_validate_address(address) for address in (cc or [])]
        blind_copy = [_validate_address(address) for address in (bcc or [])]
        safe_subject = _validate_subject(subject)
        if not body.strip():
            raise EmailInvalidAddress("the draft body must not be empty")

        sender = _validate_address(
            self.settings.email_from_address or self.settings.email_imap_username or ""
        )
        message = EmailMessage()
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        if carbon_copy:
            message["Cc"] = ", ".join(carbon_copy)
        if blind_copy:
            message["Bcc"] = ", ".join(blind_copy)
        message["Subject"] = safe_subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=sender.partition("@")[2] or "nexus.local")
        message.set_content(body)

        selected_mailbox = self._safe_mailbox(self.settings.email_drafts_mailbox)
        connection = self._connect()
        try:
            status, _ = connection.append(
                selected_mailbox,
                "(\\Draft)",
                imaplib.Time2Internaldate(time.time()),
                message.as_bytes(),
            )
            if status != "OK":
                raise EmailOperationFailed(
                    f"the Drafts mailbox {selected_mailbox!r} rejected the message"
                )
        except EmailError:
            raise
        except Exception as error:
            raise EmailOperationFailed(
                f"the IMAP operation failed ({type(error).__name__})"
            ) from error
        finally:
            _logout(connection)

        return EmailDraft(
            mailbox=selected_mailbox,
            message_id=str(message["Message-ID"] or ""),
            size=len(message.as_bytes()),
        )

    def _require_config(self, *, need_sender: bool = False) -> None:
        if not self.settings.email_enabled:
            raise EmailNotConfigured(
                "email is disabled; set EMAIL_ENABLED=true and configure the IMAP variables"
            )
        missing = [
            name
            for name, value in (
                ("EMAIL_IMAP_HOST", self.settings.email_imap_host),
                ("EMAIL_IMAP_USERNAME", self.settings.email_imap_username),
                ("EMAIL_IMAP_PASSWORD", self.settings.email_imap_password),
            )
            if not value
        ]
        if need_sender and not (
            self.settings.email_from_address or self.settings.email_imap_username
        ):
            missing.append("EMAIL_FROM_ADDRESS")
        if missing:
            raise EmailNotConfigured(
                "email is not configured; missing " + ", ".join(missing)
            )

    def _connect(self) -> imaplib.IMAP4:
        host = self.settings.email_imap_host or ""
        username = self.settings.email_imap_username or ""
        password = self.settings.email_imap_password or ""
        try:
            if self.settings.email_imap_use_ssl:
                connection: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    host, self.settings.email_imap_port, timeout=self.settings.email_timeout_seconds
                )
            else:
                connection = imaplib.IMAP4(
                    host, self.settings.email_imap_port, timeout=self.settings.email_timeout_seconds
                )
                connection.starttls()
            connection.login(username, password)
            return connection
        except Exception as error:
            raise EmailOperationFailed(
                f"could not connect to the IMAP server ({type(error).__name__})"
            ) from error

    @staticmethod
    def _safe_mailbox(value: str) -> str:
        mailbox = value.strip()
        if not mailbox or len(mailbox) > 200:
            raise EmailInvalidAddress("the mailbox name is empty or too long")
        if any(character in mailbox for character in ('"', "\\", "\r", "\n")):
            raise EmailInvalidAddress("the mailbox name contains an unsafe character")
        return mailbox


def _logout(connection: imaplib.IMAP4) -> None:
    try:
        connection.logout()
    except Exception:
        pass


def _fetch_payload(parts: object) -> bytes:
    if not isinstance(parts, (list, tuple)):
        return b""
    for part in parts:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
            return part[1]
    return b""


def _fetch_flags(parts: object) -> bytes:
    if not isinstance(parts, (list, tuple)):
        return b""
    collected: list[bytes] = []
    for part in parts:
        # imaplib puts the metadata line (including FLAGS) in tuple[0] and the
        # literal BODY payload in tuple[1]. Looking only at the metadata avoids
        # mistaking "\\Seen" inside a message header for an actual flag.
        if isinstance(part, tuple) and part and isinstance(part[0], bytes):
            collected.append(part[0])
        elif isinstance(part, bytes):
            collected.append(part)
    return b" ".join(collected)


def _header(message: Message, name: str) -> str:
    value = message.get(name)
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _body_and_attachments(message: Message) -> tuple[str, list[EmailAttachment]]:
    plain: list[str] = []
    html: list[str] = []
    attachments: list[EmailAttachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = str(part.get("Content-Disposition", "")).lower()
        filename = part.get_filename()
        if filename or "attachment" in disposition:
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                EmailAttachment(
                    filename=_decode_header_value(filename or "attachment"),
                    content_type=part.get_content_type(),
                    size=len(payload),
                )
            )
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/html":
            _, html_text = extract_html_text(text)
            html.append(html_text)
        else:
            plain.append(text)
    body = "\n\n".join(plain) if plain else "\n\n".join(html)
    return body.strip(), attachments


def _decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _quote_imap(value: str) -> str:
    cleaned = value.replace("\r", " ").replace("\n", " ")
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


_ADDRESS_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def _validate_address(value: str) -> str:
    address = value.strip()
    if len(address) > 320 or "\r" in address or "\n" in address:
        raise EmailInvalidAddress("an email address is malformed")
    if not _ADDRESS_RE.match(address):
        raise EmailInvalidAddress(f"not a bare email address: {address!r}")
    return address


def _validate_subject(value: str) -> str:
    subject = value.strip()
    if not subject:
        raise EmailInvalidAddress("the subject must not be empty")
    if "\r" in subject or "\n" in subject:
        raise EmailInvalidAddress("the subject must be a single line")
    return subject
