"""Business validation of job parse and analysis output.

The three guards this phase depends on, and the reason each exists:

- a requirement quoting text that is not in the posting is fabricated;
- a "nice to have" recorded as required turns a job someone should apply for
  into one they think they are unqualified for;
- a seniority with no reasoning is an assertion, and Phase 6 would compare a
  real profile against it.
"""

from __future__ import annotations

import pytest

from jip_api.application.jobs.analysis_schema import JobAnalysisResult, JobParseResult
from jip_api.application.jobs.analysis_validation import (
    MINIMUM_CONFIDENCE,
    UNVERIFIED_CONFIDENCE_CAP,
    ValidatedParse,
    validate_analysis_result,
    validate_parse_result,
)
from jip_api.domain.jobs.analysis import (
    AnalyzedSeniority,
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
    RoleFamily,
)

POSTING = """
Senior Backend Engineer

Requirements:
- 5+ years of backend engineering experience
- Strong Python and PostgreSQL
- Kubernetes experience is a nice to have
- Familiarity with Go

You will design and build our routing services and mentor junior engineers.
"""


def requirement(**overrides: object) -> dict[str, object]:
    return {
        "normalized_text": "Python",
        "requirement_type": "TECHNICAL_SKILL",
        "importance": "REQUIRED",
        "explicitness": "EXPLICIT",
        "source_text": "Strong Python and PostgreSQL",
        "confidence": 90,
        **overrides,
    }


def parse(**overrides: object) -> JobParseResult:
    return JobParseResult.model_validate({"requirements": [requirement()], **overrides})


def validate(result: JobParseResult, text: str = POSTING) -> ValidatedParse:
    return validate_parse_result(result, job_text=text)


# --- provenance ---------------------------------------------------------------


def test_keeps_a_requirement_whose_quote_is_in_the_posting() -> None:
    validated = validate(parse())

    assert len(validated.requirements) == 1
    assert validated.requirements[0].source_text == "Strong Python and PostgreSQL"


def test_drops_a_requirement_quoting_text_that_is_not_there() -> None:
    # The failure this catches is silent: nobody reviews job requirements one
    # by one, so a fabricated one would go straight into a matcher.
    validated = validate(
        parse(
            requirements=[
                requirement(
                    normalized_text="AWS",
                    source_text="Deep AWS expertise across every service",
                )
            ]
        )
    )

    assert validated.requirements == []


def test_says_how_many_requirements_were_dropped() -> None:
    validated = validate(
        parse(
            requirements=[
                requirement(source_text="Not in the posting at all"),
                requirement(normalized_text="Go", source_text="Also absent"),
            ]
        )
    )

    assert any("not in this posting" in warning for warning in validated.warnings)


def test_matches_a_quote_across_rewrapped_lines() -> None:
    """Extraction from HTML rewraps text, so a real quote often differs by a
    newline. Requiring an exact match would discard true requirements."""
    text = "We want\n5+ years   of backend\nengineering experience today."
    validated = validate(
        parse(requirements=[requirement(source_text="5+ years of backend engineering experience")]),
        text,
    )

    assert len(validated.requirements) == 1


def test_matching_ignores_case() -> None:
    validated = validate(
        parse(requirements=[requirement(source_text="STRONG PYTHON AND POSTGRESQL")])
    )

    assert len(validated.requirements) == 1


# --- importance ---------------------------------------------------------------


@pytest.mark.parametrize(
    "quote",
    [
        "Kubernetes experience is a nice to have",
        "Familiarity with Go",
    ],
)
def test_demotes_a_hedged_requirement_the_model_called_required(quote: str) -> None:
    hedged = requirement(importance="REQUIRED", source_text=quote)
    validated = validate(parse(requirements=[hedged]))

    assert validated.requirements[0].importance is RequirementImportance.PREFERRED


def test_demotes_a_hedged_requirement_the_model_called_core() -> None:
    validated = validate(
        parse(
            requirements=[
                requirement(
                    importance="CORE", source_text="Kubernetes experience is a nice to have"
                )
            ]
        )
    )

    assert validated.requirements[0].importance is RequirementImportance.PREFERRED


def test_caps_confidence_on_a_demoted_requirement() -> None:
    """We disagreed with the model about this item, so our own certainty about
    it should not stay at the number it supplied."""
    validated = validate(
        parse(
            requirements=[
                requirement(
                    importance="REQUIRED",
                    confidence=99,
                    source_text="Kubernetes experience is a nice to have",
                )
            ]
        )
    )

    assert validated.requirements[0].confidence <= UNVERIFIED_CONFIDENCE_CAP


def test_explains_the_demotion_to_the_user() -> None:
    validated = validate(
        parse(
            requirements=[
                requirement(
                    importance="REQUIRED", source_text="Kubernetes experience is a nice to have"
                )
            ]
        )
    )

    assert any("preference" in warning for warning in validated.warnings)


