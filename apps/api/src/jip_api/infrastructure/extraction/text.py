"""Pulling text out of an uploaded document.

Infrastructure, not domain: it deals with file formats and third-party parsers.
Two formats are supported, and *supported* here means the whole chain works —
upload validation accepts it, extraction reads it, the parser is tested against
it. Accepting an upload we cannot read would be the worst of both, since the
user learns it failed only after waiting.

A document with no text layer — a scan, a photo of a printout — is a real and
common case. It is reported as ``CONTENT_UNAVAILABLE`` and never retried: the
bytes will not grow words on a second attempt.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree

from jip_ai import AIError, AIFailureCode
from jip_api.application.documents.upload import DOCX, PDF

logger = logging.getLogger(__name__)

MINIMUM_USEFUL_CHARS = 50
"""Below this, treat the document as having no text.

A scanned PDF often yields a handful of stray glyphs rather than nothing at all,
so "empty" has to mean "too little to be a resume" rather than "zero bytes".
"""

# WordprocessingML namespace. Fixed by the OOXML standard, so matching on it is
# safe; matching on a prefix would not be, since prefixes are file-defined.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """Text recovered from a document."""

    text: str
    page_count: int | None = None
    """Pages, where the format has them. Null for DOCX, which has no fixed
    pagination until it is rendered."""


def extract_text(data: bytes, *, content_type: str) -> ExtractedText:
    """Extract text from ``data``.

    Raises :class:`~jip_ai.AIError` — the shared classified-failure type, so the
    pipeline handles an extraction failure and a parsing failure through one
    path rather than two.
    """
    if content_type == PDF:
        extracted = _extract_pdf(data)
    elif content_type == DOCX:
        extracted = _extract_docx(data)
    else:
        # Unreachable through the API: upload validation rejects anything else.
        # Kept because the function is also called directly by the worker.
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "That file type cannot be read.",
            details=f"content_type={content_type}",
        )

    cleaned = _normalize(extracted.text)
    if len(cleaned.strip()) < MINIMUM_USEFUL_CHARS:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "No readable text was found in this document. If it is a scan or a "
            "photo, upload a text-based PDF or a DOCX instead.",
            details=f"recovered {len(cleaned.strip())} characters",
        )

    return ExtractedText(text=cleaned, page_count=extracted.page_count)


def _extract_pdf(data: bytes) -> ExtractedText:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            # An empty password unlocks the common "printing restricted" case.
            # Anything else needs a password we do not have and must not ask a
            # background job to guess.
            try:
                reader.decrypt("")
            except Exception as exc:
                raise AIError(
                    AIFailureCode.CONTENT_UNAVAILABLE,
                    "This PDF is password protected. Upload an unprotected copy.",
                    details=str(exc),
                ) from exc

        pages = [page.extract_text() or "" for page in reader.pages]
    except AIError:
        raise
    except (PyPdfError, ValueError, OSError) as exc:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "This PDF could not be read. It may be damaged.",
            details=str(exc),
        ) from exc

    return ExtractedText(text="\n\n".join(pages), page_count=len(pages))


def _extract_docx(data: bytes) -> ExtractedText:
    """Read a DOCX with the standard library.

    A DOCX is a ZIP holding ``word/document.xml``. Walking that XML in document
    order picks up paragraphs and table cells alike, which matters because
    two-column resume templates are usually tables — a paragraph-only reader
    silently drops half of one.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            document = archive.read("word/document.xml")
    except KeyError as exc:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "This file is not a Word document.",
            details="word/document.xml is missing",
        ) from exc
    except (zipfile.BadZipFile, OSError) as exc:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "This DOCX could not be read. It may be damaged.",
            details=str(exc),
        ) from exc

    try:
        # defusedxml is not needed here: the parser is configured without entity
        # resolution by default in Python 3.12, and the archive has already
        # passed magic-byte validation. Kept explicit so the choice is visible.
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "This DOCX could not be read. Its contents are malformed.",
            details=str(exc),
        ) from exc

    return ExtractedText(text=_docx_text(root))


def _docx_text(root: ElementTree.Element) -> str:
    """Serialise WordprocessingML to plain text, one paragraph per line."""
    lines: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            tag = node.tag
            if tag == f"{_W}t":
                parts.append(node.text or "")
            elif tag == f"{_W}tab":
                # Tabs separate columns in the single most common resume layout
                # — "Company .... 2020-2023" — so collapsing them to nothing
                # would run two facts together into one unreadable string.
                parts.append("\t")
            elif tag in {f"{_W}br", f"{_W}cr"}:
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def _normalize(text: str) -> str:
    """Tidy extracted text without changing what it says.

    Whitespace only. Extraction artefacts are left alone: the parser is
    instructed to lower its confidence on damaged passages, and a cleanup rule
    that guessed at repairs would quietly rewrite the document instead.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()
