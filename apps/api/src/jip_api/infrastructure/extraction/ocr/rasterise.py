"""Turning PDF pages into pictures, so an engine has something to read.

A PDF is a drawing format. One produced by a word processor carries glyphs *and*
their Unicode code points, and `pypdf` reads those directly. One produced by a
scanner carries a single image per page and no code points at all, so there is
nothing to read until the page is drawn.

`pypdfium2` binds PDFium, the engine Chrome renders PDFs with. It ships wheels,
so it costs no system package — which matters because Tesseract already costs
one, and two would double the surface of the Dockerfile change.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from io import BytesIO

logger = logging.getLogger(__name__)

PDF_UNITS_PER_INCH = 72
"""Fixed by the PDF specification.

PDF user space is 72 units to the inch, so a render scale of 1.0 produces 72
DPI. Every other figure here is that ratio: 300 DPI is a scale of 300/72.
"""


def rasterise(data: bytes, *, dpi: int, max_pages: int) -> Iterator[bytes]:
    """Yield one PNG per page, greyscale, at `dpi`.

    **A generator on purpose.** An A4 page at 300 DPI is 2479 by 3508 pixels;
    a twenty-page document rendered up front is over a hundred megabytes held in
    a worker process for no reason. Rendered, read, released.

    **Greyscale on purpose too.** Recognition does not use colour, and dropping
    it is a third of the bytes for nothing lost. Anything that later wants
    colour — a layout model, a stamp detector — should ask for it rather than
    have every caller pay in advance.

    `max_pages` is a bound rather than a preference: recognition costs seconds
    per page, and a resume that runs past the cap is either not a resume or not
    one whose twentieth page decides anything.
    """
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        count = len(document)
        if count > max_pages:
            logger.info(
                "Rasterising only the first pages of a long document",
                extra={"pages": count, "limit": max_pages},
            )

        for index in range(min(count, max_pages)):
            image = document[index].render(scale=dpi / PDF_UNITS_PER_INCH).to_pil()
            buffer = BytesIO()
            image.convert("L").save(buffer, format="PNG")
            yield buffer.getvalue()
    finally:
        document.close()
