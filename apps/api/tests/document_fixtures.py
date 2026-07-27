"""Building real PDF and DOCX bytes in memory.

Generated rather than committed as binaries. A checked-in fixture file is
opaque in review, and a test that builds the document states exactly which
structural feature it is exercising — a table, a tab stop, a missing text
layer.

These are genuinely valid files: ``pypdf`` and the DOCX reader parse them the
same way they parse anything a user uploads.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels"
    ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
"""


def docx_bytes(paragraphs: list[str], *, table_rows: list[list[str]] | None = None) -> bytes:
    """A minimal but real DOCX.

    ``table_rows`` produces a genuine ``w:tbl``. Two-column resume templates are
    tables, so a reader that only walks paragraphs loses half the document —
    which is the regression this exists to catch.
    """
    body: list[str] = [
        f"<w:p><w:r><w:t xml:space='preserve'>{p}</w:t></w:r></w:p>" for p in paragraphs
    ]

    if table_rows:
        cells = "".join(
            "<w:tr>"
            + "".join(
                f"<w:tc><w:p><w:r><w:t xml:space='preserve'>{cell}</w:t></w:r></w:p></w:tc>"
                for cell in row
            )
            + "</w:tr>"
            for row in table_rows
        )
        body.append(f"<w:tbl>{cells}</w:tbl>")

    document = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<w:document xmlns:w='{_W}'><w:body>{''.join(body)}</w:body></w:document>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def docx_with_tabs(text_pairs: list[tuple[str, str]]) -> bytes:
    """A DOCX using tab stops, the classic "Company .... 2020-2023" layout."""
    paragraphs = "".join(
        f"<w:p><w:r><w:t xml:space='preserve'>{left}</w:t><w:tab/>"
        f"<w:t xml:space='preserve'>{right}</w:t></w:r></w:p>"
        for left, right in text_pairs
    )
    document = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<w:document xmlns:w='{_W}'><w:body>{paragraphs}</w:body></w:document>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def pdf_bytes(lines: list[str]) -> bytes:
    """A single-page PDF with an uncompressed text stream.

    Hand-assembled so the offsets in the cross-reference table are exact, which
    is what makes it a file ``pypdf`` will actually read rather than a plausible
    imitation.
    """
    escaped = [line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)") for line in lines]
    text_ops = "\n".join(f"({line}) Tj T*" for line in escaped)
    stream = f"BT /F1 12 Tf 14 TL 50 750 Td\n{text_ops}\nET"

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("latin-1")

    return bytes(out)


def pdf_without_text_layer() -> bytes:
    """A structurally valid PDF whose page carries no text.

    What a scan or a photographed printout looks like to an extractor: the file
    opens, the page exists, and there is nothing to read.
    """
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        "<< /Length 0 >>\nstream\n\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("latin-1")

    return bytes(out)


RESUME_LINES = [
    "MAYA OKONKWO",
    "Backend Engineer, Lisbon",
    "",
    "EXPERIENCE",
    "Junior Backend Engineer, Verdant Logistics",
    "March 2023 - Present",
    "Built REST endpoints in FastAPI for the shipment tracking service.",
    "",
    "EDUCATION",
    "BSc Computer Science, University of Lisbon, 2019 - 2022",
    "",
    "SKILLS",
    "Python, FastAPI, PostgreSQL, Docker",
]
"""A short but realistic resume, long enough to clear the minimum-text check."""
