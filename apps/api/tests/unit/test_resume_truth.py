"""Truth validation of a proposed rewrite.

The rule these exist to protect is the one ``docs/06-resume-engine.md`` states
without qualification: never invent metrics. Everything else here is secondary
to the first section.

No database, no clock, no model — the validator is deterministic, and if this
file ever needs a fixture with I/O in it, it has stopped being so.
"""

from __future__ import annotations

from jip_api.application.resumes.truth import validate_rewrite
from jip_api.domain.resumes.tailoring import ClaimStatus, SuggestionRisk

FACTS = [
    "Built a routing service in Python handling 12000 requests per second.",
    "Mentored two junior engineers.",
]


# --- invented numbers ---------------------------------------------------------


def test_a_number_that_is_nowhere_in_the_evidence_is_blocked() -> None:
    report = validate_rewrite(
        original="Improved the performance of the routing service.",
        suggested="Improved routing service performance by 40%.",
        source_facts=FACTS,
    )

    assert report.status is ClaimStatus.BLOCKED
    # The percent sign is part of the figure: "40%" and "40" are different
    # claims, and reporting the bare number would misquote the rewrite.
    assert any(claim.text == "40%" for claim in report.claims)


def test_a_blocked_rewrite_may_never_be_applied_automatically() -> None:
    report = validate_rewrite(
        original="Reduced page load time.",
        suggested="Reduced page load time by 3.5 seconds.",
        source_facts=FACTS,
    )

    assert report.may_apply_automatically is False
    assert report.risk is SuggestionRisk.HIGH


def test_a_number_already_in_the_evidence_is_not_an_invention() -> None:
    report = validate_rewrite(
        original="Built a routing service in Python.",
        suggested="Built a Python routing service handling 12000 requests per second.",
        source_facts=FACTS,
    )

    assert not any(claim.status is ClaimStatus.BLOCKED for claim in report.claims)


def test_a_number_the_user_wrote_themselves_is_not_an_invention() -> None:
    """Preserving what someone wrote is not the same as making it up, even when
    the profile has no other record of the figure."""
    report = validate_rewrite(
        original="Cut deploy time by 80%.",
        suggested="Cut deployment time by 80%.",
        source_facts=["Worked on the deployment pipeline."],
    )

    assert not any(claim.status is ClaimStatus.BLOCKED for claim in report.claims)


def test_every_invented_number_is_reported_separately() -> None:
    report = validate_rewrite(
        original="Ran the migration.",
        suggested="Migrated 47 services across 9 teams.",
        source_facts=["Ran the migration."],
    )

    blocked = [claim.text for claim in report.claims if claim.status is ClaimStatus.BLOCKED]
    assert set(blocked) == {"47", "9"}


# --- new content --------------------------------------------------------------


def test_a_word_the_profile_does_not_use_is_raised_for_confirmation() -> None:
    """The other three items on ``docs/06``'s high-risk list — new technology,
    responsibility, scale — surface as words nothing supports."""
    report = validate_rewrite(
        original="Built a routing service in Python.",
        suggested="Built a routing service in Python and Kubernetes.",
        source_facts=FACTS,
    )

    assert report.status is ClaimStatus.REQUIRES_CONFIRMATION
    assert "kubernetes" in report.claims[0].text


def test_rewording_within_the_evidence_is_safe() -> None:
    report = validate_rewrite(
        original="Mentored two junior engineers.",
        suggested="Mentored junior engineers.",
        source_facts=FACTS,
    )

    assert report.status is ClaimStatus.SAFE
    assert report.risk is SuggestionRisk.LOW
    assert report.may_apply_automatically is True


def test_a_grammatical_variant_is_not_a_new_term() -> None:
    """Walked 2026-08-11, on a real rewrite.

    The original said *"Engineered features from historical match data"*; the
    rewrite said *"feature engineering from historical match data"*. The guard
    reported **engineering, feature** as terms the profile does not use — the
    same claim, reshaped, flagged as two new ones.

    Noise here is not harmless. A check that fires on plurals is one people
    learn to skim, and it shares a list with the warnings that matter.
    """
    report = validate_rewrite(
        original="Engineered features from historical match data.",
        suggested="Feature engineering from historical match data.",
        source_facts=["Engineered features from historical match data"],
    )

    assert report.status is ClaimStatus.SAFE


def test_a_title_held_is_still_distinct_from_a_thing_done() -> None:
    """The limit of the stemming above, and the reason it is not more eager.

    "Managed" and "manager" are different claims — one is work, the other is a
    position — so they must not collapse into each other the way "managed" and
    "manages" do.
    """
    report = validate_rewrite(
        original="Managed the deployment pipeline.",
        suggested="Manager of the deployment pipeline.",
        source_facts=["Managed the deployment pipeline"],
    )

    assert report.status is ClaimStatus.REQUIRES_CONFIRMATION
    assert "manager" in report.claims[0].text


def test_a_sentence_final_full_stop_is_not_a_new_term() -> None:
    """The tokeniser admits "." so "node.js" survives whole, which also drags
    in the period ending a sentence. Left alone, the last word of every
    rewritten line reads as a newly introduced term."""
    report = validate_rewrite(
        original="Responsible for working on the routing service.",
        suggested="Built the routing service.",
        source_facts=["Built the routing service"],
    )

    assert report.status is ClaimStatus.SAFE


