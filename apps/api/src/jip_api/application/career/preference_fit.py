"""Comparing a posting against what the user said they want.

``docs/05-ai-and-matching.md`` lists location and user preferences among the
inputs a recommendation considers. This is that comparison, and everything about
its shape follows from two decisions.

**It does not touch the score, and it does not touch the stored
recommendation.** Alignment is about evidence: whether the profile answers what
the posting asked for. A job in the wrong city does not fit your skills any
less. Folding preference into the number would make a figure move when nothing
about the fit moved, and `job_matches.recommendation` is written once at match
time — a preference changed tomorrow would leave every stored recommendation
quietly stale, with no path to re-derive it. So this is computed on read,
returned beside the recommendation, and labelled as a different kind of thing.

**Silence is never agreement.** Every dimension reports one of five verdicts,
and three of them are ways of saying "no answer". A posting that does not state
its work mode must not be reported as matching a remote-only preference, and a
preference nobody set must not be reported as satisfied. The failure this
guards against is precisely DEV-035's: a preference stored and then quietly
ignored, where the user believes it was taken into account.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass

from jip_api.domain.career.models import CareerPreferences
from jip_api.domain.jobs.analysis import JobAnalysis
from jip_api.domain.jobs.models import Job


class FitVerdict(enum.StrEnum):
    """How one preference stands against one posting."""

    MATCHES = "MATCHES"
    CONFLICTS = "CONFLICTS"
    UNCONFIRMED = "UNCONFIRMED"
    """The posting says something and it did not match — but not matching is not
    the same as conflicting when the comparison is prose against prose."""

    NOT_STATED = "NOT_STATED"
    """The posting does not say. A gap in what we know about the job."""

    NO_PREFERENCE = "NO_PREFERENCE"
    """The user has not said. A gap in what we know about the user."""

    NOT_COMPARED = "NOT_COMPARED"
    """Deliberately not checked, with a reason. Salary is the only one."""


@dataclass(frozen=True, slots=True)
class PreferenceFit:
    """One dimension's reading."""

    dimension: str
    verdict: FitVerdict
    detail: str


# Only three dimensions can return CONFLICTS: work mode, employment type and
# role family, the ones with a closed vocabulary on *both* sides. Where the
# comparison is prose against prose, an unmatched value means we could not
# confirm it rather than that it is wrong — "Caesarea, Israel" against a
# preference of "Tel Aviv" is a different city in the same country, and calling
# that a conflict would be a claim the data does not support. Each function
# below enforces this for itself; a shared constant would only restate it.


def assess(
    *,
    job: Job,
    analysis: JobAnalysis | None,
    preferences: CareerPreferences | None,
) -> list[PreferenceFit]:
    """Read every dimension, always returning all of them.

    Omitting the ones with nothing to say would leave a short list that looks
    like a clean bill of health. The screen needs to show *what was not
    checked* as prominently as what was.
    """
    prefs = preferences
    return [
        _work_mode(job, prefs),
        _employment_type(job, prefs),
        _location(job, prefs),
        _role_family(analysis, prefs),
        _salary(),
    ]


def _work_mode(job: Job, prefs: CareerPreferences | None) -> PreferenceFit:
    wanted = list(prefs.work_modes) if prefs else []
    if not wanted:
        return PreferenceFit("work_mode", FitVerdict.NO_PREFERENCE, "You have not set a work mode.")
    if not job.work_mode:
        # Common, and worth saying plainly: the analysis extracts a location
        # string that often carries the mode in prose ("(Hybrid - at least 3
        # times a week from office)"), but nothing parses a work mode out of it.
        return PreferenceFit(
            "work_mode",
            FitVerdict.NOT_STATED,
            "This posting does not state whether it is on-site, hybrid or remote.",
        )
    if job.work_mode in wanted:
        return PreferenceFit(
            "work_mode", FitVerdict.MATCHES, f"This role is {_human(job.work_mode)}."
        )
    return PreferenceFit(
        "work_mode",
        FitVerdict.CONFLICTS,
        f"This role is {_human(job.work_mode)} and you asked for "
        f"{_join(_human(mode) for mode in wanted)}.",
    )


