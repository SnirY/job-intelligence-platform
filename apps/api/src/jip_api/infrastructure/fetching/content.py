"""Pulling the job description out of a fetched page.

Implements ``ContentExtractor`` from ``docs/10-api-contracts.md``:
``extract(raw_content) -> ExtractedContent``.

``docs/04-system-architecture.md`` keeps URL fetching and semantic parsing
separate, and this sits between them: it is mechanical, not semantic. It knows
that ``<script>`` is not prose and that a navigation bar is not a job
description. It does not know what a requirement is — that is Phase 5's job.

Written on ``html.parser`` rather than a parsing library because the task is
narrow and a dependency here would be carried for the life of the project to
do what forty lines of state machine already do. The extraction is also
deliberately lossy in only one direction: the untouched HTML is kept on the
import record, so a better extractor later can re-read it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Elements whose text is never content. Their contents are skipped entirely
# rather than stripped afterwards, so an inline script's source never lands in
# the middle of a description.
_SKIP_CONTENT = frozenset({"script", "style", "noscript", "template", "svg", "canvas", "iframe"})

# Structural furniture. Present on every page and part of none of them.
_CHROME = frozenset({"nav", "header", "footer", "aside", "form", "button", "select"})

# Elements that end a line of prose.
_BLOCK = frozenset(
    {
        "p", "div", "section", "article", "br", "li", "ul", "ol", "tr", "table",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dd", "dt", "dl",
    }
)  # fmt: skip

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_INLINE_SPACE = re.compile(r"[ \t]{2,}")

MINIMUM_USEFUL_CHARS = 200
"""Below this, the extraction did not find a job description.

Job postings behind a JavaScript-rendered single-page app return a shell with
almost no text. Reporting that plainly, so the user can paste instead, is more
useful than storing forty characters of boilerplate and calling it a success.
"""


@dataclass(slots=True)
class ExtractedContent:
    """The readable text of a page."""

    text: str
    title: str | None = None
    """The document title. Offered to the user as a *suggestion* only.

    ``docs/11-engineering-standards.md`` says never trust external metadata, and
    a page title is written by whoever wrote the page. It is shown pre-filled
    and editable, never stored as a fact without the user seeing it.
    """

    headings: list[str] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    """Collects readable text, tracking what it is currently inside."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._chrome_depth = 0
        self._in_title = False
        self._in_heading = False
        self.title: str | None = None
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
            return
        if tag in _CHROME:
            self._chrome_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._in_heading = True

        if tag in _BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _CHROME:
            self._chrome_depth = max(0, self._chrome_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3"}:
            self._in_heading = False

        if tag in _BLOCK:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return

        if self._in_title:
            # Titles are collected even inside <head>, which is otherwise chrome.
            self.title = (self.title or "") + data
            return

        if self._chrome_depth:
            return

        if not data.strip():
            # Whitespace between tags still separates words: "Senior</b> <b>Engineer"
            # must not become "SeniorEngineer".
            self._parts.append(" ")
            return

        if self._in_heading:
            heading = data.strip()
            if heading:
                self.headings.append(heading)

        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def extract_content(raw: str) -> ExtractedContent:
    """Extract readable text from HTML, or return the input if it is not HTML.

    Plain text passes through untouched. A pasted description that happens to
    contain an angle bracket must not be mangled by an HTML parser.
    """
    if not _looks_like_html(raw):
        return ExtractedContent(text=_tidy(raw))

    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        # html.parser is lenient, but a pathological document can still raise.
        # Whatever was collected before the failure is better than nothing, and
        # the untouched HTML is on the import record either way.
        pass

    return ExtractedContent(
        text=_tidy(parser.text()),
        title=_tidy_line(parser.title),
        headings=parser.headings[:20],
    )


def _looks_like_html(raw: str) -> bool:
    """Whether the content should go through the HTML parser.

    Checks the opening of the document rather than searching the whole thing:
    a pasted description mentioning ``<div>`` in a code sample is not a web
    page.
    """
    head = raw.lstrip()[:512].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<body" in head


def _tidy(text: str) -> str:
    """Normalise whitespace without changing the words.

    Whitespace only. Anything cleverer would be editing the posting, and the
    original is what the user will compare against.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _INLINE_SPACE.sub(" ", text)
    text = _TRAILING_SPACE.sub("\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def _tidy_line(value: str | None) -> str | None:
    if not value:
        return None
    collapsed = " ".join(value.split())
    return collapsed[:300] or None


def has_useful_content(text: str) -> bool:
    """Whether the extraction produced enough to be a job description."""
    return len(text.strip()) >= MINIMUM_USEFUL_CHARS
