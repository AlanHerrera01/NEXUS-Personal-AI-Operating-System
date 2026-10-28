"""Turn an HTML document into readable text.

Deliberately stdlib-only. A full HTML parser would be another dependency on the
path of a tool that only needs the prose, and the pages this fetches are
ordinary articles and documentation, not hostile parser fuzzing corpora.
Malformed markup falls back to a tag-stripping pass rather than failing the
fetch.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

#: Elements whose text is navigation or code, not the article body.
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "canvas", "iframe"}
)

#: Elements that start a new visual line. Without this the whole page arrives
#: as one paragraph and the model loses all structure.
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)

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


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self._title_parts: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_depth += 1
            return
        if tag in _VOID_TAGS:
            if tag in _BLOCK_TAGS:
                self._parts.append("\n")
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        # ``<br/>`` must not be treated as a container: incrementing the depth
        # for it would swallow the rest of the document.
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            return
        if self._skip_depth:
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            if self._title_depth:
                self._title_depth -= 1
            return
        if tag in _BLOCK_TAGS and tag not in _VOID_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._title_depth:
            self._title_parts.append(data)
            return
        self._parts.append(data)

    def title(self) -> str:
        return _collapse("".join(self._title_parts), keep_lines=False)

    def text(self) -> str:
        return _collapse("".join(self._parts), keep_lines=True)


def extract_html_text(document: str) -> tuple[str, str]:
    """Return ``(title, text)`` for an HTML document.

    The title is separate because a page's heading is useful metadata even when
    the body is mostly scripts and navigation.
    """

    if not document:
        return "", ""

    parser = _HtmlTextExtractor()
    try:
        parser.feed(document)
        parser.close()
    except Exception:
        # html.parser is tolerant, but a truncated or genuinely broken document
        # should still yield text rather than fail the whole fetch.
        return _fallback_title(document), _fallback_text(document)

    text = parser.text()
    title = parser.title()
    if not text.strip():
        text = _fallback_text(document)
    return title, text


def _collapse(value: str, *, keep_lines: bool) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    if keep_lines:
        # Keep paragraph breaks, drop the runs of blank lines that tag soup
        # produces.
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1] != "":
                cleaned.append("")
        return "\n".join(cleaned).strip()
    return " ".join(part for part in lines if part).strip()


def _fallback_title(document: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", document, re.I | re.S)
    return _collapse(unescape(match.group(1)), keep_lines=False) if match else ""


def _fallback_text(document: str) -> str:
    without_skipped = re.sub(
        r"<(script|style|noscript|template|svg|canvas|iframe)\b[^>]*>.*?</\1>",
        " ",
        document,
        flags=re.I | re.S,
    )
    without_tags = re.sub(r"<[^>]+>", "\n", without_skipped)
    return _collapse(unescape(without_tags), keep_lines=True)


__all__ = ("extract_html_text",)
