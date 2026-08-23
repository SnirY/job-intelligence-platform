"""The legitimacy rules: what they catch, and what they must not.

Half of these tests assert that a rule stays quiet. That is deliberate and it is
the harder half — a scam detector that fires on ordinary postings teaches the
reader to ignore it, and an ignored warning is worse than none at all.

Nothing here touches a database or a model. The rules are pure functions over a
posting's own words.
"""

from __future__ import annotations

import datetime as dt

import pytest

from jip_api.application.jobs.legitimacy import (
    LONG_RUNNING_DAYS,
    THIN_DESCRIPTION_CHARS,
    read_posting,
)
from jip_api.domain.jobs.legitimacy import ConcernConfidence, PostingConcernType

NOW = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.UTC)

REAL = (
    "We are hiring a Senior Backend Engineer for our shipment platform. You will "
    "build REST services in Python and FastAPI, own the PostgreSQL schema behind "
    "carrier reconciliation, and help move the remaining Flask endpoints across. "
    "We work hybrid from Lisbon, two days a week in the office. You will join a "
    "team of six and report to the Head of Platform. We offer private healthcare, "
    "a learning budget, and we cover the cost of your equipment."
)


def types(description: str | None = REAL, **kwargs: object) -> set[PostingConcernType]:
    reading = read_posting(description=description, now=NOW, **kwargs)  # type: ignore[arg-type]
    return {concern.type for concern in reading.concerns}


# --- an ordinary posting ------------------------------------------------------


def test_an_ordinary_posting_raises_nothing() -> None:
    """The test that keeps the others honest."""
    assert types() == set()


def test_covering_the_candidates_costs_is_not_asking_for_money() -> None:
    """`REAL` ends with "we cover the cost of your equipment".

    The payment patterns are anchored on the applicant being the one paying, and
    this is the sentence that would break a lazier version of them.
    """
    assert PostingConcernType.PAYMENT_REQUESTED not in types()


def test_a_messaging_company_is_not_off_platform_contact() -> None:
    """Naming an app is not the same as being told to be hired through one."""
    posting = REAL + " You will work on our Telegram and WhatsApp integrations."

    assert PostingConcernType.OFF_PLATFORM_CONTACT not in types(posting)


# --- asking for money ---------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "There is a one-time training fee of $250.",
        "Successful applicants pay a deposit before starting.",
        "You will need to purchase your own equipment upfront.",
        "Please send us payment to reserve your place.",
        "You cover the cost of your background check.",
    ],
)
def test_asking_the_applicant_to_pay_is_caught(phrase: str) -> None:
    assert PostingConcernType.PAYMENT_REQUESTED in types(REAL + " " + phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "There is no registration fee.",
        "We never ask you to pay a deposit.",
        "Training is provided free of charge, with not a single training fee.",
    ],
)
def test_a_posting_denying_a_fee_is_not_demanding_one(phrase: str) -> None:
    """ "There is no registration fee" contains "registration fee" and means the
    opposite of it."""
    assert PostingConcernType.PAYMENT_REQUESTED not in types(REAL + " " + phrase)


def test_denying_one_fee_does_not_hide_demanding_another() -> None:
    """The scan keeps looking past a negated match rather than stopping at it."""
    posting = REAL + " There is no registration fee. You will pay a deposit of $300."

    assert PostingConcernType.PAYMENT_REQUESTED in types(posting)


def test_a_payment_concern_quotes_the_posting() -> None:
    """A reading that cannot point at what produced it is one nobody can check."""
    reading = read_posting(description=REAL + " There is a one-time training fee.", now=NOW)

    concern = next(c for c in reading.concerns if c.type is PostingConcernType.PAYMENT_REQUESTED)
    assert concern.evidence is not None
    assert "training fee" in concern.evidence


def test_asking_for_money_is_the_most_serious_thing_here() -> None:
    assert (
        read_posting(description="Pay a deposit to begin.", now=NOW).concerns[0].confidence
        is ConcernConfidence.NEAR_CERTAIN
    )


# --- being routed off the platform --------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "Contact me on WhatsApp to arrange the interview.",
        "Message us via Telegram for next steps.",
        "The interview will be conducted on WhatsApp.",
        "WhatsApp me for details.",
    ],
)
def test_being_sent_to_a_personal_account_is_caught(phrase: str) -> None:
    assert PostingConcernType.OFF_PLATFORM_CONTACT in types(REAL + " " + phrase)


# --- how much posting there is ------------------------------------------------


