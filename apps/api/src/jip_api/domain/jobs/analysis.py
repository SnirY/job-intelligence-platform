"""What a job posting asks for, as structure rather than prose.

Three tables and one rule that shapes all of them: **this is interpretation, and
it lives apart from the job it describes**. ``docs/03-domain-model.md`` keeps
``JobAnalysis`` versioned and separate from ``Job`` precisely so an inference can
never overwrite what the posting said or what the user typed. Reanalysis adds a
version; nothing here is updated in place.

The split between the three tables follows the split between fact and judgement:

- :class:`JobRequirement` and :class:`JobResponsibility` are claims *about the
  text*. Each one carries the span it came from, and validation checks that span
  against the description.
- :class:`JobAnalysis` carries the judgements — role family, seniority — with
  their reasoning and confidence, so the UI can label them as interpretation
  rather than presenting them alongside facts.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.career.models import Seniority
from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
from jip_api.infrastructure.db.base import Base


class RequirementType(enum.StrEnum):
    """The nine types from ``docs/03-domain-model.md``.

    Closed rather than free text because Phase 6 weights categories
    differently: a missing work authorization is a blocker, a missing soft
    skill is not, and that distinction cannot be made against arbitrary
    strings.
    """

    TECHNICAL_SKILL = "TECHNICAL_SKILL"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    LANGUAGE = "LANGUAGE"
    DOMAIN_KNOWLEDGE = "DOMAIN_KNOWLEDGE"
    SOFT_SKILL = "SOFT_SKILL"
    LOCATION = "LOCATION"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    OTHER = "OTHER"


class RequirementImportance(enum.StrEnum):
    """How much the posting insists.

    ``docs/05-ai-and-matching.md``: importance must preserve source meaning, and
    "nice to have" must not become "required". That sentence is the reason this
    is a separate field rather than a boolean — collapsing five degrees into
    required/not-required is exactly how a preference becomes a demand.
    """

    CORE = "CORE"
    """Named as essential, or the role makes no sense without it."""

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    OPTIONAL = "OPTIONAL"

    UNKNOWN = "UNKNOWN"
    """The posting lists it without saying how much it matters.

    An honest answer, and a better one than guessing REQUIRED — Phase 6 can
    weight an unknown cautiously, but cannot un-invent a demand.
    """

    @property
    def is_mandatory(self) -> bool:
        """Whether failing this would count against the candidate."""
        return self in {RequirementImportance.CORE, RequirementImportance.REQUIRED}


class RequirementExplicitness(enum.StrEnum):
    """Whether the posting said it or the reader inferred it.

    Kept because an implied requirement is weaker evidence than a stated one,
    and a user reading the analysis deserves to know which they are looking at.
    """

    EXPLICIT = "EXPLICIT"
    IMPLIED = "IMPLIED"


class AnalyzedSeniority(enum.StrEnum):
    """Seniority a posting implies. The set named in ``docs/05-ai-and-matching.md``.

    Deliberately not :class:`~jip_api.domain.career.models.Seniority`, which is
    what a *person* aims for. The two vocabularies answer different questions
    and only mostly overlap: a posting can be honestly UNKNOWN, and it can say
    "entry level" without meaning JUNIOR, while nobody sets UNKNOWN as a career
    target. :func:`to_target_seniority` is the documented bridge, so Phase 6
    does not have to invent one.
    """

    INTERN = "INTERN"
    ENTRY_LEVEL = "ENTRY_LEVEL"
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    STAFF_PLUS = "STAFF_PLUS"
    UNKNOWN = "UNKNOWN"


def to_target_seniority(level: AnalyzedSeniority) -> Seniority | None:
    """Map an assessed level onto the career vocabulary.

    ``None`` where no honest mapping exists. STAFF_PLUS covers staff, principal,
    and beyond, so it lands on STAFF as the floor of that band rather than
    picking one arbitrarily; UNKNOWN maps to nothing at all, because a
    comparison against a level nobody established is worse than no comparison.
    """
    return {
        AnalyzedSeniority.INTERN: Seniority.INTERN,
        AnalyzedSeniority.ENTRY_LEVEL: Seniority.JUNIOR,
        AnalyzedSeniority.JUNIOR: Seniority.JUNIOR,
        AnalyzedSeniority.MID: Seniority.MID,
        AnalyzedSeniority.SENIOR: Seniority.SENIOR,
        AnalyzedSeniority.STAFF_PLUS: Seniority.STAFF,
    }.get(level)


class RoleFamily(enum.StrEnum):
    """The initial families from ``docs/05-ai-and-matching.md``, plus an escape.

    OTHER exists so a genuine mismatch is visible rather than being forced into
    the nearest listed family. The document calls this list *initial*; adding a
    member later is a migration and a prompt version, which is the right amount
    of friction for a vocabulary Phase 6 matches against.
    """

    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    FULL_STACK = "FULL_STACK"
    SOFTWARE = "SOFTWARE"
    AI_ML = "AI_ML"
    DATA_ENGINEERING = "DATA_ENGINEERING"
    COMPUTER_VISION = "COMPUTER_VISION"
    DEVOPS = "DEVOPS"
    CYBERSECURITY = "CYBERSECURITY"
    OTHER = "OTHER"


class JobAnalysis(TimestampMixin, UserOwnedMixin, Base):
    """One versioned interpretation of one job.

    Carries its own provenance — provider, model, both prompt versions, input
    hash — because ``docs/05-ai-and-matching.md`` requires prompts to be
    versioned and an analysis produced by ``job_parser_v1`` must keep meaning
    what it meant after v2 exists.
    """

    __tablename__ = "job_analyses"

    id: Mapped[uuid.UUID] = new_uuid_column()

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    """1, 2, 3… per job. Reanalysis adds; it never replaces."""

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    """A few sentences on what the role is. Interpretation, shown as such."""

    role_family: Mapped[RoleFamily | None] = mapped_column(
        StrEnumType(RoleFamily, 30), nullable=True
    )
    secondary_role_family: Mapped[RoleFamily | None] = mapped_column(
        StrEnumType(RoleFamily, 30), nullable=True
    )
    """Set only where it genuinely applies — a backend role that is half data
    engineering. Forcing a second family onto every job would make the field
    noise."""

    role_family_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    role_family_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    seniority: Mapped[AnalyzedSeniority] = mapped_column(
        StrEnumType(AnalyzedSeniority, 20),
        nullable=False,
        server_default=AnalyzedSeniority.UNKNOWN.value,
    )
    seniority_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    seniority_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why, in the posting's own terms.

    Required in practice for anything other than UNKNOWN — see the validation
    layer. A level with no reasoning is an assertion, and this phase's whole
    point is that judgements arrive with their grounds attached.
    """

    domain: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """Industry or problem domain — "fintech", "medical imaging". Free text:
    the space is open, and a closed list would force wrong answers."""

    years_experience_min: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    years_experience_max: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """What the posting asks for overall, when it says. Null when it does not —
    ``docs/05-ai-and-matching.md`` warns against treating years as binary, and
    inventing a floor of zero would do exactly that."""

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    parse_prompt_version: Mapped[str] = mapped_column(String(60), nullable=False)
    analysis_prompt_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """SHA-256 of the description this analysis read.

    What makes staleness a fact rather than a guess: if the job's current hash
    differs, the description has been edited since, and the UI can say so
    instead of presenting an analysis of text that no longer exists.
    """

    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    """The raw parse output, kept whole.

    The rows below are the queryable projection; this is the record of what the
    model actually returned, which is the only thing that can be re-read when a
    later version of the projection wants a field this one dropped.
    """

    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """What validation had to correct or could not verify. Shown to the user."""

    analyzed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_job_analyses_job_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "role_family_confidence IS NULL OR "
            "(role_family_confidence >= 0 AND role_family_confidence <= 100)",
            name="role_family_confidence_range",
        ),
        CheckConstraint(
            "seniority_confidence IS NULL OR "
            "(seniority_confidence >= 0 AND seniority_confidence <= 100)",
            name="seniority_confidence_range",
        ),
        CheckConstraint(
            "years_experience_min IS NULL OR "
            "(years_experience_min >= 0 AND years_experience_min <= 80)",
            name="years_min_range",
        ),
        CheckConstraint(
            "years_experience_max IS NULL OR "
            "(years_experience_max >= 0 AND years_experience_max <= 80)",
            name="years_max_range",
        ),
        # The common read is "the newest analysis for this job".
        Index("ix_job_analyses_job_version", "job_id", "version"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobAnalysis job={self.job_id} v{self.version}>"


class JobRequirement(TimestampMixin, UserOwnedMixin, Base):
    """One thing the posting asks for.

    ``docs/05-ai-and-matching.md`` decomposes a long sentence into several
    requirements — "2+ years of backend experience using Java, Spring Boot or
    similar" becomes an experience requirement and two technical ones — and
    insists the original text is preserved on each. That is what
    ``source_text`` is for, and why it is not nullable in spirit even though a
    model can omit it: the validation layer drops an item whose quoted span is
    not in the description.
    """

    __tablename__ = "job_requirements"

    id: Mapped[uuid.UUID] = new_uuid_column()

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Denormalized from the analysis.

    ``GET /jobs/{id}/requirements`` reads by job, and going through the analysis
    every time would make the common query a join for no benefit. The pair is
    written together and neither is ever updated.
    """

    requirement_type: Mapped[RequirementType] = mapped_column(
        StrEnumType(RequirementType, 30), nullable=False
    )
    importance: Mapped[RequirementImportance] = mapped_column(
        StrEnumType(RequirementImportance, 20), nullable=False
    )
    explicitness: Mapped[RequirementExplicitness] = mapped_column(
        StrEnumType(RequirementExplicitness, 20),
        nullable=False,
        server_default=RequirementExplicitness.EXPLICIT.value,
    )

    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    """The posting's own words. Never rewritten, never summarised."""

    normalized_text: Mapped[str] = mapped_column(String(300), nullable=False)
    """What it means, in a short canonical phrase — "3+ years backend
    engineering". What a human reads in the grouped list; the source text is
    what they check it against."""

    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")
    source_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    """Position in the posting. Preserved because order carries meaning: the
    first three bullets of a requirements list are not the last three."""

    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The canonical skill this resolves to, when one exists.

    Null is a normal outcome, not a failure: see
    ``jip_api.application.jobs.requirement_skills`` for why an unrecognised
    technology is recorded here and not added to the shared catalogue.
    """

    skill_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """The technology as the posting named it, before resolution. Kept whether
    or not it resolved — it is the input to any later attempt."""

    years_min: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """Years attached to this specific requirement, when it states one."""

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_range"),
        CheckConstraint("length(trim(source_text)) > 0", name="source_text_not_blank"),
        CheckConstraint("length(trim(normalized_text)) > 0", name="normalized_text_not_blank"),
        CheckConstraint(
            "years_min IS NULL OR (years_min >= 0 AND years_min <= 80)", name="years_range"
        ),
        Index("ix_job_requirements_analysis_order", "analysis_id", "source_order"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobRequirement {self.requirement_type} {self.importance}>"


class JobResponsibility(TimestampMixin, UserOwnedMixin, Base):
    """One thing the role does.

    Separate from requirements because they answer different questions — what
    you would do versus what you must already have — and Phase 6 matches
    against requirements only. Merging them would mean either matching against
    responsibilities (which is not what the scoring model does) or carrying a
    type flag that exists purely to exclude half the rows.
    """

    __tablename__ = "job_responsibilities"

    id: Mapped[uuid.UUID] = new_uuid_column()

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")
    source_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_range"),
        CheckConstraint("length(trim(text)) > 0", name="text_not_blank"),
        Index("ix_job_responsibilities_analysis_order", "analysis_id", "source_order"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobResponsibility {self.text[:40]!r}>"
