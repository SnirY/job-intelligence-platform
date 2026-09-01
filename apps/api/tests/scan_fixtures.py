"""Making a rendered page look like something that went through a scanner.

A PDF rasterised by PDFium is perfect: straight, evenly lit, no grain. That is
not what arrives. A page that has been through a flatbed sits a degree or two
off square, a phone photograph is soft, and both carry sensor noise.

Perfection is also why the first version of the accuracy suite measured nothing:
the fixture read at zero character error from 300 DPI all the way down to 100,
so every comparison between conditions was `0.0 > 0.0`. **A benchmark on which
everything scores perfectly has no dynamic range**, and a test built on one
passes for reasons unrelated to what it claims.

Deterministic on purpose. Rotation and blur are exact operations; nothing here
draws a random number, so a measurement taken today is comparable with one taken
next year.
"""

from __future__ import annotations

from io import BytesIO


def degrade(png: bytes, *, skew_degrees: float = 0.0, blur_radius: float = 0.0) -> bytes:
    """Return the page as a worse scan of itself.

    `skew_degrees` rotates, filling the corners with paper white rather than
    black, because a scanner lid is white and a black wedge would be a feature
    the segmenter tries to read.

    `blur_radius` softens. Together they stand in for the two failures that
    actually degrade a resume scan: a page put in crooked, and a lens or a
    resolution that could not hold the strokes apart.
    """
    from PIL import Image, ImageFilter
    from PIL.Image import Resampling

    with Image.open(BytesIO(png)) as image:
        out = image.convert("L")

        if skew_degrees:
            out = out.rotate(
                skew_degrees,
                resample=Resampling.BICUBIC,
                expand=True,
                fillcolor=255,
            )

        if blur_radius:
            out = out.filter(ImageFilter.GaussianBlur(blur_radius))

        buffer = BytesIO()
        out.save(buffer, format="PNG")
        return buffer.getvalue()
