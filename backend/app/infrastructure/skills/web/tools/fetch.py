"""``web.fetch``: read one public page.

The security-relevant decisions live here, not in the prompt:

* every hop, including redirects, goes through ``validate_resolution`` from the
  existing SSRF guard, so a public URL that redirects to ``169.254.169.254`` is
  refused before the second request is made;
* only 80 and 443 are reachable by default, and only textual content types are
  accepted;
* the body is read through a byte ceiling rather than buffered first;
* the excerpt is passed through the prompt-injection fence, so the model reads
  it as data instead of instructions.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from pydantic import Field

from app.application.security.injection import (
    detect_injection,
    fence,
    summarise,
)
from app.application.security.ssrf import SsrfBlocked, validate_resolution
from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.web.tools.contracts import SKILL_NAME, WebFetchOutput
from app.infrastructure.skills.web.tools.html import extract_html_text

logger = logging.getLogger(__name__)

USER_AGENT = "NEXUS/1.0 (personal AI operating system; web.fetch)"
ACCEPT = (
    "text/html,application/xhtml+xml,text/plain;q=0.9,"
    "application/json;q=0.8,application/xml;q=0.8,*/*;q=0.1"
)
MAX_URL_LENGTH = 2_048
MAX_EXCERPT_CHARS = 20_000
MIN_EXCERPT_CHARS = 200
MAX_REDIRECTS = 3

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TEXT_APPLICATION_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/json",
        "application/ld+json",
        "application/rss+xml",
        "application/x-ndjson",
        "application/xml",
        "application/xhtml+xml",
        "application/yaml",
        "application/x-yaml",
    }
)
_BINARY_SIGNATURES = (
    b"%PDF-",
    b"\x89PNG",
    b"GIF87a",
    b"GIF89a",
    b"\xff\xd8\xff",
    b"PK\x03\x04",
    b"\x00\x00\x01\x00",
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_URL_LENGTH,
            "description": "Public http(s) URL to read",
        },
        "max_chars": {
            "type": ["integer", "null"],
            "minimum": MIN_EXCERPT_CHARS,
            "maximum": MAX_EXCERPT_CHARS,
            "description": "Maximum characters of text to return",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


class WebFetchInput(ToolInput):
    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    max_chars: int | None = Field(
        default=None, ge=MIN_EXCERPT_CHARS, le=MAX_EXCERPT_CHARS
    )


class WebFetchTool(UseCaseTool[WebFetchInput, WebFetchOutput]):
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver=None,
    ) -> None:
        super().__init__(
            name="web.fetch",
            description=(
                "Fetch a public web page and return its title and a bounded, "
                "untrusted text excerpt. Private and link-local addresses are "
                "refused, including through redirects."
            ),
            skill_name=SKILL_NAME,
            input_model=WebFetchInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            requires_confirmation=False,
            category="web",
        )
        self.settings = settings
        self._transport = transport
        self._resolver = resolver

    async def run(self, payload: WebFetchInput, context: ToolContext) -> WebFetchOutput:
        try:
            final_url, status, content_type, kind, raw, truncated = await self._get(
                payload.url.strip()
            )
        except SsrfBlocked as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_URL_BLOCKED, f"URL blocked: {error.reason}"
            ) from error
        except httpx.TimeoutException as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_FETCH_FAILED, "The page did not respond in time."
            ) from error
        except httpx.HTTPError as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_FETCH_FAILED, "The page could not be fetched."
            ) from error

        text = _decode(raw, content_type)
        if kind == "html":
            title, body = extract_html_text(text)
        else:
            title, body = "", text

        limit = payload.max_chars or self.settings.web_fetch_max_chars
        truncated = truncated or len(body) > limit
        excerpt = body[:limit]

        findings = detect_injection(excerpt)
        if findings:
            # The excerpt is still returned; the detector is an observable
            # signal, not a rewrite of what the model will read.
            logger.warning(
                "web.fetch: injection-shaped content in %s (%s)",
                final_url,
                summarise(findings),
            )

        return WebFetchOutput(
            url=final_url,
            title=title,
            content_type=_mime(content_type) or ("text/html" if kind == "html" else "text/plain"),
            status_code=status,
            content=fence(excerpt, source=f"web.fetch {final_url}", max_chars=limit),
            truncated=truncated,
            fetched_at=datetime.now(UTC),
        )

    async def _get(self, url: str):
        allowed_ports = self.settings.web_fetch_allowed_port_set
        async with self._client() as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                target = await validate_resolution(current, resolver=self._resolver)
                if target.port not in allowed_ports:
                    raise SsrfBlocked(
                        f"port is not allowed for web.fetch: {target.port}"
                    )

                async with client.stream("GET", target.url) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise ToolExecutionError(
                                ToolErrorCode.WEB_FETCH_FAILED,
                                "Redirect response without a Location header.",
                            )
                        # Re-validate the next hop from scratch. A redirect is
                        # exactly where a public URL becomes an internal one.
                        current = urljoin(str(response.url), location)
                        continue

                    if not 200 <= response.status_code < 300:
                        raise ToolExecutionError(
                            ToolErrorCode.WEB_FETCH_FAILED,
                            f"The page returned HTTP {response.status_code}.",
                        )

                    content_type = response.headers.get("content-type", "")
                    mime = _mime(content_type)
                    kind = _classify_mime(mime) if mime else None
                    if kind == "unsupported":
                        raise ToolExecutionError(
                            ToolErrorCode.WEB_CONTENT_UNSUPPORTED,
                            f"Content type is not supported: {mime}.",
                        )

                    raw, truncated = await _read_limited(
                        response, self.settings.web_fetch_max_bytes
                    )
                    if kind is None:
                        kind = _sniff_kind(raw)
                    if kind == "unsupported":
                        raise ToolExecutionError(
                            ToolErrorCode.WEB_CONTENT_UNSUPPORTED,
                            "The response does not look like text or HTML.",
                        )
                    return (
                        str(response.url),
                        response.status_code,
                        content_type,
                        kind,
                        raw,
                        truncated,
                    )

        raise ToolExecutionError(
            ToolErrorCode.WEB_FETCH_FAILED, "Too many redirects."
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.web_fetch_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
        )


async def _read_limited(response: httpx.Response, limit: int) -> tuple[bytes, bool]:
    declared = response.headers.get("content-length", "")
    truncated = declared.isdigit() and int(declared) > limit
    chunks: list[bytes] = []
    total = 0

    async for chunk in response.aiter_bytes():
        remaining = limit - total
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total = limit
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)

    return b"".join(chunks), truncated


def _decode(raw: bytes, content_type: str) -> str:
    encoding = _charset(content_type) or "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return text.lstrip("\ufeff")


def _charset(content_type: str) -> str | None:
    match = re.search(r"charset\s*=\s*\"?([^\";\s]+)", content_type or "", re.I)
    return match.group(1).lower() if match else None


def _mime(content_type: str) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _classify_mime(mime: str) -> str:
    if mime in {"text/html", "application/xhtml+xml"}:
        return "html"
    if mime.startswith("text/") or mime in _TEXT_APPLICATION_TYPES:
        return "text"
    return "unsupported"


def _sniff_kind(raw: bytes) -> str:
    sample = raw[:1_024].lstrip()
    lowered = sample.lower()
    if any(sample.startswith(signature) for signature in _BINARY_SIGNATURES):
        return "unsupported"
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        return "html"
    if b"<html" in lowered[:256]:
        return "html"
    return "text"


__all__ = ("WebFetchTool",)
