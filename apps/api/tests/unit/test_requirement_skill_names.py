"""Cleaning a technology name out of the prose a posting wraps around it.

Resolution itself needs the catalogue and is covered in the integration suite.
This is the part that runs before the query, and its whole risk is
over-cleaning: "Node.js" and "C++" are names, and a rule clever enough to strip
"strong" is one edit away from stripping "++".
"""

from __future__ import annotations

import pytest

from jip_api.application.jobs.requirement_skills import clean_skill_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Python", "Python"),
        ("  Python  ", "Python"),
        ("Strong Python", "Python"),
        ("strong python", "python"),
        ("Solid Kubernetes", "Kubernetes"),
        ("Deep PostgreSQL", "PostgreSQL"),
        ("Excellent Go", "Go"),
        ("Hands-on Terraform", "Terraform"),
        ("Hands on Terraform", "Terraform"),
        ("Advanced TypeScript", "TypeScript"),
        ("Basic SQL", "SQL"),
        ("Proven Java", "Java"),
        ("Extensive Rust", "Rust"),
        ("Some Ruby", "Ruby"),
        ("Working Scala", "Scala"),
    ],
)
def test_strips_leading_qualifiers(raw: str, expected: str) -> None:
    assert clean_skill_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rust (advantageous)", "Rust"),
        ("Kubernetes (a plus)", "Kubernetes"),
        ("Go [optional]", "Go"),
        ("Python experience", "Python"),
        ("Kubernetes knowledge", "Kubernetes"),
        ("React skills", "React"),
        ("Java skill", "Java"),
        ("Docker proficiency", "Docker"),
    ],
)
def test_strips_trailing_qualifiers(raw: str, expected: str) -> None:
    assert clean_skill_name(raw) == expected


def test_strips_both_ends() -> None:
    assert clean_skill_name("Strong Kubernetes experience") == "Kubernetes"


@pytest.mark.parametrize(
    "name",
    ["Node.js", "C++", "C#", "F#", "Objective-C", ".NET", "Vue.js", "Next.js", "ASP.NET Core"],
)
def test_leaves_punctuated_names_intact(name: str) -> None:
    # The reason cleaning only touches affixes. A rule that reached into the
    # middle of a string would merge C, C++, and C# into one skill.
    assert clean_skill_name(name) == name


def test_does_not_strip_a_qualifier_that_is_part_of_the_name() -> None:
    """ "Basic" leads here, but the name is "BASIC" — and stripping it would
    leave nothing, which the empty-result guard catches."""
    assert clean_skill_name("BASIC") == "BASIC"


def test_returns_the_original_when_cleaning_would_empty_it() -> None:
    assert clean_skill_name("strong") == "strong"


def test_handles_a_blank_name() -> None:
    assert clean_skill_name("   ") == ""


def test_stops_after_a_bounded_number_of_passes() -> None:
    """Pathological input must terminate rather than clean perfectly.

    Six stacked qualifiers is not real input. The guarantee is that this
    returns — an unbounded loop here would be a worse bug than a name that is
    only partly cleaned, and a partly cleaned name simply fails to resolve.
    """
    result = clean_skill_name("strong solid deep excellent good basic Rust")

    assert result.endswith("Rust")
    assert not result.startswith("strong")
