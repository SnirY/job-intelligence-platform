"""The OCR adapters, below the point where the pipeline reaches for them.

None of this needs Tesseract installed. Rasterising is pure `pypdfium2`, the
result arithmetic is arithmetic, and the engine's availability check is exercised
by turning it off. That separation is half the reason `OcrEngine` is a protocol:
recognition needs a system binary, and a unit suite that needed one too would be
a suite most developers could not run.
"""

from __future__ import annotations

from io import BytesIO

import pytest

from jip_api.infrastructure.extraction.ocr import OcrPage, OcrResult, get_ocr_engine, rasterise
from tests.document_fixtures import RESUME_LINES, pdf_bytes

# --- The document-level confidence figure --------------------------------------


def test_confidence_is_weighted_by_how_much_text_each_page_held() -> None:
    """A three-word cover page read perfectly must not outvote the work history.

    A plain mean would let it. The figure exists to answer "how much of what I
    am about to read was guessed at", and that question is about characters,
    not about pages.
    """
    result = OcrResult(
        pages=(
            OcrPage(text="x" * 3, confidence=100.0),
            OcrPage(text="y" * 297, confidence=50.0),
        )
    )

    assert result.confidence == pytest.approx(50.5)


def test_confidence_of_nothing_is_zero_rather_than_a_division_error() -> None:
    assert OcrResult(pages=()).confidence == 0.0


def test_pages_are_joined_the_way_the_pdf_reader_joins_them() -> None:
    result = OcrResult(pages=(OcrPage("one", 90.0), OcrPage("two", 90.0)))

    assert result.text == "one\n\ntwo"


# --- Rasterising ---------------------------------------------------------------


def test_renders_one_image_per_page() -> None:
    pages = list(rasterise(pdf_bytes(RESUME_LINES), dpi=72, max_pages=10))

    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG")


def test_dpi_decides_the_size_of_the_bitmap() -> None:
    """PDF user space is 72 units to the inch, so 144 DPI is exactly double.

    Worth asserting rather than assuming: the scale is a ratio the caller never
    sees, and getting it wrong produces a page that still renders and still
    reads, only worse.
    """
    from PIL import Image

    def width(dpi: int) -> int:
        page = next(iter(rasterise(pdf_bytes(RESUME_LINES), dpi=dpi, max_pages=1)))
        with Image.open(BytesIO(page)) as image:
            # Pillow ships no type information; re-typed here rather than
            # widening the whole file to Any.
            return int(image.width)

    assert width(144) == pytest.approx(width(72) * 2, abs=2)


def test_pages_are_greyscale() -> None:
    """Recognition does not use colour, and dropping it is a third of the bytes."""
    from PIL import Image

    page = next(iter(rasterise(pdf_bytes(RESUME_LINES), dpi=72, max_pages=1)))
    with Image.open(BytesIO(page)) as image:
        assert image.mode == "L"


def test_max_pages_is_a_hard_stop() -> None:
    pages = list(rasterise(pdf_bytes(RESUME_LINES), dpi=72, max_pages=0))

    assert pages == []


def test_nothing_is_rendered_until_it_is_asked_for() -> None:
    """A generator, not a list. Twenty A4 pages at 300 DPI is over 100 MB."""
    pages = rasterise(pdf_bytes(RESUME_LINES), dpi=300, max_pages=10)

    assert not isinstance(pages, list)


# --- Whether there is an engine at all -----------------------------------------


def test_no_engine_when_ocr_is_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off returns the pipeline to refusing scans, which is what it did before.

    A missing engine is not an error anywhere above this line, so this has to be
    `None` rather than something that raises when used.
    """
    from jip_config import get_settings

    monkeypatch.setenv("JIP_OCR_ENABLED", "false")
    get_settings.cache_clear()

    assert get_ocr_engine() is None
