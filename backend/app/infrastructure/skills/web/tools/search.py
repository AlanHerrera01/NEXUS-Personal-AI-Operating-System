"""``web.search``: provider-backed web search.

Two providers are supported. Brave is the reliable one and needs an API key.
DuckDuckGo's HTML endpoint works without a key but is best-effort: from a
datacenter address it frequently answers with an anti-bot challenge, which this
tool reports instead of pretending it found nothing.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from pydantic import Field

from app.application.tools.base import UseCaseTool
from app.application.tools.errors import ToolExecutionError
from app.config.settings import Settings
from app.domain.ports.tool import ToolContext, ToolInput
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.web.tools.contracts import (
    SKILL_NAME,
    WebSearchOutput,
    WebSearchResult,
)

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DUCKDUCKGO_ENDPOINT = "https://html.duckduckgo.com/html/"
USER_AGENT = "NEXUS/1.0 (personal AI operating system; web.search)"
MAX_QUERY_LENGTH = 500
MAX_RESULTS = 10

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_QUERY_LENGTH,
            "description": "Search query",
        },
        "limit": {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": MAX_RESULTS,
            "description": "Maximum results to return",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class WebSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int | None = Field(default=None, ge=1, le=MAX_RESULTS)


class WebSearchTool(UseCaseTool[WebSearchInput, WebSearchOutput]):
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            name="web.search",
            description=(
                "Search the public web and return titles, URLs and snippets. "
                "Use web.fetch to read a result in more detail."
            ),
            skill_name=SKILL_NAME,
            input_model=WebSearchInput,
            input_schema=INPUT_SCHEMA,
            read_only=True,
            side_effect=False,
            requires_confirmation=False,
            category="web",
        )
        self.settings = settings
        self._transport = transport

    async def run(self, payload: WebSearchInput, context: ToolContext) -> WebSearchOutput:
        limit = min(
            payload.limit or self.settings.web_search_max_results,
            self.settings.web_search_max_results,
            MAX_RESULTS,
        )
        provider = self._provider()
        if provider == "brave":
            items = await self._search_brave(payload.query, limit)
        else:
            items = await self._search_duckduckgo(payload.query, limit)
        return WebSearchOutput(
            query=payload.query,
            provider=provider,
            items=items,
            count=len(items),
        )

    def _provider(self) -> str:
        if self.settings.web_search_provider == "auto":
            return "brave" if self.settings.web_search_api_key else "duckduckgo"
        return self.settings.web_search_provider

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.web_search_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT},
        )

    async def _search_brave(self, query: str, limit: int) -> list[WebSearchResult]:
        api_key = self.settings.web_search_api_key
        if not api_key:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                "Brave Search is selected but WEB_SEARCH_API_KEY is empty.",
            )

        url = self.settings.web_search_base_url or BRAVE_ENDPOINT
        try:
            async with self._client() as client:
                response = await client.get(
                    url,
                    params={
                        "q": query,
                        "count": limit,
                        "safesearch": "moderate",
                        "text_decorations": "false",
                        "spellcheck": "false",
                    },
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": api_key,
                    },
                )
        except httpx.TimeoutException as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED, "Brave Search timed out."
            ) from error
        except httpx.HTTPError as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED, "Brave Search request failed."
            ) from error

        if response.status_code in {401, 403}:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                "Brave Search rejected the API key.",
            )
        if response.status_code == 429:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                "Brave Search rate limit reached.",
            )
        if response.status_code != 200:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                f"Brave Search returned HTTP {response.status_code}.",
            )

        try:
            data = response.json()
        except ValueError as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                "Brave Search returned an invalid JSON response.",
            ) from error

        web = data.get("web") if isinstance(data, dict) else None
        raw_results = web.get("results") if isinstance(web, dict) else None
        if not isinstance(raw_results, list):
            return []

        items: list[WebSearchResult] = []
        for entry in raw_results:
            if not isinstance(entry, dict):
                continue
            title = _plain(entry.get("title"))
            url = _clean(entry.get("url"))
            snippet = _plain(entry.get("description") or entry.get("snippet"))
            if title and _is_http_url(url):
                items.append(WebSearchResult(title=title, url=url, snippet=snippet))
            if len(items) >= limit:
                break
        return items

    async def _search_duckduckgo(self, query: str, limit: int) -> list[WebSearchResult]:
        url = self.settings.web_search_base_url or DUCKDUCKGO_ENDPOINT
        try:
            async with self._client() as client:
                response = await client.get(
                    url,
                    params={"q": query},
                    headers={"Accept": "text/html,application/xhtml+xml"},
                )
        except httpx.TimeoutException as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED, "DuckDuckGo timed out."
            ) from error
        except httpx.HTTPError as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED, "DuckDuckGo request failed."
            ) from error

        if response.status_code != 200:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                f"DuckDuckGo returned HTTP {response.status_code}.",
            )

        body = response.text
        if "anomaly-modal" in body or "challenge-form" in body:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                "DuckDuckGo returned an anti-bot challenge. Configure a Brave "
                "Search key in WEB_SEARCH_API_KEY and set WEB_SEARCH_PROVIDER=brave.",
            )

        parser = _DuckDuckGoParser()
        try:
            parser.feed(body)
            parser.close()
        except Exception as error:
            raise ToolExecutionError(
                ToolErrorCode.WEB_SEARCH_FAILED,
                "DuckDuckGo returned a page that could not be parsed.",
            ) from error

        items = [
            WebSearchResult(
                title=result["title"],
                url=result["url"],
                snippet=result["snippet"],
            )
            for result in parser.results
            if result["title"] and _is_http_url(result["url"])
        ]
        return items[:limit]


class _DuckDuckGoParser(HTMLParser):
    """Extract ``result__a`` titles and ``result__snippet`` text.

    The HTML endpoint renders results as anchors with those two class names.
    A small state machine is enough; it does not try to be a general-purpose
    scraper.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._capture: str | None = None
        self._depth = 0
        self._href = ""
        self._buffer: list[str] = []
        self._attach_snippet = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {name: value or "" for name, value in attrs}
        classes = attributes.get("class", "").split()

        if self._capture is not None:
            if tag.lower() not in _VOID_TAGS:
                self._depth += 1
            else:
                self._buffer.append(" ")
            return

        if tag.lower() == "a" and "result__a" in classes:
            self._start("title", attributes.get("href", ""))
        elif "result__snippet" in classes:
            self._start("snippet", "")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if self._capture is not None:
            self._buffer.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None or tag.lower() in _VOID_TAGS:
            return
        if self._depth > 0:
            self._depth -= 1
            return
        self._finish()

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)

    def _start(self, capture: str, href: str) -> None:
        self._capture = capture
        self._depth = 0
        self._href = href
        self._buffer = []
        if capture == "title":
            self._attach_snippet = False

    def _finish(self) -> None:
        text = _clean("".join(self._buffer))
        if self._capture == "title":
            url = _unwrap_duckduckgo(self._href)
            if text and _is_http_url(url):
                self.results.append({"title": text, "url": url, "snippet": ""})
                self._attach_snippet = True
        elif self._capture == "snippet" and self._attach_snippet and self.results:
            self.results[-1]["snippet"] = text
        self._capture = None
        self._buffer = []
        self._href = ""


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _plain(value: object) -> str:
    """Brave occasionally decorates descriptions with small HTML tags."""
    return _clean(re.sub(r"<[^>]+>", " ", str(value or "")))


def _is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


def _unwrap_duckduckgo(href: str) -> str:
    value = unescape(href.strip())
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/l/"):
        value = "https://duckduckgo.com" + value

    try:
        parts = urlsplit(value)
    except ValueError:
        return value

    host = (parts.hostname or "").lower()
    if (host == "duckduckgo.com" or host.endswith(".duckduckgo.com")) and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        if target:
            return unquote(target[0])
    return value


__all__ = ("WebSearchTool",)
