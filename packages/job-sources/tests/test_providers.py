"""The three board providers, against fixtures rather than the network.

**No test here opens a socket.** `AGENTS.md` gives the reason in another
context and it applies exactly: a test that needs the internet is a test that
silently stops running, and these would additionally depend on three companies
not changing their open roles.

The fixtures are hand-written, and the field names, nesting and value formats in
them were taken from live responses to the three documented endpoints — a
Greenhouse `location` really is an object with a `name`, Lever's `createdAt`
really is epoch milliseconds, Ashby's `publishedAt` really carries an offset.
Written by hand rather than recorded so they can also carry what real data does
not: a malformed row, an unlisted posting, a missing location.

What is asserted is the mapping and the skipping. A change in a board's shape
must fail that board's test and no other.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from jip_sources.models import BoardRef, InvalidBoard
from jip_sources.providers.ashby import AshbySource
from jip_sources.providers.greenhouse import GreenhouseSource
from jip_sources.providers.lever import LeverSource

GREENHOUSE: dict[str, Any] = {
    "jobs": [
        {
            "id": 4512345,
            "title": "Senior Backend Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/verdant/jobs/4512345",
            "location": {"name": "Lisbon, Portugal; Remote"},
            "company_name": "Verdant Logistics",
            "first_published": "2026-08-01T09:00:00-04:00",
            "updated_at": "2026-08-20T11:00:00-04:00",
            # Entity-encoded markup, which is how Greenhouse sends a posting.
            "content": "&lt;p&gt;We are hiring a &lt;strong&gt;backend&lt;/strong&gt; engineer.&lt;/p&gt;",  # noqa: E501
        },
        # No title. Skipped, and the row above still arrives.
        {"id": 999, "absolute_url": "https://example.com/x", "location": {"name": "Berlin"}},
    ],
    "meta": {"total": 2},
}

LEVER: list[Any] = [
    {
        "id": "6c2ab1f4-0000-4a1e-9d3f-2b7c5a9e1234",
        "text": "Platform Engineer",
        "hostedUrl": "https://jobs.lever.co/tidewater/6c2ab1f4",
        "applyUrl": "https://jobs.lever.co/tidewater/6c2ab1f4/apply",
        "createdAt": 1785574800000,  # 2026-08-01T09:00:00Z, in milliseconds
        "categories": {"location": "Berlin, Germany", "team": "Platform"},
        "descriptionPlain": "You will own the deployment pipeline.",
        "description": "<p>You will own the deployment pipeline.</p>",
    },
    "not a posting at all",
]

ASHBY: dict[str, Any] = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "8f1c-listed",
            "title": "Data Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/harborlight/8f1c",
            "location": "Remote - European Union",
            "secondaryLocations": [{"location": "Dublin"}],
            "publishedAt": "2026-07-15T14:29:08.532+00:00",
            "descriptionPlain": "Own the warehouse.",
            "descriptionHtml": "<p>Own the warehouse.</p>",
            "isListed": True,
        },
        {
            "id": "8f1d-unlisted",
            "title": "Secret Role",
            "jobUrl": "https://jobs.ashbyhq.com/harborlight/8f1d",
            "location": "Remote",
            "publishedAt": "2026-07-15T14:29:08.532+00:00",
            "isListed": False,
        },
    ],
}


def stub(monkeypatch: pytest.MonkeyPatch, module: str, payload: Any) -> list[str]:
    """Answer the provider's one HTTP call, and record the URL it asked for."""
    asked: list[str] = []

    def _get_json(url: str, **_kwargs: object) -> Any:
        asked.append(url)
        return payload

    monkeypatch.setattr(f"jip_sources.providers.{module}.get_json", _get_json)
    return asked


# --- Greenhouse ---------------------------------------------------------------


def test_greenhouse_maps_a_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, "greenhouse", GREENHOUSE)

    postings = GreenhouseSource().fetch(BoardRef("greenhouse", "verdant"))

    assert len(postings) == 1
    posting = postings[0]
    assert posting.external_id == "4512345"
    assert posting.title == "Senior Backend Engineer"
    assert posting.company == "Verdant Logistics"
    assert posting.location == "Lisbon, Portugal; Remote"
    assert posting.posted_at == dt.datetime(
        2026, 8, 1, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4))
    )


def test_greenhouse_asks_for_the_posting_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without `content=true` a posting arrives with no description at all, and
    a posting with no text cannot be analysed."""
    asked = stub(monkeypatch, "greenhouse", GREENHOUSE)

    GreenhouseSource().fetch(BoardRef("greenhouse", "verdant"))

    assert asked == ["https://boards-api.greenhouse.io/v1/boards/verdant/jobs?content=true"]


def test_greenhouse_unescapes_the_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Greenhouse sends HTML, entity-encoded. One unescape puts it back."""
    stub(monkeypatch, "greenhouse", GREENHOUSE)

    posting = GreenhouseSource().fetch(BoardRef("greenhouse", "verdant"))[0]

    assert posting.description_html == "<p>We are hiring a <strong>backend</strong> engineer.</p>"
    # Text is not invented from the markup here. Extraction is the caller's, and
    # it is the same extractor a pasted page goes through.
    assert posting.description_text is None


