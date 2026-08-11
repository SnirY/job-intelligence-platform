"""The invariant: hallucinated facts = 0.

``docs/05-ai-and-matching.md`` calls this the strongest resume invariant.
Coverage tests measure how much a parser finds; these measure whether anything
it produced was invented — a different question, and the one that decides
whether a user can trust the review screen.

Two guards are under test, both of which check the model's claims against the
document rather than against another model:

1. A number in a candidate that appears nowhere in the resume.
2. A quoted ``source_text`` that is not in the resume.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.resumes.parsing import ResumeParseOutcome
from jip_api.application.resumes.validation import UNVERIFIED_CONFIDENCE_CAP, CandidateDraft

from .conftest import CASES, EvalCase, parse

ProviderFactory = Callable[[EvalCase], FakeLLMProvider]

_DIGIT_RUN = re.compile(r"\d+")

FABRICATION_CASE = next(c for c in CASES if c.path.stem == "fabricated_metrics")


def _all_candidates(outcome: ResumeParseOutcome) -> list[CandidateDraft]:
    """Flatten parents and children — a fabricated metric usually sits in a
    child achievement, not in the role above it."""
    flat: list[CandidateDraft] = []
    for candidate in outcome.validated.candidates:
        flat.append(candidate)
        flat.extend(candidate.children)
    return flat


def _flags(candidate: CandidateDraft) -> list[str]:
    flags = candidate.payload.get("flags", [])
    return list(flags) if isinstance(flags, list) else []


def _text(candidate: CandidateDraft) -> str:
    return str(candidate.payload.get("text", ""))


def _fabrication_outcome() -> ResumeParseOutcome:
    # Four responses, one per section: DEV-017 split the parse and
    # `FakeLLMProvider` replays in request order.
    return parse(FakeLLMProvider(FABRICATION_CASE.recorded_sections), FABRICATION_CASE)


def test_no_candidate_carries_a_number_absent_from_the_document(
    case: EvalCase, offline_provider_factory: ProviderFactory
) -> None:
    """Every long digit run in an unflagged candidate must exist in the resume.

    Runs of one or two digits are excluded, matching the validator: they are
    ordinary text ("2 years", "top 5") and flagging them would make the warning
    worthless.
    """
    outcome = parse(offline_provider_factory(case), case)
    document_digits = set(_DIGIT_RUN.findall(case.resume_text))

    offenders: list[tuple[str, str]] = []
    for candidate in _all_candidates(outcome):
        if "UNSUPPORTED_NUMBERS" in _flags(candidate):
            continue  # already caught and surfaced to the user
        text = _text(candidate)
        for run in _DIGIT_RUN.findall(text):
            if len(run) > 2 and run not in document_digits:
                offenders.append((run, text[:80]))

    assert not offenders, f"{case.name}: unflagged invented numbers {offenders}"


def test_quoted_source_text_appears_in_the_document(
    case: EvalCase, offline_provider_factory: ProviderFactory
) -> None:
    """Provenance the user can check has to be checkable.

    A ``source_text`` that survives validation must be findable in the resume;
    anything else is removed by the validator, so a survivor that is not there
    means the guard failed.
    """
    outcome = parse(offline_provider_factory(case), case)
    haystack = re.sub(r"\s+", " ", case.resume_text).strip().casefold()

    for candidate in _all_candidates(outcome):
        if not candidate.source_text:
            continue
        needle = re.sub(r"\s+", " ", candidate.source_text).strip().casefold()
        assert needle in haystack, f"{case.name}: quoted text not in document"


# --- the deliberately-defective fixture ---------------------------------------


def test_invented_numbers_are_flagged() -> None:
    """The fabrication fixture's two invented metrics must both be caught."""
    flagged = {
        _text(c)
        for c in _all_candidates(_fabrication_outcome())
        if "UNSUPPORTED_NUMBERS" in _flags(c)
    }

    assert any("340" in text for text in flagged), "the 340% claim was not flagged"
    assert any("250000" in text for text in flagged), "the 250,000 users claim was not flagged"


def test_a_bad_quote_is_removed_and_flagged() -> None:
    """The fourth achievement quotes a sentence the resume does not contain.

    The item survives — the user may well have written something like it — but
    its false evidence is stripped and it is marked for checking.
    """
    suspect = next(
        c for c in _all_candidates(_fabrication_outcome()) if "infrastructure spend" in _text(c)
    )

    assert "QUOTE_NOT_FOUND" in _flags(suspect)
    assert suspect.source_text is None


def test_flagged_candidates_have_their_confidence_capped() -> None:
    """A flagged item must not present as high-confidence.

    The review screen sorts and styles on confidence, so leaving a fabricated
    metric at 88 would put it at the top of the list looking trustworthy.
    """
    for candidate in _all_candidates(_fabrication_outcome()):
        if _flags(candidate):
            assert candidate.confidence is not None
            assert candidate.confidence <= UNVERIFIED_CONFIDENCE_CAP


def test_the_honest_achievement_is_untouched() -> None:
    """A guard that fires on everything is a guard nobody reads."""
    clean = next(
        c for c in _all_candidates(_fabrication_outcome()) if _text(c) == "Reduced deployment time."
    )

    assert _flags(clean) == []
    assert clean.confidence == 90


def test_every_flag_produces_a_warning_for_the_user() -> None:
    """Flags are machine-readable; warnings are what the person actually sees.

    A flag with no warning is a defect the user is never told about.
    """
    outcome = _fabrication_outcome()
    flagged = [c for c in _all_candidates(outcome) if _flags(c)]

    assert len(flagged) >= 3
    assert len(outcome.warnings) >= len(flagged)
