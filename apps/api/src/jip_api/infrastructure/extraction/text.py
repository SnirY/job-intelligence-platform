"""Pulling text out of an uploaded document.

Infrastructure, not domain: it deals with file formats and third-party parsers.
Two formats are supported, and *supported* here means the whole chain works —
upload validation accepts it, extraction reads it, the parser is tested against
it. Accepting an upload we cannot read would be the worst of both, since the
user learns it failed only after waiting.

A document with no text layer — a scan, a photo of a printout — is a real and
common case. It used to be reported as ``CONTENT_UNAVAILABLE`` and never
retried, with a message asking the user to go and find a different file. It is
now read with OCR when an engine is available, and refused only when that also
comes back empty. The refusal stays permanent: the bytes will not grow words on
a second attempt.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from xml.etree import ElementTree

from jip_ai import AIError, AIFailureCode
from jip_api.application.documents.upload import DOCX, PDF
from jip_api.infrastructure.extraction.ocr import OcrEngine, rasterise
from jip_config import get_settings

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


class TextSource(StrEnum):
    """How the text was obtained, which is not a detail.

    A text layer is what the document itself says its glyphs are: exact, by
    construction. OCR is a reading of a picture, and a good reading is still a
    reading. Anything that shows this text to a person has to be able to say
    which of the two it got, because they deserve different amounts of trust.
    """

    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """Text recovered from a document."""

    text: str
    page_count: int | None = None
    """Pages, where the format has them. Null for DOCX, which has no fixed
    pagination until it is rendered."""

    source: TextSource = TextSource.TEXT_LAYER
    confidence: float | None = None
    """Mean confidence, 0 to 100, when the text came from OCR. Null otherwise.

    Null rather than 100, because a text layer has no confidence rather than
    perfect confidence. Writing 100 would make the two indistinguishable to
    everything downstream — the same mistake as recording an absent date as an
    unknown one.
    """


def extract_text(
    data: bytes,
    *,
    content_type: str,
    ocr: OcrEngine | None = None,
) -> ExtractedText:
    """Extract text from ``data``.

    Raises :class:`~jip_ai.AIError` — the shared classified-failure type, so the
    pipeline handles an extraction failure and a parsing failure through one
    path rather than two.

    ``ocr`` is reached for **only** when the document turns out to have no
    usable text layer. Recognition costs seconds of processor time per page and
    a text layer is exact, so trying an engine speculatively would be slower and
    worse at once. With no engine supplied, the behaviour is what it was before
    OCR existed.
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
    if len(cleaned.strip()) >= MINIMUM_USEFUL_CHARS:
        return ExtractedText(text=cleaned, page_count=extracted.page_count)

    if content_type == PDF and ocr is not None:
        return _read_with_ocr(data, ocr, page_count=extracted.page_count)

    raise AIError(
        AIFailureCode.CONTENT_UNAVAILABLE,
        "No readable text was found in this document. If it is a scan or a "
        "photo, upload a text-based PDF or a DOCX instead.",
        details=f"recovered {len(cleaned.strip())} characters",
    )


def _read_with_ocr(data: bytes, ocr: OcrEngine, *, page_count: int | None) -> ExtractedText:
    """Read the pages as pictures, because the file had nothing else to give.

    Every failure below is ``CONTENT_UNAVAILABLE`` and therefore permanent, for
    the reason the module opens with: a retry reads the same bytes.

    **None of these messages may suggest uploading a text-based PDF.** That
    sentence was true while this was the only path. Now that the pages have been
    rendered and read, telling somebody to take a step already taken is worse
    than saying nothing.
    """
    settings = get_settings()

    try:
        result = ocr.read(
            rasterise(data, dpi=settings.ocr_dpi, max_pages=settings.ocr_max_pages),
            languages=settings.ocr_languages,
        )
    except Exception as exc:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "This document could not be read as a scan.",
            details=f"{type(exc).__name__}: {exc}",
        ) from exc

    cleaned = _normalize(result.text)
    recovered = len(cleaned.strip())

    if recovered < MINIMUM_USEFUL_CHARS:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "We read this as a scan and found no text on the pages. If they are "
            "photographs, a straighter and sharper scan usually works.",
            details=f"ocr recovered {recovered} characters",
        )

    if result.confidence < settings.ocr_min_confidence:
        # Refused rather than passed on with a warning. What comes next is a
        # model call on text nobody has read, and a review screen full of
        # confident sentences built from a bad transcript is more convincing and
        # less useful than an error — the argument DEV-020 already makes about
        # documents that are not resumes.
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "We read this as a scan, and what came back was too unclear to use. "
            "A sharper scan, or the original file if you still have it, would "
            "work better.",
            details=f"ocr confidence {result.confidence:.1f} over {recovered} characters",
        )

    logger.info(
        "Recovered document text with OCR",
        extra={
            "engine": ocr.name,
            "characters": recovered,
            "confidence": round(result.confidence, 1),
            "pages": len(result.pages),
        },
    )
    return ExtractedText(
        text=cleaned,
        page_count=page_count,
        source=TextSource.OCR,
        confidence=result.confidence,
    )


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
