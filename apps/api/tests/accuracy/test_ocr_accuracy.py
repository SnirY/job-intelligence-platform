"""How well the engine actually reads, in numbers.

Phase 14, slice 3. The two slices before this built the path and recorded which
one ran. Neither established whether the reading is any good, and the job this
work came from describes itself as improving an extraction pipeline **for
accuracy** — which is not a thing you can claim, only a thing you can measure.

## Where the truth comes from

`pdf_bytes` builds a real single-page PDF with a Helvetica text stream. The
lines handed to it are, by construction, exactly what is on the page, so the
ground truth is not transcribed, guessed, or committed as a binary fixture: it
is the input. The same PDF is then rendered to a bitmap and read back as if
nobody had ever seen it.

## The first version of this file measured nothing

It compared 300 DPI against 120 and asserted the coarser read was worse. Both
came back at **0.0000** character error, and the assertion failed as
`0.0 > 0.0`. A crisply rendered page of 12pt Helvetica is readable all the way
down to 100 DPI — far past where the folklore says Tesseract gives up.

That is the whole argument for measuring rather than assuming, and it is why
`scan_fixtures.degrade` exists. The numbers below are from the sweep that
followed:

    dpi (clean render)        300 → 100   CER 0.0000
                              60          CER 0.0451
                              50          CER 0.5417
                              40          CER 1.0000  (nothing read at all)

    300 dpi, degraded         clean               CER 0.0000   conf 94.5
                              skew 1.5° blur 2.5  CER 0.0903   conf 93.0
                              skew 2.5° blur 3.5  CER 0.4549   conf 86.9
                              skew 3.5° blur 4.5  CER 0.1979   conf 53.4

Read the last two rows again. They are the finding of this slice.

## Needs Tesseract

The binary lives in the API image, not on a developer's machine. These skip
with a reason when it is absent rather than failing, because "not installed"
and "reads badly" are different answers.
"""

from __future__ import annotations

import pytest

from jip_api.application.resumes import looks_like_a_resume
from jip_api.infrastructure.extraction.ocr import OcrResult, TesseractEngine, rasterise
from tests.document_fixtures import RESUME_LINES, pdf_bytes
from tests.ocr_metrics import character_error_rate, word_error_rate
from tests.scan_fixtures import degrade

pytestmark = pytest.mark.ocr

TRUTH = "\n".join(RESUME_LINES)

CLEAN_CER_CEILING = 0.05
"""Measured at 0.0000. The ceiling is loose on purpose.

A regression guard, not a target: it should catch a language pack going missing
or the engine falling back to the pre-4.0 recogniser, and it should not fail
because a point release moved a hundredth.
"""

BADLY_SCANNED = {"skew_degrees": 2.5, "blur_radius": 3.5}
"""Measured at CER 0.4549 — bad enough to be interesting, short of unreadable."""


@pytest.fixture(scope="module")
def engine() -> TesseractEngine:
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
    except Exception as error:  # pragma: no cover - depends on the host
        pytest.skip(f"tesseract is not installed here: {error}")

    return TesseractEngine()


def read_at(engine: TesseractEngine, dpi: int, **damage: float) -> OcrResult:
    """Render the fixture at `dpi`, optionally spoil it, and read it back."""
    pages = [
        degrade(page, **damage) for page in rasterise(pdf_bytes(RESUME_LINES), dpi=dpi, max_pages=1)
    ]
    return engine.read(pages, languages="eng")


def test_a_clean_page_reads_within_the_ceiling(engine: TesseractEngine) -> None:
    result = read_at(engine, 300)
    cer = character_error_rate(TRUTH, result.text)
    wer = word_error_rate(TRUTH, result.text)

    # Printed whether or not it passes. A figure drifting toward the ceiling is
    # the thing worth knowing, and a test that only speaks when it fails cannot
    # say that.
    print(f"\n  clean 300 dpi   CER {cer:.4f}   WER {wer:.4f}   conf {result.confidence:.1f}")

    assert cer <= CLEAN_CER_CEILING, (
        f"A crisply rendered page read at {cer:.1%} character error, over the "
        f"{CLEAN_CER_CEILING:.0%} ceiling. Something is wrong with the engine "
        f"or its language data, not with the page.\n\nRead back:\n{result.text}"
    )


def test_the_words_that_matter_survive(engine: TesseractEngine) -> None:
    """A rate is an average, and an average hides the line that counts.

    A name and an employer are what the parser is looking for, and they are also
    where OCR is weakest: an ordinary word has a dictionary to fall back on and
    a proper noun has nothing.
    """
    read = read_at(engine, 300).text

    for phrase in ("MAYA OKONKWO", "Verdant Logistics", "FastAPI", "PostgreSQL"):
        assert phrase in read, f"{phrase!r} did not survive the round trip.\n\n{read}"