def test_leaves_a_genuinely_required_item_alone() -> None:
    validated = validate(
        parse(
            requirements=[
                requirement(
                    importance="REQUIRED",
                    source_text="5+ years of backend engineering experience",
                )
            ]
        )
    )

    assert validated.requirements[0].importance is RequirementImportance.REQUIRED


def test_never_promotes_a_preference() -> None:
    """The guard is one-directional on purpose. A model that saw the whole
    posting is trusted to be stricter than a rule reading one sentence, but
    never more lenient — promotion is the damaging direction."""
    validated = validate(
        parse(
            requirements=[
                requirement(
                    importance="PREFERRED",
                    source_text="5+ years of backend engineering experience",
                )
            ]
        )
    )

    assert validated.requirements[0].importance is RequirementImportance.PREFERRED


def test_keeps_unknown_importance_as_unknown() -> None:
    validated = validate(parse(requirements=[requirement(importance="UNKNOWN")]))

    assert validated.requirements[0].importance is RequirementImportance.UNKNOWN


# --- confidence and de-duplication --------------------------------------------


def test_drops_a_requirement_below_the_confidence_floor() -> None:
    validated = validate(parse(requirements=[requirement(confidence=MINIMUM_CONFIDENCE - 1)]))

    assert validated.requirements == []


def test_keeps_a_requirement_at_the_confidence_floor() -> None:
    validated = validate(parse(requirements=[requirement(confidence=MINIMUM_CONFIDENCE)]))

    assert len(validated.requirements) == 1


def test_collapses_the_same_requirement_extracted_twice() -> None:
    """Postings repeat themselves between a summary and a bullet list."""
    validated = validate(
        parse(
            requirements=[
                requirement(normalized_text="Python"),
                requirement(normalized_text="python"),
            ]
        )
    )

    assert len(validated.requirements) == 1


def test_keeps_the_same_text_under_two_different_types() -> None:
    """ "Python" as a skill and "Python" as domain knowledge are different
    claims, and merging them would lose one."""
    validated = validate(
        parse(
            requirements=[
                requirement(normalized_text="Python", requirement_type="TECHNICAL_SKILL"),
                requirement(normalized_text="Python", requirement_type="DOMAIN_KNOWLEDGE"),
            ]
        )
    )

    assert len(validated.requirements) == 2


def test_preserves_the_posting_s_order() -> None:
    validated = validate(
        parse(
            requirements=[
                requirement(normalized_text="First"),
                requirement(normalized_text="Second"),
            ]
        )
    )

    assert [r.source_order for r in validated.requirements] == [0, 1]


# --- fields -------------------------------------------------------------------


def test_records_the_named_technology_for_a_skill_requirement() -> None:
    validated = validate(parse(requirements=[requirement(skill_name="Python")]))

    assert validated.requirements[0].skill_name == "Python"


def test_drops_a_skill_name_from_a_non_skill_requirement() -> None:
    """A skill name on a LOCATION requirement is a model slip, and carrying it
    forward would put "Lisbon" into skill resolution."""
    validated = validate(
        parse(
            requirements=[
                requirement(
                    requirement_type="LOCATION",
                    normalized_text="Lisbon",
                    skill_name="Lisbon",
                )
            ]
        )
    )

    assert validated.requirements[0].skill_name is None


def test_keeps_years_attached_to_a_requirement() -> None:
    validated = validate(
        parse(
            requirements=[
                requirement(
                    requirement_type="EXPERIENCE",
                    normalized_text="5+ years backend",
                    source_text="5+ years of backend engineering experience",
                    years_min=5,
                )
            ]
        )
    )

    assert validated.requirements[0].years_min == 5


def test_keeps_explicitness_as_reported() -> None:
    validated = validate(parse(requirements=[requirement(explicitness="IMPLIED")]))

    assert validated.requirements[0].explicitness is RequirementExplicitness.IMPLIED


def test_maps_the_requirement_type() -> None:
    validated = validate(parse(requirements=[requirement(requirement_type="WORK_AUTHORIZATION")]))

    assert validated.requirements[0].requirement_type is RequirementType.WORK_AUTHORIZATION


# --- responsibilities ---------------------------------------------------------


def test_keeps_a_responsibility_whose_quote_is_real() -> None:
    validated = validate(
        parse(
            responsibilities=[
                {
                    "text": "Design and build routing services",
                    "source_text": "You will design and build our routing services",
                    "confidence": 90,
                }
            ]
        )
    )

    assert len(validated.responsibilities) == 1


def test_drops_a_fabricated_responsibility() -> None:
    validated = validate(
        parse(
            responsibilities=[
                {
                    "text": "Run the company",
                    "source_text": "You will run the entire company",
                    "confidence": 90,
                }
            ]
        )
    )

    assert validated.responsibilities == []


