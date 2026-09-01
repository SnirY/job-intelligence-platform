"""Source documents uploaded by the user.

The row holds *metadata and extracted text*; the file itself lives in object
storage under ``storage_key`` (``docs/04-system-architecture.md``).

``GOAL.md`` requires that a failure never destroys user work, which is why the
document and its raw text survive independently of whether parsing succeeded.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
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


class TextSource(enum.StrEnum):
    """How the text on a document was obtained.

    A text layer is what the file itself declares its glyphs to be: exact, by
    construction. OCR is a reading of a picture of a page, and a good reading is
    still a reading. The two deserve different amounts of trust, and a person
    confirming what a model found in them has a right to know which they got.

    Domain rather than infrastructure. `extract_text` produces it, but this is
    the layer that stores it, and an ORM column typed by an extractor's private
    enum would put the schema at the mercy of a module that has no idea it is
    persisted.
    """

    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"


class SourceDocument(TimestampMixin, UserOwnedMixin, Base):
    """An uploaded file and whatever text has been pulled out of it."""

    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = new_uuid_column()

    kind: Mapped[DocumentKind] = mapped_column(StrEnumType(DocumentKind, 30), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(StrEnumType(DocumentStatus, 20), nullable=False)

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

    text_source: Mapped[TextSource | None] = mapped_column(
        StrEnumType(TextSource, 20), nullable=True
    )
    """Whether `extracted_text` came from the file or from reading a picture.

    Nullable, and null means *not extracted yet* rather than *unknown*. Every
    row written before OCR existed came from a text layer, but backfilling them
    to `TEXT_LAYER` would invent a fact about documents nobody checked, which is
    the same mistake as recording an absent date as an unknown one.
    """

    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    """Mean confidence over the words the engine scored, 0 to 100.

    Null when the text came from a text layer, because a text layer has no
    confidence rather than perfect confidence. Storing 100 would make the two
    indistinguishable to every query that comes later.

    **Diagnostic, and not shown to anybody.** DEV-084: the figure rises as the
    read gets worse, because it averages the words the engine emitted and the
    ones it abandoned never enter it. Kept because it is real data about a real
    run and useful when investigating one; not displayed, because a reader would
    take it for a quality score and it is not one.
    """

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
        # A figure outside 0-100 is not a poor reading, it is a bug in whatever
        # wrote it: a unit mix-up, or a fraction where a percentage was meant.
        CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 100)",
            name="ocr_confidence_range",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SourceDocument id={self.id} status={self.status}>"


class DocumentExtraction(TimestampMixin, UserOwnedMixin, Base):
    """Structured output of one parse of one document.

    Versioned rather than overwritten. ``docs/03-domain-model.md`` keeps AI
    interpretation separate from verified facts and forbids overwriting
    history, so re-parsing a document with a newer prompt adds version 2 and
    leaves version 1 exactly as the user reviewed it.

    Nothing here is career data. It becomes career data only when the user
    accepts an item, and only through the career application services.
    """

    __tablename__ = "document_extractions"

    id: Mapped[uuid.UUID] = new_uuid_column()

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("source_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ai_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The traced call that produced this. Nullable so the extraction survives
    a trace being cleared out, which is operational data with its own lifetime."""

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(60), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """The validated ``ResumeParseResult`` as JSON.

    JSONB per ``docs/03-domain-model.md``: this is raw AI output, read whole and
    never filtered on. The reviewable candidates are split into rows below,
    because those *are* queried, decided on, and linked to career records.
    """

    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """What business validation dropped or could not trust, kept so the user is
    told rather than left wondering why a line from their resume is missing."""

    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_document_id", "version", name="uq_document_extractions_version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DocumentExtraction id={self.id} version={self.version}>"


class CandidateType(enum.StrEnum):
    """What a review candidate would become if accepted.

    One member per approve destination. A type with no destination would be a
    candidate the user can accept and then never find, which is worse than not
    extracting it.
    """

    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    EXPERIENCE_ACHIEVEMENT = "EXPERIENCE_ACHIEVEMENT"
    PROJECT = "PROJECT"
    PROJECT_SKILL = "PROJECT_SKILL"
    EDUCATION = "EDUCATION"


class CandidateDecision(enum.StrEnum):
    """What the user did with a candidate.

    ``PENDING`` until they decide. ``EDITED`` is kept distinct from ``ACCEPTED``
    so the record of what the model proposed versus what the user actually
    meant is not lost — ``docs/06-resume-engine.md`` wants rejected and
    corrected inferences remembered, not silently merged.
    """

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    IGNORED = "IGNORED"


class DocumentExtractionItem(TimestampMixin, UserOwnedMixin, Base):
    """One reviewable fact the parser proposed.

    A row rather than a slot in the JSON payload, because each one carries a
    decision, and — once accepted — the identity of the career record it
    produced. That link is what makes confirming twice a no-op instead of a
    duplicate.
    """

    __tablename__ = "document_extraction_items"

    id: Mapped[uuid.UUID] = new_uuid_column()

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("document_extractions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    candidate_type: Mapped[CandidateType] = mapped_column(
        StrEnumType(CandidateType, 30), nullable=False
    )

    parent_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("document_extraction_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """An achievement's role, or a technology's project.

    A child cannot be applied unless its parent was: an achievement with no
    experience has nowhere to go, and inventing a role to hang it on would be
    fabricating career data.
    """

    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """What the parser proposed, exactly as validated."""

    edited_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """What the user changed it to, when they did. The original stays intact."""

    confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """0-100, as reported by the parser. Null when it did not say.

    Presented as uncertainty, never as accuracy: a confident model is still an
    untrusted one (``docs/05-ai-and-matching.md``)."""

    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The line of the resume this came from, when the parser identified one.
    Provenance the user can check the proposal against."""

    decision: Mapped[CandidateDecision] = mapped_column(
        StrEnumType(CandidateDecision, 20), nullable=False, index=True
    )

    target_entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    """The career record this became. Set once; re-confirming reuses it."""

    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 100)",
            name="confidence_range",
        ),
        CheckConstraint("display_order >= 0", name="display_order_not_negative"),
    )

    @property
    def effective_payload(self) -> dict[str, Any]:
        """What an approval should actually write."""
        return self.edited_payload if self.edited_payload is not None else self.payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DocumentExtractionItem id={self.id} type={self.candidate_type}>"
