"""Main-content extraction and URL normalization.

Both are mechanical, not semantic. Extraction knows a ``<script>`` is not prose;
it does not know what a requirement is, which is Phase 5's job.
"""

from __future__ import annotations

import pytest

from jip_api.domain.jobs.models import normalize_title
from jip_api.domain.jobs.urls import normalize_url
from jip_api.infrastructure.fetching.content import (
    MINIMUM_USEFUL_CHARS,
    extract_content,
    has_useful_content,
)

PAGE = """<!doctype html>
<html>
  <head>
    <title>Senior Backend Engineer at Verdant — Careers</title>
    <style>.hero { color: red }</style>
    <script>window.analytics = {track: function(){}};</script>
  </head>
  <body>
    <nav><a href="/">Home</a><a href="/jobs">All jobs</a></nav>
    <header><h1>Verdant Logistics</h1></header>
    <main>
      <h2>Senior Backend Engineer</h2>
      <p>We are looking for a backend engineer to work on our shipment platform.</p>
      <ul>
        <li>Five years of Python experience</li>
        <li>Experience with PostgreSQL and FastAPI</li>
      </ul>
      <p>Salary: competitive. Location: Lisbon, hybrid.</p>
    </main>
    <footer><p>Copyright Verdant Logistics</p></footer>
  </body>
</html>
"""


# --- extraction ---------------------------------------------------------------


def test_extracts_the_body_text() -> None:
    extracted = extract_content(PAGE)

    assert "shipment platform" in extracted.text
    assert "Five years of Python experience" in extracted.text


def test_script_and_style_contents_never_appear() -> None:
    """Their text is skipped, not stripped afterwards — otherwise an inline
    script lands in the middle of the description."""
    text = extract_content(PAGE).text

    assert "window.analytics" not in text
    assert "color: red" not in text


def test_navigation_and_footers_are_dropped() -> None:
    """Structural furniture is on every page and part of none of them."""
    text = extract_content(PAGE).text

    assert "All jobs" not in text
    assert "Copyright" not in text


def test_the_title_is_offered_as_a_suggestion() -> None:
    """Read, but never stored as a fact without the user seeing it —
    docs/11-engineering-standards.md says never trust external metadata."""
    assert extract_content(PAGE).title == "Senior Backend Engineer at Verdant — Careers"


def test_headings_are_collected() -> None:
    assert "Senior Backend Engineer" in extract_content(PAGE).headings


def test_list_items_stay_on_separate_lines() -> None:
    """A bullet list run together is unreadable, and Phase 5 parses this text.

    The assertion is that the items are on different lines, not which blank-line
    convention separates them — that is formatting, and pinning it would make
    every whitespace tweak a test failure.
    """
    lines = [line for line in extract_content(PAGE).text.split("\n") if line.strip()]

    assert "Five years of Python experience" in lines
    assert "Experience with PostgreSQL and FastAPI" in lines


def test_adjacent_inline_elements_keep_their_word_break() -> None:
    """ "Senior</b> <b>Engineer" must not become "SeniorEngineer"."""
    text = extract_content("<html><body><p><b>Senior</b> <b>Engineer</b></p></body></html>").text

    assert "Senior Engineer" in text


def test_entities_are_decoded() -> None:
    page = "<html><body><p>R&amp;D &mdash; Sales &amp; Marketing</p></body></html>"

    assert "R&D — Sales & Marketing" in extract_content(page).text


def test_plain_text_passes_through_untouched() -> None:
    """A pasted description containing an angle bracket must not be mangled."""
    pasted = "We use generics like List<String> in our Java codebase.\n\nApply within."

    extracted = extract_content(pasted)

    assert "List<String>" in extracted.text
    assert extracted.title is None


def test_malformed_markup_does_not_lose_the_page() -> None:
    broken = "<html><body><p>Backend Engineer<div><span>Lisbon</body>"

    text = extract_content(broken).text

    assert "Backend Engineer" in text
    assert "Lisbon" in text


def test_whitespace_is_normalised_without_changing_words() -> None:
    page = "<html><body><p>Backend     Engineer</p>\n\n\n\n<p>Lisbon</p></body></html>"

    text = extract_content(page).text

    assert "Backend Engineer" in text
    assert "\n\n\n" not in text


def test_a_javascript_shell_is_reported_as_not_useful() -> None:
    """A single-page app returns a shell with almost no text. Saying so lets the
    user paste instead of storing boilerplate and calling it a success."""
    shell = "<!doctype html><html><body><div id='root'></div></body></html>"

    assert not has_useful_content(extract_content(shell).text)


def test_a_real_posting_is_useful() -> None:
    assert has_useful_content("x" * MINIMUM_USEFUL_CHARS)


# --- URL normalization --------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("https://jobs.example.com/role/1", "https://jobs.example.com/role/1/"),
        ("https://jobs.example.com/role/1", "http://jobs.example.com/role/1"),
        ("https://JOBS.example.com/role/1", "https://jobs.example.com/role/1"),
        ("https://www.example.com/role/1", "https://example.com/role/1"),
        ("https://m.example.com/role/1", "https://example.com/role/1"),
        ("https://example.com:443/role/1", "https://example.com/role/1"),
        ("https://example.com/role/1#apply", "https://example.com/role/1"),
        (
            "https://example.com/role?id=1&utm_source=linkedin&fbclid=xyz",
            "https://example.com/role?id=1",
        ),
        ("https://example.com/role?b=2&a=1", "https://example.com/role?a=1&b=2"),
    ],
)
def test_equivalent_urls_normalize_together(left: str, right: str) -> None:
    assert normalize_url(left) == normalize_url(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("https://example.com/role/1", "https://example.com/role/2"),
        ("https://example.com/role?id=1", "https://example.com/role?id=2"),
        ("https://a.example.com/role", "https://b.example.com/role"),
        # Paths are case-sensitive on plenty of sites, so lowercasing one would
        # merge two different postings.
        ("https://example.com/Role/AbC", "https://example.com/role/abc"),
        ("https://example.com:8080/role", "https://example.com/role"),
    ],
)
def test_different_urls_stay_different(left: str, right: str) -> None:
    assert normalize_url(left) != normalize_url(right)


def test_an_unknown_query_parameter_is_kept() -> None:
    """Dropping unrecognised parameters would collapse every posting on a site
    that identifies them in the query string into one key."""
    assert "jobId=884" in str(normalize_url("https://example.com/careers?jobId=884"))


@pytest.mark.parametrize("raw", ["not a url", "file:///etc/passwd", "ftp://example.com/x", ""])
def test_non_web_urls_have_no_key(raw: str) -> None:
    assert normalize_url(raw) is None


def test_a_bare_domain_normalizes_to_root() -> None:
    assert normalize_url("https://example.com") == "https://example.com/"


# --- title normalization ------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Senior Backend Engineer", "senior backend engineer  "),
        ("Back-End Engineer", "Back End Engineer"),
        ("Engineer (Remote)", "Engineer Remote"),
    ],
)
def test_equivalent_titles_normalize_together(left: str, right: str) -> None:
    assert normalize_title(left) == normalize_title(right)


def test_different_titles_stay_different() -> None:
    assert normalize_title("Backend Engineer") != normalize_title("Frontend Engineer")
