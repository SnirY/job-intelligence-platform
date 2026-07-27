"""Schema and business validation of parsed resume output.

The layer between "the model said something" and "we are willing to show this
to the user as a fact from their document". Most of what is under test here is
refusal: dropping a guess, stripping a false quote, flagging an invented number.
"""

from __future__ import annotations

from typing import Any

import pytest

from jip_api.application.resumes.schema import (
    DatePrecision,
    PartialDate,
    ResumeParseResult,
    resume_parse_json_schema,
)
from jip_api.application.resumes.validation import (
    MINIMUM_CONFIDENCE,
    UNVERIFIED_CONFIDENCE_CAP,
    validate_parse_result,
)
from jip_api.domain.documents.models import CandidateType

DOCUMENT = (
    "MAYA OKONKWO\n"
    "Backend Engineer\n\n"
    "EXPERIENCE\n"
    "Junior Backend Engineer, Verdant Logistics\n"
    "March 2023 - Present\n"
    "Migrated 14 legacy Flask endpoints to FastAPI.\n"
    "Took pricing test coverage from 31% to 78%.\n\n"
    "PROJECTS\n"
    "ledgerline - a bookkeeping library. Python, SQLAlchemy.\n\n"
    "EDUCATION\n"
    "BSc Computer Science, University of Lisbon, 2019 - 2022\n\n"
    "SKILLS\n"
    "Python, FastAPI, PostgreSQL\n"
)


def validate(payload: dict[str, Any], document: str = DOCUMENT) -> Any:
    return validate_parse_result(ResumeParseResult.model_validate(payload), document_text=document)


def by_type(result: Any, candidate_type: CandidateType) -> list[Any]:
    return [c for c in result.candidates if c.candidate_type is candidate_type]


# --- partial dates ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "precision", "iso"),
    [
        ("2021", DatePrecision.YEAR, "2021-01-01"),
        ("2021-03", DatePrecision.MONTH, "2021-03-01"),
        ("2021-03-15", DatePrecision.DAY, "2021-03-15"),
    ],
)
def test_dates_keep_the_precision_the_resume_gave(
    raw: str, precision: DatePrecision, iso: str
) -> None:
    """Widening fills with the earliest value and records that it happened.

    A year-only date stored as 1 January is otherwise indistinguishable from a
    real 1 January, and the reviewer needs to know which they are approving.
    """
    parsed = PartialDate.parse(raw)

    assert parsed is not None
    assert parsed.precision is precision
    assert parsed.to_date().isoformat() == iso


@pytest.mark.parametrize("raw", ["sometime in 2019", "March 2021", "", "20211", "2021-13", None])
def test_unreadable_dates_become_none(raw: str | None) -> None:
    """One bad date costs that date, not the whole extraction."""
    assert PartialDate.parse(raw) is None


# --- confidence ---------------------------------------------------------------


def test_low_confidence_items_are_dropped() -> None:
    """The prompt asks for the same floor; enforcing it here means a model that
    ignores the instruction cannot fill the review screen with guesses."""
    result = validate(
        {
            "skills": [
                {"name": "Python", "confidence": MINIMUM_CONFIDENCE},
                {"name": "Rust", "confidence": MINIMUM_CONFIDENCE - 1},
            ]
        }
    )

    assert {c.payload["name"] for c in by_type(result, CandidateType.SKILL)} == {"Python"}


# --- fabrication guards -------------------------------------------------------


def test_a_quote_absent_from_the_document_is_stripped_and_flagged() -> None:
    result = validate(
        {
            "skills": [
                {"name": "Python", "confidence": 95, "source_text": "Rust and Haskell expertise"}
            ]
        }
    )

    skill = by_type(result, CandidateType.SKILL)[0]
    assert skill.source_text is None
    assert skill.payload["flags"] == ["QUOTE_NOT_FOUND"]
    assert skill.confidence <= UNVERIFIED_CONFIDENCE_CAP
    assert any("does not appear" in w for w in result.warnings)