def test_collapses_a_repeated_responsibility() -> None:
    validated = validate(
        parse(
            responsibilities=[
                {
                    "text": "Design and build routing services",
                    "source_text": "You will design and build our routing services",
                    "confidence": 90,
                },
                {
                    "text": "design and build routing services",
                    "source_text": "You will design and build our routing services",
                    "confidence": 80,
                },
            ]
        )
    )

    assert len(validated.responsibilities) == 1


# --- years range --------------------------------------------------------------


def test_keeps_a_sensible_years_range() -> None:
    validated = validate(parse(years_experience_min=3, years_experience_max=6))

    assert (validated.years_experience_min, validated.years_experience_max) == (3, 6)


def test_drops_a_reversed_years_range() -> None:
    """A range saying "between 8 and 3 years" is a reading error, and showing
    it would be presenting nonsense as what the posting asked for."""
    validated = validate(parse(years_experience_min=8, years_experience_max=3))

    assert validated.years_experience_min is None
    assert validated.years_experience_max is None
    assert any("impossible range" in warning for warning in validated.warnings)


# --- analysis -----------------------------------------------------------------


def analysis(**overrides: object) -> JobAnalysisResult:
    return JobAnalysisResult.model_validate(
        {
            "role_family": "BACKEND",
            "role_family_confidence": 90,
            "role_family_reasoning": "Server-side services in Python and PostgreSQL.",
            "seniority": "SENIOR",
            "seniority_confidence": 85,
            "seniority_reasoning": "Asks for 5+ years and expects platform ownership.",
            **overrides,
        }
    )


def test_keeps_a_seniority_with_real_reasoning() -> None:
    validated = validate_analysis_result(analysis(), has_requirements=True)

    assert validated.seniority is AnalyzedSeniority.SENIOR
    assert validated.seniority_confidence == 85


def test_demotes_a_seniority_with_no_reasoning() -> None:
    """A level with no grounds is an assertion, and Phase 6 would compare a
    real person's experience against it."""
    validated = validate_analysis_result(analysis(seniority_reasoning=None), has_requirements=True)

    assert validated.seniority is AnalyzedSeniority.UNKNOWN
    assert validated.seniority_confidence == 0


def test_demotes_a_seniority_whose_reasoning_says_nothing() -> None:
    validated = validate_analysis_result(analysis(seniority_reasoning="n/a"), has_requirements=True)

    assert validated.seniority is AnalyzedSeniority.UNKNOWN


def test_explains_a_demoted_seniority() -> None:
    validated = validate_analysis_result(analysis(seniority_reasoning=""), has_requirements=True)

    assert any("reasoning" in warning for warning in validated.warnings)


def test_refuses_a_seniority_when_nothing_could_be_extracted() -> None:
    """ "Senior Engineer, apply within" supports no level. Reading the title and
    stopping is the exact failure docs/05-ai-and-matching.md warns about."""
    validated = validate_analysis_result(analysis(), has_requirements=False)

    assert validated.seniority is AnalyzedSeniority.UNKNOWN
    assert any("guessed from the title" in warning for warning in validated.warnings)


def test_allows_unknown_seniority_without_reasoning() -> None:
    validated = validate_analysis_result(
        analysis(seniority="UNKNOWN", seniority_reasoning=None), has_requirements=True
    )

    assert validated.seniority is AnalyzedSeniority.UNKNOWN
    assert validated.warnings == []


def test_keeps_the_role_family() -> None:
    validated = validate_analysis_result(analysis(), has_requirements=True)

    assert validated.role_family is RoleFamily.BACKEND


def test_keeps_a_genuine_secondary_family() -> None:
    validated = validate_analysis_result(
        analysis(secondary_role_family="DATA_ENGINEERING"), has_requirements=True
    )

    assert validated.secondary_role_family is RoleFamily.DATA_ENGINEERING


def test_drops_a_secondary_family_that_repeats_the_primary() -> None:
    """ "Backend, and also backend" is noise, not a second family."""
    validated = validate_analysis_result(
        analysis(secondary_role_family="BACKEND"), has_requirements=True
    )

    assert validated.secondary_role_family is None


def test_role_family_survives_a_demoted_seniority() -> None:
    """The two judgements are independent, and one being unsupported says
    nothing about the other."""
    validated = validate_analysis_result(analysis(seniority_reasoning=None), has_requirements=True)

    assert validated.role_family is RoleFamily.BACKEND
    assert validated.seniority is AnalyzedSeniority.UNKNOWN


def test_blanks_a_whitespace_only_domain() -> None:
    validated = validate_analysis_result(analysis(domain="   "), has_requirements=True)

    assert validated.domain is None
