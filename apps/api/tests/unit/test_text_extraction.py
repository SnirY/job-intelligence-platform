"""Text extraction from real PDF and DOCX bytes.

Both formats are exercised against genuine files, because "supported" has to
mean the whole chain works. Accepting an upload the extractor cannot read would
mean the user waits for a job that was always going to fail.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from jip_ai import AIError, AIFailureCode
from jip_api.application.documents.upload import DOCX, PDF
from jip_api.domain.documents.models import TextSource
from jip_api.infrastructure.extraction import extract_text
from jip_api.infrastructure.extraction.ocr import OcrPage, OcrResult
from tests.document_fixtures import (
    RESUME_LINES,
    docx_bytes,
    docx_with_tabs,
    pdf_bytes,
    pdf_without_text_layer,
)

# --- PDF ----------------------------------------------------------------------


def test_reads_a_pdf() -> None:
    extracted = extract_text(pdf_bytes(RESUME_LINES), content_type=PDF)

    assert "MAYA OKONKWO" in extracted.text
    assert "FastAPI" in extracted.text
    assert extracted.page_count == 1


def test_a_pdf_with_no_text_layer_is_content_unavailable() -> None:
    """A scan. Not retriable — the bytes will not grow words on a second run."""
    with pytest.raises(AIError) as caught:
        extract_text(pdf_without_text_layer(), content_type=PDF)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert not caught.value.is_retriable
    assert "scan" in str(caught.value)


def test_a_damaged_pdf_is_reported_not_crashed() -> None:
    with pytest.raises(AIError) as caught:
        extract_text(b"%PDF-1.4\nthis is not really a pdf", content_type=PDF)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE


def test_a_pdf_with_only_a_few_characters_is_treated_as_empty() -> None:
    """Scans often yield a handful of stray glyphs rather than nothing, so the
    threshold has to be "too little to be a resume", not "zero bytes"."""
    with pytest.raises(AIError, match="No readable text"):
        extract_text(pdf_bytes(["a b"]), content_type=PDF)


# --- DOCX ---------------------------------------------------------------------


def test_reads_a_docx() -> None:
    extracted = extract_text(docx_bytes(RESUME_LINES), content_type=DOCX)

    assert "MAYA OKONKWO" in extracted.text
    assert "University of Lisbon" in extracted.text


def test_docx_page_count_is_unknown() -> None:
    """DOCX has no fixed pagination until it is rendered, so reporting a number
    would be inventing one."""
    assert extract_text(docx_bytes(RESUME_LINES), content_type=DOCX).page_count is None


def test_reads_text_inside_tables() -> None:
    """Two-column resume templates are tables.

    A paragraph-only reader silently drops half of one, and the failure looks
    like a parser that missed the user's whole work history.
    """
    data = docx_bytes(
        ["CURRICULUM VITAE", "A short profile paragraph to clear the minimum."],
        table_rows=[
            ["Verdant Logistics", "March 2023 - Present"],
            ["Ashcombe Digital", "2018 - 2020"],
        ],
    )

    text = extract_text(data, content_type=DOCX).text

    assert "Verdant Logistics" in text
    assert "Ashcombe Digital" in text


def test_tab_stops_separate_columns() -> None:
    """ "Company<tab>2020-2023" must not collapse into "Company2020-2023"."""
    data = docx_with_tabs(
        [
            ("Verdant Logistics", "March 2023 - Present"),
            ("A profile line long enough to clear the minimum text threshold.", ""),
        ]
    )

    text = extract_text(data, content_type=DOCX).text

    assert "Verdant Logistics\tMarch 2023" in text


def test_a_zip_without_a_document_part_is_rejected() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("unrelated.txt", "not a word document")

    with pytest.raises(AIError, match="not a Word document"):
        extract_text(buffer.getvalue(), content_type=DOCX)


def test_a_damaged_docx_is_reported_not_crashed() -> None:
    with pytest.raises(AIError) as caught:
        extract_text(b"PK\x03\x04 truncated", content_type=DOCX)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE


# --- shared -------------------------------------------------------------------


def test_an_unsupported_type_is_refused() -> None:
    with pytest.raises(AIError, match="cannot be read"):
        extract_text(b"plain text " * 20, content_type="text/plain")


def test_whitespace_is_normalised_without_changing_content() -> None:
    """Tidying is whitespace only. A cleanup rule that guessed at repairs would
    quietly rewrite the user's document."""
    data = docx_bytes(["First line", "", "", "", "Second line after many blanks", "x" * 60])

    text = extract_text(data, content_type=DOCX).text

    assert "\n\n\n" not in text
    assert "First line" in text and "Second line after many blanks" in text