def test_a_technology_name_containing_digits_is_not_a_metric() -> None:
    """ "p99" is a name, not a figure. Firing the strictest rule in the module
    on a technology someone plainly used is worse than missing one."""
    report = validate_rewrite(
        original="Cut tail latency on the routing service.",
        suggested="Cut p99 latency on the routing service.",
        source_facts=["Cut p99 latency on the routing service"],
    )

    assert not any(claim.status is ClaimStatus.BLOCKED for claim in report.claims)


def test_stopwords_are_not_treated_as_claims() -> None:
    """ "the" appearing in a rewrite and not in the evidence is not an assertion,
    and reporting it would bury the words that are."""
    report = validate_rewrite(
        original="Mentored two junior engineers",
        suggested="Mentored the two junior engineers",
        source_facts=FACTS,
    )

    assert report.status is ClaimStatus.SAFE


# --- risk ---------------------------------------------------------------------


def test_a_new_claim_of_leadership_is_high_risk() -> None:
    report = validate_rewrite(
        original="Worked on the routing service in Python.",
        suggested="Led the routing service in Python.",
        source_facts=FACTS,
    )

    assert report.risk is SuggestionRisk.HIGH
    assert report.may_apply_automatically is False


def test_a_leadership_verb_already_in_the_original_does_not_raise_the_risk() -> None:
    """Risk is about what the rewrite *introduces*. Keeping a word the user
    already used is not a new claim."""
    report = validate_rewrite(
        original="Led the routing service work in Python.",
        suggested="Led routing service work in Python.",
        source_facts=FACTS,
    )

    assert report.risk is SuggestionRisk.LOW


def test_growing_a_line_is_at_least_medium_risk() -> None:
    """Length alone is not proof of invention, but a longer line has said
    something more, and ``docs/06`` wants medium and high reviewed."""
    report = validate_rewrite(
        original="Mentored two junior engineers.",
        suggested="Mentored two junior engineers throughout their first year.",
        source_facts=FACTS,
    )

    assert report.risk is not SuggestionRisk.LOW


def test_a_rewrite_that_says_nothing_new_still_produces_a_claim() -> None:
    """An empty report would read as "not checked" rather than "checked and
    fine", so the safe case is stated explicitly."""
    report = validate_rewrite(
        original="Mentored two junior engineers.",
        suggested="Mentored two junior engineers.",
        source_facts=FACTS,
    )

    assert len(report.claims) == 1
    assert report.claims[0].status is ClaimStatus.SAFE


def test_the_worst_claim_decides_the_verdict() -> None:
    """One invented number makes the sentence false regardless of how well the
    rest of it is evidenced."""
    report = validate_rewrite(
        original="Built a routing service in Python.",
        suggested="Architected a Kubernetes routing service serving 90% of traffic.",
        source_facts=FACTS,
    )

    statuses = {claim.status for claim in report.claims}
    assert ClaimStatus.BLOCKED in statuses
    assert ClaimStatus.REQUIRES_CONFIRMATION in statuses
    assert report.status is ClaimStatus.BLOCKED


def test_validation_is_deterministic() -> None:
    first = validate_rewrite(
        original="Built a routing service.",
        suggested="Architected a Kubernetes routing service by 40%.",
        source_facts=FACTS,
    )
    second = validate_rewrite(
        original="Built a routing service.",
        suggested="Architected a Kubernetes routing service by 40%.",
        source_facts=FACTS,
    )

    assert [(c.text, c.status) for c in first.claims] == [(c.text, c.status) for c in second.claims]
    assert first.risk is second.risk


def test_a_figure_the_user_wrote_is_not_called_fabricated() -> None:
    """Walked 2026-08-11, and the guard accused the author.

    A rewrite came back with the six literal characters that spell the plus-
    minus sign, followed by ``0.5cm``. ``_NUMBER`` rejects a digit preceded by a
    letter, so the only figure it could find was **5** — the tail of a number,
    not the number. ``0.5`` was in the original line and would have passed; 5
    was not, so the strictest rule in the module fired on a figure the user had
    written themselves.

    Repaired at the parse boundary in ``jip_ai.structured``, which is why the
    text here is clean. This asserts the consequence: with the real character
    present, the figure is recognised and nothing is blocked.
    """
    report = validate_rewrite(
        original="Measured newborn length to ±0.5cm accuracy.",
        suggested="Achieved ±0.5cm accuracy measuring newborn length.",
        source_facts=FACTS,
    )

    assert not [claim for claim in report.claims if claim.status is ClaimStatus.BLOCKED]


def test_the_tail_of_a_number_is_what_a_broken_escape_looks_like() -> None:
    """The failure itself, pinned so nobody has to rediscover what it looked like.

    If a stray escape ever survives to here again, this is what the user is
    told: a claim about 5, which appears in neither the original nor the
    evidence. The repair belongs upstream — this only records the shape of the
    damage, so the next person seeing "5" recognises it in one reading.
    """
    report = validate_rewrite(
        original="Measured newborn length to ±0.5cm accuracy.",
        suggested=r"Achieved \u00b10.5cm accuracy measuring newborn length.",
        source_facts=FACTS,
    )

    blocked = [claim.text for claim in report.claims if claim.status is ClaimStatus.BLOCKED]
    assert blocked == ["5"]
