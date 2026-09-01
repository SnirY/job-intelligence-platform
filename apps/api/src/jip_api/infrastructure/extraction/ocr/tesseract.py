"""Tesseract, and the decision about whether there is an engine at all.

Since version 4 Tesseract recognises a **whole text line with an LSTM** rather
than classifying one character at a time, which is why it copes with joined and
imperfect glyphs far better than its own older releases — a distinction worth
keeping straight, because most of what is written about "Tesseract's accuracy"
predates it.

It needs the `tesseract-ocr` system binary and a language pack per script. Both
arrive through the image; neither is a Python dependency. When the binary is
absent this module says so once and returns no engine, and the pipeline behaves
exactly as it did before OCR existed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from io import BytesIO

from jip_api.infrastructure.extraction.ocr.base import OcrEngine, OcrPage, OcrResult
from jip_config import get_settings

logger = logging.getLogger(__name__)

_PAGE_SEGMENTATION_MODE = 3
"""Fully automatic page segmentation, without orientation detection.

`--psm` is the flag that decides how Tesseract *looks* for text — a whole page,
one uniform block, a single line, sparse text — and the wrong one is the most
common cause of poor output on a document that looks easy. 3 is right for a
resume: a full page with a layout to find. A caller that knows it is holding a
single line would want 7, and would be wrong to use this.
"""

_LSTM_ONLY = 1
"""`--oem`. The neural line recogniser, without the pre-4.0 character classifier.

Asked for explicitly rather than left at the default, which may fall back to the
legacy engine when a language pack happens to carry the old data files — a
silent halving of accuracy that looks like nothing at all.
"""


class TesseractEngine:
    """Reads pages with Tesseract, keeping the confidence it reports.

    Bounded by a wall-clock budget for the whole document. A page it cannot
    segment does not fail -- it searches, and it will search for as long as it
    is given. A photograph of a CV spent 823 seconds across two pages here and
    produced the four characters `HAAN`, which is a worker held for a quarter of
    an hour on work that was always going to be refused (DEV-085).

    When the budget runs out the pages read so far are returned rather than an
    error. What came back may still be enough, and it is not this class's
    business to decide: `MINIMUM_USEFUL_CHARS` already makes that call.
    """

    name = "tesseract"

    def __init__(self, budget_seconds: float) -> None:
        self.budget_seconds = budget_seconds

    def read(self, pages: Iterable[bytes], *, languages: str) -> OcrResult:
        deadline = time.monotonic() + self.budget_seconds
        config = f"--oem {_LSTM_ONLY} --psm {_PAGE_SEGMENTATION_MODE}"
        read_pages: list[OcrPage] = []

        for index, png in enumerate(pages):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Stopped reading a document before the end of it: out of time",
                    extra={"pages_read": index, "budget_seconds": self.budget_seconds},
                )
                break

            import pytesseract
            from PIL import Image

            try:
                with Image.open(BytesIO(png)) as image:
                    # `image_to_data`, not `image_to_string`. The string form
                    # throws the confidence away, and confidence is the whole
                    # reason a reviewer can be told which parts were guessed at.
                    data = pytesseract.image_to_data(
                        image,
                        lang=languages,
                        config=config,
                        output_type=pytesseract.Output.DICT,
                        timeout=remaining,
                    )
            except RuntimeError as error:
                # What pytesseract raises when it kills the subprocess. The page
                # is lost, not the document: an earlier page may already carry
                # enough, and a later one cannot be reached anyway.
                logger.warning(
                    "Gave up on a page that would not resolve",
                    extra={"page": index, "seconds_left": round(remaining, 1), "error": str(error)},
                )
                break

            read_pages.append(_page_from(data))

        return OcrResult(pages=tuple(read_pages))


def _page_from(data: dict[str, list[object]]) -> OcrPage:
    """Assemble Tesseract's word table back into lines of text.

    The table is one row per word, with `block_num`, `par_num` and `line_num`
    saying where each sat. Joining on those keeps line breaks that the plain
    string output also keeps — but it keeps the per-word confidence with them,
    which the string output does not.

    Rows with a confidence of -1 are the ones Tesseract emits for structure
    rather than for text: page, block and paragraph boundaries. They carry no
    word and must not drag the mean down.
    """
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []

    for index, raw_text in enumerate(data.get("text", [])):
        word = str(raw_text).strip()
        confidence = float(str(data["conf"][index]))
        if not word or confidence < 0:
            continue

        key = (
            int(str(data["block_num"][index])),
            int(str(data["par_num"][index])),
            int(str(data["line_num"][index])),
        )
        lines.setdefault(key, []).append(word)
        confidences.append(confidence)

    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrPage(text=text, confidence=mean)


def get_ocr_engine() -> OcrEngine | None:
    """The engine to use, or nothing.

    One place decides whether OCR exists; the extraction step only decides
    whether to reach for it. That split is why the pipeline needs no opinion
    about installation, configuration or availability.

    Returns `None` when OCR is switched off, when the Python binding is missing,
    or when the binary is not installed — the last being the ordinary state of a
    developer machine. A missing engine is not an error: it leaves the pipeline
    behaving exactly as it did before this existed, which is a refusal with a
    clear message rather than a crash.
    """
    settings = get_settings()
    if not settings.ocr_enabled:
        return None

    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception as error:
        logger.warning(
            "OCR is enabled but Tesseract is unavailable; scanned documents will be refused",
            extra={"error": str(error)},
        )
        return None

    return TesseractEngine(budget_seconds=settings.ocr_budget_seconds)
