"""What an OCR engine is, to the rest of this codebase.

The protocol takes **page bitmaps and returns text**. It does not know about
PDFs, documents, resumes or the import pipeline, and the pipeline does not know
which engine it has. That boundary is the point of the file:
[ADR-0008](../../../../../../docs/adr/0008-ocr-behind-an-engine-interface.md)
chose Tesseract first knowing the choice would be revisited, and a second engine
behind this protocol is a small class rather than a change to the pipeline.

It also keeps the unit suite honest. Recognition needs a system binary that is
not installed on every developer's machine, so every test above this line
supplies its own engine and none of them needs Tesseract at all.

**Bitmaps rather than a PDF**, because rasterising is a separate concern with
its own failure modes, and because the day this platform accepts a photograph of
a resume there will be no PDF in the picture.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OcrPage:
    """One page, as read."""

    text: str

    confidence: float
    """Mean confidence over the words the engine was willing to score, 0 to 100.

    Not a probability and not comparable between engines. It is useful for one
    thing: telling a clean read from a guess, so a low figure can be surfaced to
    the person reviewing the result rather than hidden behind text that looks
    just as confident either way.
    """


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Every page of one document."""

    pages: tuple[OcrPage, ...]

    @property
    def text(self) -> str:
        """The pages joined, in order, the way `_extract_pdf` joins them."""
        return "\n\n".join(page.text for page in self.pages)

    @property
    def confidence(self) -> float:
        """One figure for the document, weighted by how much text each page held.

        A plain mean would let a near-empty cover page — three words, read
        perfectly — count as much as the page carrying the whole work history.
        Weighting by length asks the question a reader actually has: how much of
        what I am about to read was guessed at.
        """
        weighted = sum(page.confidence * len(page.text) for page in self.pages)
        total = sum(len(page.text) for page in self.pages)
        return weighted / total if total else 0.0


class OcrEngine(Protocol):
    """Turns page bitmaps into text."""

    name: str
    """Recorded with the result, so a stored extraction says what read it."""

    def read(self, pages: Iterable[bytes], *, languages: str) -> OcrResult:
        """Read every page.

        `pages` is PNG bytes and is deliberately an iterable rather than a
        sequence: an A4 page at 300 DPI is around 8 MB uncompressed, and a
        twenty-page document held all at once is memory a worker does not need
        to spend. Implementations should consume it lazily.

        `languages` is engine-specific — Tesseract wants `eng+heb`. Passing it
        through rather than modelling it keeps the protocol from having opinions
        about scripts it has never seen.
        """
        ...
