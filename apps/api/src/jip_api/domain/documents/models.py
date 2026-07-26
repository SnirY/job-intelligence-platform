"""Source documents uploaded by the user.

The row holds *metadata and extracted text*; the file itself lives in object
storage under ``storage_key`` (``docs/04-system-architecture.md``).

``GOAL.md`` requires that a failure never destroys user work, which is why the
document and its raw text survive independently of whether parsing succeeded.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import BigInteger, CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import TimestampMixin, UserOwnedMixin, new_uuid_column
from jip_api.infrastructure.db.base import Base


class DocumentKind(enum.StrEnum):
    """What the user said this document is."""

    RESUME = "RESUME"


class DocumentStatus(enum.StrEnum):
    """How far the document has progressed through the import pipeline.

    Mirrors the steps in ``docs/09-mvp-roadmap.md``. Kept on the document rather
    than only on the processing job so the state survives after the job record
    is trimmed.
    """

    UPLOADED = "UPLOADED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class SourceDocument(TimestampMixin, UserOwnedMixin, Base):
    """An uploaded file and whatever text has been pulled out of it."""

    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = new_uuid_column()

    kind: Mapped[DocumentKind] = mapped_column(String(30), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(String(20), nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    """The name the browser sent, stored for display only.

    Never used to build a storage key or a filesystem path: an uploaded
    filename is attacker-controlled and is the classic path-traversal input
    (``docs/11-engineering-standards.md``: never trust uploaded filenames).
    """

    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    """Hash of the uploaded bytes.

    Lets a re-upload of the identical file be recognised instead of re-running a
    paid model call over content already parsed.
    """

    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    """Where the file lives in object storage. Generated, never user-supplied."""

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Raw text pulled from the file.

    ``GOAL.md`` requires preserving raw inputs: this is kept verbatim so a later
    parser version can re-read it without asking the user to upload again.
    """

    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why extraction failed, when it did. Surfaced so a failure is actionable."""

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SourceDocument id={self.id} status={self.status}>"
