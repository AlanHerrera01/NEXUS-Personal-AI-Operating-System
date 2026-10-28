from datetime import datetime

from app.domain.ports.tool import ToolOutput

SKILL_NAME = "web"


class WebSearchResult(ToolOutput):
    """One result as the model sees it.

    Snippets are short by nature. Full page text only arrives through
    ``web.fetch``, which fences it as untrusted data.
    """

    title: str
    url: str
    snippet: str = ""


class WebSearchOutput(ToolOutput):
    query: str
    provider: str
    items: list[WebSearchResult]
    count: int


class WebFetchOutput(ToolOutput):
    url: str
    title: str = ""
    content_type: str
    status_code: int
    #: Already passed through the prompt-injection fence. The caller sees the
    #: delimiters on purpose: they mark the block as data, not instructions.
    content: str
    truncated: bool = False
    fetched_at: datetime