def test_a_real_quote_survives() -> None:
    """A guard that fires on everything is a guard nobody reads."""
    result = validate(
        {"skills": [{"name": "Python", "confidence": 95, "source_text": "Python, FastAPI"}]}
    )

    skill = by_type(result, CandidateType.SKILL)[0]
    assert skill.source_text == "Python, FastAPI"
    assert "flags" not in skill.payload
    assert skill.confidence == 95


def test_quote_matching_ignores_whitespace_and_case() -> None:
    """Extracted text has lost its layout; an exact match would fail on real
    documents and make the warning meaningless."""
    result = validate(
        {"skills": [{"name": "Python", "confidence": 95, "source_text": "python,   FASTAPI"}]}
    )

    assert "flags" not in by_type(result, CandidateType.SKILL)[0].payload


def test_an_invented_metric_is_flagged() -> None:
    """The strongest invariant: never invent a number."""
    result = validate(
        {
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "confidence": 95,
                    "achievements": [
                        {"text": "Improved throughput by 340%.", "confidence": 90},
                    ],
                }
            ]
        }
    )

    achievement = by_type(result, CandidateType.EXPERIENCE)[0].children[0]
    assert achievement.payload["flags"] == ["UNSUPPORTED_NUMBERS"]
    assert any("340" in w for w in result.warnings)


def test_numbers_present_in_the_document_are_not_flagged() -> None:
    result = validate(
        {
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "confidence": 95,
                    "achievements": [
                        {"text": "Took pricing test coverage from 31% to 78%.", "confidence": 90},
                    ],
                }
            ]
        }
    )

    assert "flags" not in by_type(result, CandidateType.EXPERIENCE)[0].children[0].payload


def test_short_digit_runs_are_ignored() -> None:
    """ "2 years" and "top 5" are ordinary text, not fabricated quantities."""
    result = validate(
        {
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "confidence": 95,
                    "achievements": [{"text": "Led a team of 4 for 2 years.", "confidence": 90}],
                }
            ]
        }
    )

    assert "flags" not in by_type(result, CandidateType.EXPERIENCE)[0].children[0].payload


# --- per-type rules -----------------------------------------------------------


def test_skills_are_deduplicated_by_canonical_normalization() -> None:
    """Two spellings of one skill would create one row and leave the second
    silently doing nothing — an accepted item the user never sees appear."""
    result = validate(
        {
            "skills": [
                {"name": "React.js", "confidence": 90},
                {"name": "react js", "confidence": 88},
                {"name": "React", "confidence": 85},
            ]
        }
    )

    assert len(by_type(result, CandidateType.SKILL)) == 2


def test_a_current_role_with_an_end_date_is_reconciled() -> None:
    """The database refuses the combination, and it is a contradiction anyway.
    The end date is the more specific claim, so it wins."""
    result = validate(
        {
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "is_current": True,
                    "end_date": "2024-01",
                    "confidence": 95,
                }
            ]
        }
    )

    experience = by_type(result, CandidateType.EXPERIENCE)[0]
    assert experience.payload["is_current"] is False
    assert experience.payload["end_date"] == "2024-01-01"
    assert any("marked as current" in w for w in result.warnings)


def test_a_reversed_date_range_is_kept_but_reported() -> None:
    """Kept because the user may have the dates the right way round in their
    head and can fix it in the review screen."""
    result = validate(
        {
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "start_date": "2024",
                    "end_date": "2020",
                    "confidence": 95,
                }
            ]
        }
    )

    assert any("before the start date" in w for w in result.warnings)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>", "not a url"])
def test_non_web_links_are_dropped(url: str) -> None:
    """Project links render as anchors, so a javascript: value extracted from an
    uploaded document would be stored XSS supplied by a file."""
    result = validate(
        {"projects": [{"name": "ledgerline", "confidence": 90, "repository_url": url}]}
    )

    assert by_type(result, CandidateType.PROJECT)[0].payload["repository_url"] is None
    assert any("not a web address" in w for w in result.warnings)