def test_a_very_short_posting_says_so() -> None:
    reading = read_posting(description="Backend engineer wanted. Apply now.", now=NOW)

    concern = next(c for c in reading.concerns if c.type is PostingConcernType.THIN_DESCRIPTION)
    assert concern.confidence is ConcernConfidence.OBSERVED
    assert concern.evidence is None


def test_a_short_posting_is_not_accused_of_anything() -> None:
    """Plenty of real postings are short, and the wording has to reflect that."""
    reading = read_posting(description="Backend engineer wanted.", now=NOW)

    concern = next(c for c in reading.concerns if c.type is PostingConcernType.THIN_DESCRIPTION)
    assert "scam" not in concern.summary.lower()
    assert "fake" not in concern.summary.lower()


def test_a_posting_just_over_the_threshold_stays_quiet() -> None:
    assert PostingConcernType.THIN_DESCRIPTION not in types("x" * (THIN_DESCRIPTION_CHARS + 1))


def test_no_description_raises_no_text_concerns() -> None:
    """A job added by hand has no posting. That is not a thin posting."""
    assert types(None) == set()


# --- how long it has been open ------------------------------------------------


def test_a_long_running_posting_is_noticed() -> None:
    old = NOW - dt.timedelta(days=LONG_RUNNING_DAYS + 1)

    assert PostingConcernType.LONG_RUNNING in types(posted_at=old)


def test_a_recent_posting_is_not() -> None:
    recent = NOW - dt.timedelta(days=LONG_RUNNING_DAYS - 1)

    assert PostingConcernType.LONG_RUNNING not in types(posted_at=recent)


def test_an_unknown_date_is_not_an_old_posting() -> None:
    """Invariant 14, in the engine rather than on the screen."""
    assert PostingConcernType.LONG_RUNNING not in types(posted_at=None, first_seen_at=None)


def test_when_we_first_saw_it_stands_in_for_a_missing_publish_date() -> None:
    """A lower bound is the best available answer for anything that did not
    arrive through discovery."""
    seen = NOW - dt.timedelta(days=LONG_RUNNING_DAYS + 5)

    assert PostingConcernType.LONG_RUNNING in types(posted_at=None, first_seen_at=seen)


def test_the_boards_own_date_is_preferred_over_ours() -> None:
    """We may have found a role months after it was published."""
    assert PostingConcernType.LONG_RUNNING in types(
        posted_at=NOW - dt.timedelta(days=LONG_RUNNING_DAYS + 5),
        first_seen_at=NOW - dt.timedelta(days=2),
    )


def test_a_naive_date_is_read_as_utc_rather_than_dropped() -> None:
    naive = dt.datetime(2026, 1, 1, 12, 0)

    assert PostingConcernType.LONG_RUNNING in types(posted_at=naive)


def test_a_date_in_the_future_is_not_an_old_posting() -> None:
    """A board with a clock problem must not produce a negative age."""
    assert PostingConcernType.LONG_RUNNING not in types(posted_at=NOW + dt.timedelta(days=5))


# --- ordering -----------------------------------------------------------------


def test_the_most_serious_concern_comes_first() -> None:
    """So a screen that shows only one does not show the least important."""
    posting = "Pay a training fee. " + "x" * 10

    reading = read_posting(description=posting, now=NOW)

    assert reading.concerns[0].type is PostingConcernType.PAYMENT_REQUESTED
    assert len(reading.concerns) > 1


# --- the rule the whole slice exists to keep ----------------------------------


def test_nothing_here_produces_a_score() -> None:
    """A number can be averaged, weighted and eventually folded into the match.

    A list of named concerns cannot be, without someone writing the code that
    does it — which is the friction this design is for. If this test has to
    change, the change is the thing to argue about.
    """
    reading = read_posting(description="Pay a training fee to start.", now=NOW)

    assert not hasattr(reading, "score")
    assert not hasattr(reading, "rating")
    for concern in reading.concerns:
        assert not hasattr(concern, "score")
        assert not hasattr(concern, "weight")


def test_the_matcher_does_not_know_this_module_exists() -> None:
    """Structural, not a promise.

    The guarantee that a concern cannot move a score is that the scoring code
    has no way to reach it.
    """
    import pathlib

    matching = pathlib.Path(__file__).resolve().parents[2] / "src" / "jip_api" / "application"
    sources = (matching / "matching").rglob("*.py")

    for source in sources:
        assert "legitimacy" not in source.read_text(encoding="utf-8")