def _employment_type(job: Job, prefs: CareerPreferences | None) -> PreferenceFit:
    wanted = list(prefs.employment_types) if prefs else []
    if not wanted:
        return PreferenceFit(
            "employment_type", FitVerdict.NO_PREFERENCE, "You have not set an employment type."
        )
    if not job.employment_type:
        return PreferenceFit(
            "employment_type",
            FitVerdict.NOT_STATED,
            "This posting does not state its employment type.",
        )
    if job.employment_type in wanted:
        return PreferenceFit(
            "employment_type", FitVerdict.MATCHES, f"This role is {_human(job.employment_type)}."
        )
    return PreferenceFit(
        "employment_type",
        FitVerdict.CONFLICTS,
        f"This role is {_human(job.employment_type)} and you asked for "
        f"{_join(_human(kind) for kind in wanted)}.",
    )


def _location(job: Job, prefs: CareerPreferences | None) -> PreferenceFit:
    wanted = [place.strip() for place in (prefs.locations if prefs else []) if place.strip()]
    if not wanted:
        return PreferenceFit("location", FitVerdict.NO_PREFERENCE, "You have not set a location.")
    if not job.location:
        return PreferenceFit(
            "location", FitVerdict.NOT_STATED, "This posting does not state a location."
        )

    haystack = job.location.casefold()
    hit = next((place for place in wanted if place.casefold() in haystack), None)
    if hit is not None:
        return PreferenceFit("location", FitVerdict.MATCHES, f"{job.location} — matches {hit}.")

    if prefs is not None and prefs.open_to_relocation:
        return PreferenceFit(
            "location",
            FitVerdict.MATCHES,
            f"{job.location} is not on your list, but you are open to relocating.",
        )

    # Not CONFLICTS. One free-text string failing to contain another is weak
    # evidence: "Merkaz" does not contain "Tel Aviv" and may well be it.
    return PreferenceFit(
        "location",
        FitVerdict.UNCONFIRMED,
        f"{job.location} does not obviously match {_join(wanted)} — worth checking yourself.",
    )


def _role_family(analysis: JobAnalysis | None, prefs: CareerPreferences | None) -> PreferenceFit:
    excluded = list(prefs.excluded_role_families) if prefs else []
    if not excluded:
        return PreferenceFit(
            "role_family", FitVerdict.NO_PREFERENCE, "You have not excluded any role types."
        )
    if analysis is None or not analysis.role_family:
        return PreferenceFit(
            "role_family",
            FitVerdict.NOT_STATED,
            "This job has not been analysed for its role type.",
        )
    if analysis.role_family in excluded:
        return PreferenceFit(
            "role_family",
            FitVerdict.CONFLICTS,
            f"We read this as a {_human(analysis.role_family)} role, which you excluded.",
        )
    return PreferenceFit(
        "role_family",
        FitVerdict.MATCHES,
        f"We read this as a {_human(analysis.role_family)} role, which you did not exclude.",
    )


def _salary() -> PreferenceFit:
    """Never compared, and the reason is shown rather than left as silence.

    `jobs.salary_text` is free text — "competitive", "₪25-30k", nothing at all.
    Turning that into a number to compare against would be a guess presented as
    arithmetic, and a wrong comparison here is worse than none: the user would
    discard a job on a figure we invented.
    """
    return PreferenceFit(
        "salary",
        FitVerdict.NOT_COMPARED,
        "Postings state pay as free text when they state it at all, so we do not "
        "compare it. Yours is recorded for your own reference.",
    )


def _human(value: str) -> str:
    return value.replace("_", " ").lower()


def _join(values: Iterable[str]) -> str:
    items = list(values)
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} or {items[-1]}"
