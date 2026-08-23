"""What a cover letter is allowed to say, and the setting that decides it.

A resume rewrite is anchored: there is an original line, and validation asks
whether the new wording says more than the old one did. **A letter has no
original.** So it is validated with `original=""`, which is the strictest thing
`truth.py` does — every figure in the text must appear in the career facts or
the claim is BLOCKED.

These tests are about that difference, not about `truth.py` itself, which has
its own file next door. They exist because the setting is one character and the
consequence is whether a candidate walks into an interview holding a number they
cannot back up.
"""

from __future__ import annotations

from jip_api.application.resumes.truth import TruthReport, validate_rewrite
from jip_api.domain.resumes.tailoring import ClaimStatus

FACTS = [
    "Built REST services in Python and FastAPI for a shipment platform",
    "Owned the PostgreSQL schema behind carrier reconciliation",
    "Led the migration of 12 Flask endpoints to FastAPI",
]


def letter(text: str) -> TruthReport:
    """Validated the way a letter is: with nothing to be anchored against."""
    return validate_rewrite(original="", suggested=text, source_facts=FACTS)


def test_a_letter_drawn_from_the_facts_passes() -> None:
    report = letter(
        "I have built REST services in Python and FastAPI, and I owned the "
        "PostgreSQL schema behind carrier reconciliation."
    )

    assert report.status is ClaimStatus.SAFE


def test_a_figure_the_profile_does_not_carry_is_blocked() -> None:
    """The rule the empty original exists to enforce.

    In a rewrite, a number already in the original line is fine — preserving
    what the user wrote is not inventing. A letter has no original, so there is
    nothing for a number to be preserved *from*.
    """
    report = letter("I reduced reconciliation errors by 40% across the platform.")

    assert report.status is ClaimStatus.BLOCKED


def test_a_figure_the_profile_does_carry_is_not() -> None:
    """`12` is in the facts, so quoting it back is reporting, not inventing."""
    report = letter("I led the migration of 12 Flask endpoints to FastAPI.")

    assert report.status is not ClaimStatus.BLOCKED


def test_a_technology_the_profile_never_mentions_is_reported() -> None:
    """The implication failure the prompt spends a section on.

    Nothing in the facts says Kubernetes. A letter claiming it is the exact
    thing the candidate gets asked about in the interview.
    """
    report = letter("I have run production workloads on Kubernetes for three years.")

    assert report.status is not ClaimStatus.SAFE


def test_the_worst_claim_decides_the_letter() -> None:
    """One invented figure makes the letter unsendable regardless of the rest.

    Same rule as a rewrite, and it matters more here: a letter is read as one
    statement, so a reader who catches one false claim discounts all of them.
    """
    report = letter("I built REST services in Python and FastAPI. I also cut latency by 60%.")

    assert report.status is ClaimStatus.BLOCKED


def test_a_blocked_letter_still_says_which_sentence() -> None:
    """`docs/06` wants the claim quoted back, not the document refused.

    The user may know the number is real, in which case the fix is to add it to
    their profile — which is what "the system may ask for missing metrics" means.
    """
    report = letter("I reduced reconciliation errors by 40%.")

    blocked = [c for c in report.claims if c.status is ClaimStatus.BLOCKED]
    assert blocked
    assert blocked[0].explanation