def test_https_links_survive() -> None:
    result = validate(
        {
            "projects": [
                {
                    "name": "ledgerline",
                    "confidence": 90,
                    "repository_url": "https://github.com/mayaok/ledgerline",
                }
            ]
        }
    )

    assert (
        by_type(result, CandidateType.PROJECT)[0].payload["repository_url"]
        == "https://github.com/mayaok/ledgerline"
    )


def test_achievements_become_children_of_their_role() -> None:
    """A bullet with no parent has nowhere to go at approval time."""
    result = validate(
        {
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "confidence": 95,
                    "achievements": [
                        {"text": "Migrated 14 legacy Flask endpoints to FastAPI.", "confidence": 90}
                    ],
                }
            ]
        }
    )

    experience = by_type(result, CandidateType.EXPERIENCE)[0]
    assert len(experience.children) == 1
    assert experience.children[0].candidate_type is CandidateType.EXPERIENCE_ACHIEVEMENT


def test_project_technologies_become_children_and_deduplicate() -> None:
    result = validate(
        {
            "projects": [
                {
                    "name": "ledgerline",
                    "confidence": 90,
                    "technologies": [
                        {"name": "Python", "confidence": 95},
                        {"name": "python", "confidence": 90},
                        {"name": "SQLAlchemy", "confidence": 92},
                    ],
                }
            ]
        }
    )

    children = by_type(result, CandidateType.PROJECT)[0].children
    assert len(children) == 2
    assert all(c.candidate_type is CandidateType.PROJECT_SKILL for c in children)


def test_duplicate_projects_are_collapsed() -> None:
    """``projects`` enforces one name per user, so a second would fail the
    constraint at approval time rather than being merely redundant."""
    result = validate(
        {
            "projects": [
                {"name": "ledgerline", "confidence": 90},
                {"name": "Ledgerline", "confidence": 85},
            ]
        }
    )

    assert len(by_type(result, CandidateType.PROJECT)) == 1


def test_a_blank_skill_name_is_reported_not_stored() -> None:
    result = validate({"skills": [{"name": "---", "confidence": 90}]})

    assert by_type(result, CandidateType.SKILL) == []
    assert any("no usable name" in w for w in result.warnings)


def test_all_six_candidate_types_are_produced() -> None:
    """Every approve destination the phase promises must be reachable."""
    result = validate(
        {
            "skills": [{"name": "Python", "confidence": 95}],
            "experiences": [
                {
                    "company": "Verdant Logistics",
                    "title": "Junior Backend Engineer",
                    "confidence": 95,
                    "achievements": [{"text": "Shipped things.", "confidence": 90}],
                }
            ],
            "projects": [
                {
                    "name": "ledgerline",
                    "confidence": 90,
                    "technologies": [{"name": "SQLAlchemy", "confidence": 90}],
                }
            ],
            "education": [{"institution": "University of Lisbon", "confidence": 90}],
        }
    )

    produced = {c.candidate_type for c in result.candidates}
    produced |= {child.candidate_type for c in result.candidates for child in c.children}

    assert produced == set(CandidateType)


# --- schema -------------------------------------------------------------------


def test_an_empty_object_is_a_valid_empty_result() -> None:
    """A resume with nothing extractable is a real answer, not a failure."""
    result = ResumeParseResult.model_validate({})

    assert result.is_empty


def test_unknown_fields_are_dropped_not_fatal() -> None:
    """A model adding a field it thought helpful should not fail the parse, and
    the extra must not reach storage either."""
    result = ResumeParseResult.model_validate(
        {"skills": [{"name": "Python", "confidence": 90, "invented_field": "x"}], "extra": 1}
    )

    assert not hasattr(result.skills[0], "invented_field")


def test_the_provider_schema_is_in_the_supported_subset() -> None:
    """Constrained decoding rejects a schema carrying numeric or length
    keywords, so the generated one has to be sanitised."""
    schema = resume_parse_json_schema()
    serialized = str(schema)

    assert "minimum" not in serialized
    assert "maxLength" not in serialized
    assert schema["additionalProperties"] is False
