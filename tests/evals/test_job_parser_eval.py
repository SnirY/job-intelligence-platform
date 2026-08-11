"""Evaluation for ``job_parser_v1`` and ``job_analysis_v1``.

Two kinds of assertion here, and the difference matters:

- **Coverage** — did the parser find what is plainly written? Floors, not exact
  counts. A parser that finds more real detail than a fixture records is not a
  regression, and pinning exact numbers would make every prompt improvement a
  test failure.
- **Correctness** — is anything it produced invented, or promoted beyond what
  the posting said? These are absolute. A fixture may under-extract and still
  pass; a fabricated requirement or a promoted preference is a defect.

The offline run replays recorded responses; the live run calls a real model.
Same expectations both ways.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from jip_ai import LLMProvider
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.jobs.analysis_services import JobParseOutcome
from jip_api.application.jobs.analysis_validation import RequirementDraft
from jip_api.domain.career.skills import normalize_skill_name
from jip_api.domain.jobs.analysis import RequirementImportance

from .job_conftest import JobEvalCase, analyze_job, parse_job

ProviderFactory = Callable[[JobEvalCase], FakeLLMProvider]


def _normalized(outcome: JobParseOutcome) -> set[str]:
    return {r.normalized_text.casefold() for r in outcome.validated.requirements}


def _covers(outcome: JobParseOutcome, expected: str) -> bool:
    """Whether the parse found ``expected``, however it chose to word it.

    DEV-047. The live check used to be `expected.casefold() in {normalized_text}`
    — an exact string match against the *recorded* response's phrasing. The
    offline run replays that recording, so it always passed; the live model
    phrases things its own way, so it always failed. Three fixtures reported
    that a real model "did not extract Python" from a posting that says Python.

    DEV-026 measured this exact effect and named the fix: keyed by text, 31-46%
    of requirements survive a re-reading; keyed by resolved skill, 75%. The eval
    was keyed by text.

    So an expectation is met when either the resolved skill matches it outright,
    or every significant word of it appears in the requirement's own text —
    which accepts "5+ years of backend engineering experience" for
    "5+ years backend engineering" and still rejects a requirement that is
    simply about something else.
    """
    wanted = expected.casefold()
    tokens = {word for word in re.findall(r"[a-z0-9+#.]+", wanted) if word not in _NOISE}

    for requirement in outcome.validated.requirements:
        skill = (requirement.skill_name or "").casefold()
        # `skill in wanted` is what accepts the model answering "JS" where the
        # fixture expects "JavaScript". Guarded at two characters so a
        # single-letter skill — "R", "C" — cannot match every word containing
        # it.
        if skill and (skill == wanted or wanted in skill or (len(skill) > 1 and skill in wanted)):
            return True

        text = requirement.normalized_text.casefold()
        if wanted in text:
            return True
        if tokens and tokens <= set(re.findall(r"[a-z0-9+#.]+", text)):
            return True

    return False


_NOISE = frozenset({"a", "an", "and", "of", "or", "the", "in", "with", "to", "for", "experience"})
"""Words that carry no identity. "5+ years backend engineering" and "5+ years of
backend engineering experience" are the same requirement."""


def _by_importance(outcome: JobParseOutcome, importance: RequirementImportance) -> set[str]:
    return {
        r.normalized_text.casefold()
        for r in outcome.validated.requirements
        if r.importance is importance
    }


def _mandatory(outcome: JobParseOutcome) -> set[str]:
    return {
        r.normalized_text.casefold()
        for r in outcome.validated.requirements
        if r.importance.is_mandatory
    }


def _requirement(outcome: JobParseOutcome, name: str) -> RequirementDraft:
    return next(
        r for r in outcome.validated.requirements if r.normalized_text.casefold() == name.casefold()
    )


# --- coverage -----------------------------------------------------------------


