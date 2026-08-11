"""Refusing a document that is not a resume.

DEV-020. Upload validation asks four questions about file integrity and none
about contents, so a Hebrew product specification was accepted, parsed, and
presented as a normal review screen.

The product decision was rejection over a soft warning. That takes on the risk
DEV-020 names — *"an unusual or non-standard CV would be blocked, and that is
exactly the kind of heuristic that fails on the real case"* — so most of what is
below is about the false positive rather than the true one. A test file for a
heuristic like this is worth more for the documents it insists must pass.
"""

# ruff: noqa: RUF001
# The Hebrew fixtures are the point of this file. A vav that resembles a Latin
# "l" is what a real document contains, and substituting lookalikes would test
# a string no user will ever upload.

from __future__ import annotations

import pytest

from jip_api.application.resumes.looks_like_a_resume import MINIMUM_SIGNALS, check

# --- documents that must be accepted ------------------------------------------

ORDINARY_CV = """\
Maya Okonkwo
maya.okonkwo@example.com · +44 20 7946 0958

EXPERIENCE
Junior Backend Engineer, Verdant Logistics
2021 - Present
Built REST endpoints in FastAPI.

EDUCATION
BSc Computer Science, University of Leeds, 2018 - 2021
"""

HEBREW_CV = """\
שניר יהודה
snir@example.com

ניסיון תעסוקתי
מהנדס תוכנה, ראדקום
מרץ 2021 - היום

השכלה
תואר ראשון בהנדסת תוכנה, מכללת בראודה
"""

SPARSE_ACADEMIC_CV = """\
Dr. A. Rahman
a.rahman@university.edu

Publications
"On the stability of iterative solvers", Journal of Numerical Analysis, 2019
"A note on preconditioning", 2021
"""

DESIGNER_CV_MOSTLY_LINKS = """\
Jonah Pike
github.com/jonahpike

Selected work
Rebrand for Halcyon Coffee, 2022 - 2023
Identity system for Northwind Books
"""


@pytest.mark.parametrize(
    ("name", "document"),
    [
        ("an ordinary CV", ORDINARY_CV),
        ("a Hebrew CV", HEBREW_CV),
        ("a sparse academic CV", SPARSE_ACADEMIC_CV),
        ("a designer's CV that is mostly links", DESIGNER_CV_MOSTLY_LINKS),
    ],
)
def test_a_real_resume_is_accepted(name: str, document: str) -> None:
    """The failure that matters. Every one of these is missing something a
    typical CV has, and every one has to get through."""
    assert check(document).is_resume, name


# --- documents that must be refused -------------------------------------------

PRODUCT_SPEC = """\
Product Specification: Ingest Service

The ingest service accepts uploads over HTTP and writes them to object storage.
It is built with Python, FastAPI and PostgreSQL, and deployed to Kubernetes.

Throughput target: 400 requests per second.
Retention: objects are kept until deleted by their owner.
"""

HEBREW_PRODUCT_SPEC = """\
מפרט מוצר: שירות קליטה

השירות מקבל קבצים ושומר אותם באחסון אובייקטים.
נבנה עם פייתון, FastAPI ו-PostgreSQL.
"""

INVOICE = """\
INVOICE 2024-0184

Halcyon Coffee Ltd
Amount due: 1,250.00
Payment terms: 30 days
"""


@pytest.mark.parametrize(
    ("name", "document"),
    [
        ("an English product specification", PRODUCT_SPEC),
        ("the Hebrew specification that found DEV-020", HEBREW_PRODUCT_SPEC),
        ("an invoice", INVOICE),
    ],
)
def test_a_document_that_is_not_a_resume_is_refused(name: str, document: str) -> None:
    assert not check(document).is_resume, name


# --- the threshold itself ------------------------------------------------------


def test_one_signal_is_not_enough() -> None:
    """An email address alone is most documents. Accepting on one signal is the
    same as not checking."""
    verdict = check("Questions? Write to support@example.com.")

    assert len(verdict.found) == 1
    assert not verdict.is_resume


def test_two_signals_are_enough() -> None:
    """The threshold, asserted rather than left implicit in the fixtures."""
    verdict = check("Experience\nSoftware Engineer, 2019 - 2022")

    assert len(verdict.found) == MINIMUM_SIGNALS
    assert verdict.is_resume


def test_a_bare_year_is_not_a_date() -> None:
    """Every copyright notice has one. Counting it would accept every document
    with a footer."""
    verdict = check("Copyright 2024 Halcyon Coffee Ltd. All rights reserved.")

    assert not verdict.is_resume


def test_the_same_signal_many_times_still_counts_once() -> None:
    """Forty repetitions of one fact is one fact."""
    verdict = check("mail@example.com\n" * 40)

    assert len(verdict.found) == 1
    assert not verdict.is_resume


def test_an_empty_document_is_refused_without_raising() -> None:
    assert not check("").is_resume


def test_the_reason_says_what_to_do_next() -> None:
    """A refusal that only says no leaves the user with a file and no route.
    `GOAL.md`: a failure must leave the work recoverable."""
    reason = check(PRODUCT_SPEC).reason

    assert "does not look like a resume" in reason
    assert "by hand" in reason