def test_greenhouse_prefers_when_it_was_published(monkeypatch: pytest.MonkeyPatch) -> None:
    """`updated_at` moves whenever anyone edits the posting, so it does not
    answer "how old is this"."""
    stub(monkeypatch, "greenhouse", GREENHOUSE)

    posting = GreenhouseSource().fetch(BoardRef("greenhouse", "verdant"))[0]

    assert posting.posted_at is not None
    assert posting.posted_at.date() == dt.date(2026, 8, 1)


# --- Lever --------------------------------------------------------------------


def test_lever_maps_a_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, "lever", LEVER)

    postings = LeverSource().fetch(BoardRef("lever", "tidewater", label="Tidewater"))

    assert len(postings) == 1
    posting = postings[0]
    assert posting.title == "Platform Engineer"
    assert posting.url == "https://jobs.lever.co/tidewater/6c2ab1f4"
    assert posting.location == "Berlin, Germany"
    assert posting.description_text == "You will own the deployment pipeline."


def test_lever_reads_epoch_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """`createdAt` is milliseconds and the payload does not say so."""
    stub(monkeypatch, "lever", LEVER)

    posting = LeverSource().fetch(BoardRef("lever", "tidewater"))[0]

    assert posting.posted_at == dt.datetime(2026, 8, 1, 9, 0, tzinfo=dt.UTC)


def test_lever_names_the_company_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lever's payload never says which company the board belongs to."""
    stub(monkeypatch, "lever", LEVER)

    labelled = LeverSource().fetch(BoardRef("lever", "tidewater", label="Tidewater"))[0]
    bare = LeverSource().fetch(BoardRef("lever", "tidewater"))[0]

    assert labelled.company == "Tidewater"
    assert bare.company == "tidewater"


# --- Ashby --------------------------------------------------------------------


def test_ashby_maps_a_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, "ashby", ASHBY)

    postings = AshbySource().fetch(BoardRef("ashby", "harborlight"))

    assert len(postings) == 1
    posting = postings[0]
    assert posting.title == "Data Engineer"
    assert posting.location == "Remote - European Union"
    assert posting.description_text == "Own the warehouse."


def test_ashby_skips_an_unlisted_posting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A posting Ashby returns but does not publish is one nobody can apply to.

    Importing it would put a job in front of the user that was never on the
    board.
    """
    stub(monkeypatch, "ashby", ASHBY)

    titles = [p.title for p in AshbySource().fetch(BoardRef("ashby", "harborlight"))]

    assert titles == ["Data Engineer"]


def test_ashby_keeps_a_posting_that_does_not_say(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent is not `false`.

    A board that stopped sending the field should not silently return nothing.
    """
    row = {key: value for key, value in ASHBY["jobs"][0].items() if key != "isListed"}
    stub(monkeypatch, "ashby", {"jobs": [row]})

    assert len(AshbySource().fetch(BoardRef("ashby", "harborlight"))) == 1


def test_ashby_does_not_merge_secondary_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The posting names one place. Concatenating the others would invent a
    place the posting does not claim the role is."""
    stub(monkeypatch, "ashby", ASHBY)

    posting = AshbySource().fetch(BoardRef("ashby", "harborlight"))[0]

    assert "Dublin" not in (posting.location or "")


# --- shared behaviour ---------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "payload", "source"),
    [
        ("greenhouse", GREENHOUSE, GreenhouseSource()),
        ("lever", LEVER, LeverSource()),
        ("ashby", ASHBY, AshbySource()),
    ],
)
def test_one_bad_row_costs_that_row_only(
    monkeypatch: pytest.MonkeyPatch, module: str, payload: Any, source: Any
) -> None:
    """Every fixture carries something unusable beside something good."""
    stub(monkeypatch, module, payload)

    assert len(source.fetch(BoardRef(module, "board"))) == 1


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("greenhouse", GreenhouseSource()),
        ("lever", LeverSource()),
        ("ashby", AshbySource()),
    ],
)
def test_a_shape_that_is_not_a_board_is_empty_not_an_error(
    monkeypatch: pytest.MonkeyPatch, module: str, source: Any
) -> None:
    """An endpoint that answered with something else entirely."""
    stub(monkeypatch, module, {"unexpected": True})

    assert list(source.fetch(BoardRef(module, "board"))) == []


@pytest.mark.parametrize(
    "token",
    ["../../etc/passwd", "verdant/jobs", "a?b", "a@evil.example.com", "", "a b"],
)
def test_a_token_cannot_leave_the_path_it_was_given(token: str) -> None:
    """The host is fixed in each provider module, so the token is the only part
    of the URL that comes from configuration.

    Rejected at construction, so there is no way to reach a provider with one
    nobody checked.
    """
    with pytest.raises(InvalidBoard):
        BoardRef("greenhouse", token)
