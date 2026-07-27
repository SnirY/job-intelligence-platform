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
from jip_api.infrastructure.extraction import extract_text
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