def test_resolution_is_what_decides_accuracy(engine: TesseractEngine) -> None:
    """The highest-leverage knob, asserted as a relation rather than a budget.

    50 DPI rather than the 120 this test first used, because at 120 the page
    still reads perfectly. The cliff is between 60 and 50 on this fixture — and
    the useful lesson is not the number but its shape: accuracy holds flat over
    a wide range and then collapses, rather than degrading smoothly. Sampling
    below the strokes does not make reading harder, it makes it impossible.
    """
    fine = character_error_rate(TRUTH, read_at(engine, 300).text)
    coarse = character_error_rate(TRUTH, read_at(engine, 50).text)

    print(f"\n  300 dpi CER {fine:.4f}   50 dpi CER {coarse:.4f}")

    assert coarse > fine, (
        f"50 DPI read as well as 300 ({coarse:.4f} vs {fine:.4f}). Either the "
        "fixture is too forgiving to measure with, or rasterise is ignoring the "
        "dpi it was given."
    )


def test_mean_confidence_is_not_a_proxy_for_accuracy(engine: TesseractEngine) -> None:
    """The finding of this slice, written down so nobody assumes it away.

    Two degraded reads of the same page:

        skew 2.5° blur 3.5    CER 0.4549    confidence 86.9
        skew 3.5° blur 4.5    CER 0.1979    confidence 53.4

    **The worse read reported the higher confidence.** Not noise — a property of
    what the number is. Mean word confidence averages the words the engine chose
    to emit. When it is badly confused it drops the hard ones entirely, and a
    dropped word is a deletion: it wrecks the error rate and never appears in
    the average. Confidence measures the words it kept, not the words it lost.

    So `ocr_min_confidence` is a backstop against a page of noise, not a quality
    gate, and the real protection is `MINIMUM_USEFUL_CHARS` above it and the
    review screen below it. A future version wanting a genuine signal should
    count the words *below* a threshold rather than average all of them.

    Asserted rather than merely recorded: if a Tesseract release ever makes
    confidence track error, this fails and somebody re-reads the finding instead
    of inheriting a stale conclusion.
    """
    worse_read = read_at(engine, 300, skew_degrees=2.5, blur_radius=3.5)
    better_read = read_at(engine, 300, skew_degrees=3.5, blur_radius=4.5)

    worse_cer = character_error_rate(TRUTH, worse_read.text)
    better_cer = character_error_rate(TRUTH, better_read.text)

    print(f"\n  CER {worse_cer:.4f} at confidence {worse_read.confidence:.1f}")
    print(f"  CER {better_cer:.4f} at confidence {better_read.confidence:.1f}")

    assert worse_cer > better_cer, "The two damage levels no longer bracket the effect."
    assert worse_read.confidence > better_read.confidence, (
        "Mean confidence now tracks character error on this fixture, which it "
        "did not when this was written. Good news, and it means the reasoning "
        "in `ocr_min_confidence` and in this docstring needs revisiting."
    )


def test_the_gate_still_accepts_a_badly_scanned_resume(engine: TesseractEngine) -> None:
    """The risk this phase named in advance, and the answer is no.

    `looks_like_a_resume.check()` runs on extracted text **before** any model
    sees it, and its thresholds were tuned against clean extraction. The worry
    was that OCR noise would push a real resume below them, so the user is told
    "this does not look like a resume" when the truth is "we read it badly" — a
    refusal that blames the document for our error.

    It does not happen. The gate holds at 45% character error, and only fails
    when nothing legible comes back at all, which is the right answer. Tested
    against a spoiled scan rather than a clean one: a clean read passes for
    reasons that have nothing to do with the risk.
    """
    assert looks_like_a_resume.check(TRUTH).is_resume, (
        "The fixture does not pass the gate even as a perfect text layer, so "
        "this test cannot say anything about OCR."
    )

    result = read_at(engine, 300, **BADLY_SCANNED)
    verdict = looks_like_a_resume.check(result.text)
    cer = character_error_rate(TRUTH, result.text)

    print(f"\n  badly scanned   CER {cer:.4f}   gate {verdict.is_resume}   {verdict.found}")

    assert verdict.is_resume, (
        f"OCR noise at {cer:.1%} character error pushed a real resume below the "
        f"gate. The user would be told it does not look like a resume. Signals "
        f"found: {verdict.found}\n\nRead back:\n{result.text}"
    )
