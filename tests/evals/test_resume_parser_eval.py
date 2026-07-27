"""Coverage evaluation for ``resume_parser_v1``.

Did the parser find what is plainly written in the document? Floors, not exact
counts — a parser that finds *more* real detail than a fixture records is not a
regression, and pinning exact numbers would make every prompt improvement a
test failure.

The offline run replays a recorded response; the live run calls a real model.
Same expectations both ways.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from jip_ai import LLMProvider
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.resumes.parsing import ResumeParseOutcome
from jip_api.domain.career.skills import normalize_skill_name
from jip_api.domain.documents.models import CandidateType

from .conftest import EvalCase, parse

ProviderFactory = Callable[[EvalCase], FakeLLMProvider]


def _names(outcome: ResumeParseOutcome, candidate_type: CandidateType, key: str) -> set[str]:
    return {
        str(c.payload[key]).strip()
        for c in outcome.validated.candidates
        if c.candidate_type is candidate_type and key in c.payload
    }


def _count(outcome: ResumeParseOutcome, candidate_type: CandidateType) -> int:
    return sum(1 for c in outcome.validated.candidates if c.candidate_type is candidate_type)


def test_expected_skills_are_extracted(
    case: EvalCase, offline_provider_factory: ProviderFactory
) -> None:
    """Compared after canonical normalization.

    "react js" satisfies an expectation of "React.js": they are the same string
    by the rule the rest of the platform matches on. Alias collapsing —
    React.js to React — is the catalogue's job at approval time, not the
    parser's.
    """
    outcome = parse(offline_provider_factory(case), case)

    found = {normalize_skill_name(n) for n in _names(outcome, CandidateType.SKILL, "name")}
    missing = [s for s in case.expect("expect_skills", []) if normalize_skill_name(s) not in found]

    assert not missing, f"{case.name}: did not extract {missing}"


def test_expected_companies_are_extracted(
    case: EvalCase, offline_provider_factory: ProviderFactory
) -> None:
    outcome = parse(offline_provider_factory(case), case)

    found = {c.casefold() for c in _names(outcome, CandidateType.EXPERIENCE, "company")}
    missing = [c for c in case.expect("expect_companies", []) if c.casefold() not in found]

    assert not missing, f"{case.name}: did not extract employers {missing}"


@pytest.mark.parametrize(
    ("key", "candidate_type"),
    [
        ("expect_min_experiences", CandidateType.EXPERIENCE),
        ("expect_min_projects", CandidateType.PROJECT),
        ("expect_min_education", CandidateType.EDUCATION),
    ],
)
def test_minimum_counts(
    case: EvalCase,
    offline_provider_factory: ProviderFactory,
    key: str,
    candidate_type: CandidateType,
) -> None:
    outcome = parse(offline_provider_factory(case), case)
    expected = int(case.expect(key, 0))

    assert _count(outcome, candidate_type) >= expected, (
        f"{case.name}: expected at least {expected} {candidate_type}"
    )


def test_forbidden_text_is_absent(
    case: EvalCase, offline_provider_factory: ProviderFactory
) -> None:
    """Text a correct parse must never produce.

    This is where a seniority the resume never claimed, or any other known
    invention, gets pinned once it has been observed.
    """
    outcome = parse(offline_provider_factory(case), case)

    serialized = str([c.payload for c in outcome.validated.candidates])
    offending = [s for s in case.expect("forbid_substrings", []) if s in serialized]

    assert not offending, f"{case.name}: output contains forbidden text {offending}"


def test_achievements_are_attached_to_their_role(
    case: EvalCase, offline_provider_factory: ProviderFactory
) -> None:
    """An achievement is only usable if it knows which job it belongs to.

    Loose bullets cannot be approved — the confirm step has nowhere to put them
    — so this is a correctness property, not presentation.
    """
    outcome = parse(offline_provider_factory(case), case)

    for candidate in outcome.validated.candidates:
        for child in candidate.children:
            if child.candidate_type is CandidateType.EXPERIENCE_ACHIEVEMENT:
                assert candidate.candidate_type is CandidateType.EXPERIENCE


# --- live mode ----------------------------------------------------------------


@pytest.mark.live_ai
def test_live_model_meets_the_same_expectations(case: EvalCase, live_provider: LLMProvider) -> None:
    """The same assertions against a real model.

    Skipped unless ``JIP_RUN_AI_EVALS=1``. This is the run that measures the
    model rather than the code around it.
    """
    from jip_config import get_settings

    outcome = parse(live_provider, case, model=get_settings().ai_resume_parse_model)

    found = {normalize_skill_name(n) for n in _names(outcome, CandidateType.SKILL, "name")}
    missing = [s for s in case.expect("expect_skills", []) if normalize_skill_name(s) not in found]

    assert not missing, f"{case.name}: live model did not extract {missing}"
