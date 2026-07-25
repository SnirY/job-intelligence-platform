"""Validating and storing an uploaded document.

``docs/10-api-contracts.md`` requires uploads to validate size, MIME type,
extension, and content handling. All four are checked here, and the content
check is the one that matters: the declared type and the extension are both
supplied by the caller, so neither is evidence of anything.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jip_api.application.errors import ApplicationError
from jip_api.domain.documents.models import DocumentKind, DocumentStatus, SourceDocument
from jip_api.infrastructure.storage.base import ObjectStorage

logger = logging.getLogger(__name__)

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

ALLOWED_UPLOAD_TYPES: dict[str, set[str]] = {
    PDF: {".pdf"},
    DOCX: {".docx"},
}

# Leading bytes that actually identify the format. A PDF starts with "%PDF-";
# DOCX is a ZIP container, so it starts with the ZIP local file header.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    PDF: (b"%PDF-",),
    DOCX: (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
}


class UploadRejected(ApplicationError):
    """The uploaded file is not something we accept."""


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """An upload as received from the transport layer."""

    filename: str
    content_type: str
    data: bytes


def validate_upload(upload: UploadedFile, *, max_bytes: int) -> str:
    """Check the upload and return the content type to record.

    Raises :class:`UploadRejected` with a message safe to show the user.
    """
    if not upload.data:
        raise UploadRejected("The file is empty.")

    if len(upload.data) > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise UploadRejected(f"The file is larger than the {limit_mb:.0f} MB limit.")

    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared not in ALLOWED_UPLOAD_TYPES:
        raise UploadRejected("Only PDF and DOCX resumes are supported.")

    suffix = _extension(upload.filename)
    if suffix not in ALLOWED_UPLOAD_TYPES[declared]:
        raise UploadRejected("The file extension does not match its type.")

    # The decisive check. A caller controls both the declared type and the
    # extension, so agreement between them proves nothing; the bytes do.
    if not upload.data.startswith(_MAGIC[declared]):
        raise UploadRejected("The file contents do not match a PDF or DOCX document.")

    return declared


def _extension(filename: str) -> str:
    """Lowercase extension of ``filename``, or an empty string.

    Deliberately does not use the filename for anything else — it is
    attacker-controlled and never becomes part of a path or storage key.
    """
    _, _, tail = filename.rpartition(".")
    return f".{tail.lower()}" if tail and tail != filename else ""


def build_storage_key(user_id: uuid.UUID, document_id: uuid.UUID, content_type: str) -> str:
    """Generate the object key.

    Composed entirely from values we control. Using any part of the uploaded
    filename here is how path traversal and key collisions get in.
    """
    suffix = next(iter(ALLOWED_UPLOAD_TYPES[content_type]))
    return f"users/{user_id}/documents/{document_id}{suffix}"


def store_uploaded_document(
    session: Session,
    storage: ObjectStorage,
    *,
    user_id: uuid.UUID,
    upload: UploadedFile,
    max_bytes: int,
    kind: DocumentKind = DocumentKind.RESUME,
) -> SourceDocument:
    """Validate, store the bytes, and record the document.

    The object is written before the row is committed by the caller. If the
    commit then fails the object is orphaned, which is the safe direction: a
    stray file costs storage, whereas a row pointing at a missing object would
    be a document the user can see and never open.
    """
    content_type = validate_upload(upload, max_bytes=max_bytes)

    document_id = uuid.uuid4()
    storage_key = build_storage_key(user_id, document_id, content_type)

    storage.upload(storage_key, upload.data, content_type=content_type)

    document = SourceDocument(
        id=document_id,
        user_id=user_id,
        kind=kind,
        status=DocumentStatus.UPLOADED,
        original_filename=upload.filename[:255],
        content_type=content_type,
        size_bytes=len(upload.data),
        content_sha256=hashlib.sha256(upload.data).hexdigest(),
        storage_key=storage_key,
    )
    session.add(document)
    session.flush()

    logger.info(
        "Stored uploaded document",
        extra={"document_id": str(document_id), "size_bytes": len(upload.data)},
    )
    return document