def test_expected_requirements_are_extracted(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    found = _normalized(outcome)
    missing = [r for r in job_case.expect("expect_requirements", []) if r.casefold() not in found]

    assert not missing, f"{job_case.name}: did not extract {missing}"


def test_minimum_requirement_count(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)
    expected = int(job_case.expect("expect_min_requirements", 0))

    assert len(outcome.validated.requirements) >= expected, (
        f"{job_case.name}: expected at least {expected} requirements"
    )


def test_minimum_responsibility_count(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)
    expected = int(job_case.expect("expect_min_responsibilities", 0))

    assert len(outcome.validated.responsibilities) >= expected, (
        f"{job_case.name}: expected at least {expected} responsibilities"
    )


def test_expected_requirement_types_are_present(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """Types drive weighting in Phase 6. A posting whose work-authorization
    line is filed as OTHER loses a blocker."""
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    found = {str(r.requirement_type) for r in outcome.validated.requirements}
    missing = [t for t in job_case.expect("expect_requirement_types", []) if t not in found]

    assert not missing, f"{job_case.name}: no requirement of type {missing}"


def test_named_technologies_are_recorded(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """Compared after canonical normalization.

    "React.js" satisfies an expectation of "react js" — the same string by the
    rule the rest of the platform matches on. Alias collapsing to React is the
    catalogue's job at resolution time, not the parser's.
    """
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    found = {
        normalize_skill_name(r.skill_name)
        for r in outcome.validated.requirements
        if r.skill_name is not None
    }
    missing = [
        s for s in job_case.expect("expect_skill_names", []) if normalize_skill_name(s) not in found
    ]

    assert not missing, f"{job_case.name}: did not record technologies {missing}"


# --- importance ---------------------------------------------------------------


def test_required_items_stay_required(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    mandatory = _mandatory(outcome)
    demoted = [r for r in job_case.expect("expect_required", []) if r.casefold() not in mandatory]

    assert not demoted, f"{job_case.name}: genuinely required items lost their weight: {demoted}"


def test_preferences_are_never_presented_as_requirements(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """The substitution that turns a job someone should apply for into one they
    think they are unqualified for. ``promoted_preferences`` exists to prove
    this fires against a model that gets every one of them wrong."""
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    mandatory = _mandatory(outcome)
    promoted = [r for r in job_case.expect("expect_preferred", []) if r.casefold() in mandatory]

    assert not promoted, f"{job_case.name}: preferences presented as required: {promoted}"


def test_preferences_are_kept_rather_than_dropped(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """Demotion is a correction, not a deletion. A "nice to have" the user
    happens to have is worth showing them."""
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    found = _normalized(outcome)
    missing = [r for r in job_case.expect("expect_preferred", []) if r.casefold() not in found]

    assert not missing, f"{job_case.name}: preferences disappeared entirely: {missing}"


# --- fabrication --------------------------------------------------------------


def test_forbidden_requirements_are_absent(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """Where a known invention gets pinned once it has been seen."""
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    found = _normalized(outcome)
    offending = [r for r in job_case.expect("forbid_requirements", []) if r.casefold() in found]

    assert not offending, f"{job_case.name}: output contains fabricated requirements {offending}"


def test_every_requirement_quotes_the_posting(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """The invariant for this phase, and the one that survives every fixture.

    Whatever else a parse gets wrong, a requirement claiming the posting said
    something it did not is the defect that reaches a matcher unreviewed.
    """
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)
    haystack = " ".join(job_case.job_text.split()).casefold()

    for requirement in outcome.validated.requirements:
        quoted = " ".join(requirement.source_text.split()).casefold()
        assert quoted in haystack, (
            f"{job_case.name}: {requirement.normalized_text!r} quotes text "
            f"that is not in the posting"
        )


def test_every_responsibility_quotes_the_posting(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    outcome = parse_job(offline_job_provider_factory(job_case), job_case)
    haystack = " ".join(job_case.job_text.split()).casefold()

    for responsibility in outcome.validated.responsibilities:
        assert responsibility.source_text is not None
        quoted = " ".join(responsibility.source_text.split()).casefold()
        assert quoted in haystack, f"{job_case.name}: a responsibility quotes absent text"


def test_a_maximum_is_respected_where_one_is_set(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """Only the vague posting sets this. A three-line advert that produces ten
    requirements has invented nine of them."""
    maximum = job_case.expect("expect_max_requirements")
    if maximum is None:
        pytest.skip("no ceiling set for this posting")

    outcome = parse_job(offline_job_provider_factory(job_case), job_case)

    assert len(outcome.validated.requirements) <= int(maximum)


# --- analysis -----------------------------------------------------------------


def test_role_family_is_correct(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    provider = offline_job_provider_factory(job_case)
    parse = parse_job(provider, job_case)
    analysis = analyze_job(provider, job_case, parse)

    expected = job_case.expect("expect_role_family")
    assert str(analysis.validated.role_family) == expected, (
        f"{job_case.name}: expected {expected}, got {analysis.validated.role_family}"
    )


def test_seniority_is_correct(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    """Includes ``vague_posting``, whose recorded response confidently answers
    SENIOR from the title alone and must come back UNKNOWN."""
    provider = offline_job_provider_factory(job_case)
    parse = parse_job(provider, job_case)
    analysis = analyze_job(provider, job_case, parse)

    expected = job_case.expect("expect_seniority")
    assert str(analysis.validated.seniority) == expected, (
        f"{job_case.name}: expected {expected}, got {analysis.validated.seniority}"
    )


def test_a_stated_seniority_comes_with_reasoning(
    job_case: JobEvalCase, offline_job_provider_factory: ProviderFactory
) -> None:
    provider = offline_job_provider_factory(job_case)
    parse = parse_job(provider, job_case)
    analysis = analyze_job(provider, job_case, parse)

    if str(analysis.validated.seniority) == "UNKNOWN":
        pytest.skip("nothing to justify")

    assert analysis.validated.seniority_reasoning


# --- live mode ----------------------------------------------------------------


@pytest.mark.live_ai
def test_live_model_meets_the_same_expectations(
    job_case: JobEvalCase, live_provider: LLMProvider
) -> None:
    """The same assertions against a real model.

    Skipped unless ``JIP_RUN_AI_EVALS=1``. This is the run that measures the
    model rather than the code around it.
    """
    from jip_config import get_settings

    model = get_settings().ai_job_parse_model or get_settings().ai_resume_parse_model
    parse = parse_job(live_provider, job_case, model=model)

    missing = [r for r in job_case.expect("expect_requirements", []) if not _covers(parse, r)]
    assert not missing, (
        f"{job_case.name}: live model did not extract {missing}. "
        f"Found: {sorted(_normalized(parse))}"
    )

    mandatory = _mandatory(parse)
    promoted = [r for r in job_case.expect("expect_preferred", []) if r.casefold() in mandatory]
    assert not promoted, f"{job_case.name}: live model promoted preferences: {promoted}"


@pytest.mark.live_ai
def test_live_model_judges_seniority_the_same_way(
    job_case: JobEvalCase, live_provider: LLMProvider
) -> None:
    from jip_config import get_settings

    settings = get_settings()
    model = settings.ai_job_analysis_model or settings.ai_resume_parse_model
    parse = parse_job(live_provider, job_case, model=model)
    analysis = analyze_job(live_provider, job_case, parse, model=model)

    assert str(analysis.validated.seniority) == job_case.expect("expect_seniority")