# --- Falling back to OCR ------------------------------------------------------


class RecordingEngine:
    """An engine that says what it was asked to do.

    The point of most of these tests is *whether* it was called, so it counts.
    It also drains the iterable it is handed, because that iterable is the
    rasteriser and a test that never consumed it would pass without a single
    page ever being rendered.
    """

    name = "recording"

    def __init__(self, text: str = "", confidence: float = 90.0) -> None:
        self.calls = 0
        self.pages: list[bytes] = []
        self.languages: str | None = None
        self._page = OcrPage(text=text, confidence=confidence)

    def read(self, pages: object, *, languages: str) -> OcrResult:
        self.calls += 1
        self.pages = list(pages)  # type: ignore[call-overload]
        self.languages = languages
        return OcrResult(pages=(self._page,))


SCANNED_TEXT = "MAYA OKONKWO\nBackend Engineer, Lisbon\nBuilt REST endpoints in FastAPI."


def test_a_pdf_with_a_text_layer_never_reaches_the_engine() -> None:
    """Asserted, not assumed.

    A text layer is exact and free; recognition is a guess that costs seconds
    per page. Reaching for the engine speculatively would be slower and worse at
    the same time, and nothing about the returned text would reveal it had
    happened.
    """
    engine = RecordingEngine(text=SCANNED_TEXT)

    extracted = extract_text(pdf_bytes(RESUME_LINES), content_type=PDF, ocr=engine)

    assert engine.calls == 0
    assert extracted.source is TextSource.TEXT_LAYER
    assert extracted.confidence is None
    assert "MAYA OKONKWO" in extracted.text


def test_a_scan_is_read_with_ocr() -> None:
    engine = RecordingEngine(text=SCANNED_TEXT, confidence=88.0)

    extracted = extract_text(pdf_without_text_layer(), content_type=PDF, ocr=engine)

    assert engine.calls == 1
    assert extracted.source is TextSource.OCR
    assert extracted.confidence == 88.0
    assert "MAYA OKONKWO" in extracted.text
    # The pages really were rendered, rather than an empty generator being
    # handed over and quietly ignored.
    assert len(engine.pages) == 1
    assert engine.pages[0].startswith(b"\x89PNG")


def test_the_configured_languages_reach_the_engine() -> None:
    engine = RecordingEngine(text=SCANNED_TEXT)

    extract_text(pdf_without_text_layer(), content_type=PDF, ocr=engine)

    assert engine.languages == "eng+heb"


def test_a_scan_ocr_cannot_read_does_not_suggest_a_step_already_taken() -> None:
    """The message has to change once we have tried.

    "Upload a text-based PDF instead" was true while extraction was the only
    path. After rendering the pages and reading them it is advice to repeat work
    the platform has done, which is worse than saying nothing.
    """
    engine = RecordingEngine(text="")

    with pytest.raises(AIError) as caught:
        extract_text(pdf_without_text_layer(), content_type=PDF, ocr=engine)

    message = str(caught.value)
    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert not caught.value.is_retriable
    assert "text-based PDF" not in message
    assert "read this as a scan" in message


def test_a_scan_read_too_poorly_is_refused_rather_than_passed_on() -> None:
    """What comes next is a model call on text nobody has read.

    A review screen full of confident sentences built from a bad transcript is
    more convincing and less useful than an error.
    """
    engine = RecordingEngine(text=SCANNED_TEXT, confidence=12.0)

    with pytest.raises(AIError, match="too unclear to use"):
        extract_text(pdf_without_text_layer(), content_type=PDF, ocr=engine)


def test_an_engine_that_raises_is_reported_not_crashed() -> None:
    class BrokenEngine:
        name = "broken"

        def read(self, pages: object, *, languages: str) -> OcrResult:
            raise RuntimeError("tesseract is not installed")

    with pytest.raises(AIError) as caught:
        extract_text(pdf_without_text_layer(), content_type=PDF, ocr=BrokenEngine())

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert "could not be read as a scan" in str(caught.value)


def test_a_docx_with_no_text_is_not_sent_to_ocr() -> None:
    """OCR reads pictures of pages, and a DOCX has no pages until it is rendered.

    Rasterising one would mean laying it out first, which is a different problem
    and a different dependency.
    """
    engine = RecordingEngine(text=SCANNED_TEXT)

    with pytest.raises(AIError, match="No readable text"):
        extract_text(docx_bytes([""]), content_type=DOCX, ocr=engine)

    assert engine.calls == 0
