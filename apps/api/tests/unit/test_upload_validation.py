"""Upload validation.

``docs/10-api-contracts.md`` requires size, MIME type, extension, and content
checks. The content check carries the weight: a caller controls both the
declared type and the extension, so their agreeing proves nothing.
"""

from __future__ import annotations

import pytest

from jip_api.application.documents.upload import (
    DOCX,
    PDF,
    UploadedFile,
    build_storage_key,
    validate_upload,
)
from jip_api.application.errors import ApplicationError

MAX = 1024 * 1024

PDF_BYTES = b"%PDF-1.7\n" + b"x" * 100
DOCX_BYTES = b"PK\x03\x04" + b"x" * 100


def upload(**overrides: object) -> UploadedFile:
    fields: dict[str, object] = {
        "filename": "resume.pdf",
        "content_type": PDF,
        "data": PDF_BYTES,
    }
    fields.update(overrides)
    return UploadedFile(**fields)  # type: ignore[arg-type]


def test_accepts_a_real_pdf() -> None:
    assert validate_upload(upload(), max_bytes=MAX) == PDF


def test_accepts_a_real_docx() -> None:
    result = validate_upload(
        upload(filename="resume.docx", content_type=DOCX, data=DOCX_BYTES), max_bytes=MAX
    )

    assert result == DOCX


def test_tolerates_a_charset_parameter() -> None:
    """Browsers may append parameters to the content type."""
    assert validate_upload(upload(content_type=f"{PDF}; charset=binary"), max_bytes=MAX) == PDF


def test_rejects_an_empty_file() -> None:
    with pytest.raises(ApplicationError):
        validate_upload(upload(data=b""), max_bytes=MAX)


def test_rejects_a_file_over_the_limit() -> None:
    with pytest.raises(ApplicationError, match="larger than"):
        validate_upload(upload(data=PDF_BYTES + b"y" * MAX), max_bytes=MAX)


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "image/png", "application/zip", "application/x-msdownload", ""],
)
def test_rejects_unsupported_types(content_type: str) -> None:
    with pytest.raises(ApplicationError):
        validate_upload(upload(content_type=content_type), max_bytes=MAX)


def test_rejects_a_mismatched_extension() -> None:
    with pytest.raises(ApplicationError, match="extension"):
        validate_upload(upload(filename="resume.exe"), max_bytes=MAX)


def test_rejects_a_pdf_declaration_over_other_content() -> None:
    """The decisive check.

    An executable renamed to .pdf and declared as application/pdf passes both
    the extension and MIME checks; only the magic bytes catch it.
    """
    with pytest.raises(ApplicationError, match="contents"):
        validate_upload(upload(data=b"MZ\x90\x00" + b"x" * 100), max_bytes=MAX)


def test_rejects_a_docx_declaration_over_non_zip_content() -> None:
    with pytest.raises(ApplicationError, match="contents"):
        validate_upload(
            upload(filename="resume.docx", content_type=DOCX, data=b"not a zip"), max_bytes=MAX
        )


def test_rejects_html_disguised_as_pdf() -> None:
    with pytest.raises(ApplicationError):
        validate_upload(upload(data=b"<html><script>alert(1)</script></html>"), max_bytes=MAX)


# --- storage keys -------------------------------------------------------------


def test_storage_key_ignores_the_uploaded_filename() -> None:
    """A filename is attacker-controlled and never reaches a path."""
    import uuid

    user_id = uuid.uuid4()
    document_id = uuid.uuid4()

    key = build_storage_key(user_id, document_id, PDF)

    assert key == f"users/{user_id}/documents/{document_id}.pdf"


@pytest.mark.parametrize(
    "hostile",
    ["../../etc/passwd", "..\\..\\windows\\system32", "a/../../b", "%2e%2e%2fpasswd"],
)
def test_traversal_filenames_cannot_affect_the_key(hostile: str) -> None:
    import uuid

    key = build_storage_key(uuid.uuid4(), uuid.uuid4(), PDF)

    assert hostile not in key
    assert ".." not in key
