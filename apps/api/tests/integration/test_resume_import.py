"""Resume import end to end, against a real database.

Upload, extract, parse, review, confirm — with a real PostgreSQL schema built
by the real migrations, a real PDF, and a fake model provider. The only things
substituted are the network boundaries: object storage, the queue, and the LLM.

What these tests are really protecting is stated in ``GOAL.md``: a failure must
never destroy user work, and AI output must never become verified career data
without an explicit human decision.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jip_ai import AIError, AIFailureCode, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.api.dependencies import get_dispatcher, get_storage
from jip_api.application.processing import jobs as jobs_uc
from jip_api.application.resumes import pipeline as pipeline_uc
from jip_api.domain.documents.models import DocumentStatus, SourceDocument
from jip_api.domain.processing.models import ProcessingJob, ProcessingJobStatus
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.extraction.ocr import OcrPage, OcrResult
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.document_fixtures import RESUME_LINES, pdf_bytes, pdf_without_text_layer
from tests.integration.resume_fixtures import InMemoryStorage, RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/resumes"
ALICE = "user_alice"
BOB = "user_bob"

PDF_TYPE = "application/pdf"

PARSE_RESPONSE: dict[str, Any] = {
    "skills": [
        {
            "name": "Python",
            "category": "LANGUAGE",
            "confidence": 95,
            "source_text": "Python, FastAPI",
        },
        {"name": "FastAPI", "category": "FRAMEWORK", "confidence": 92, "source_text": "FastAPI"},
    ],
    "experiences": [
        {
            "company": "Verdant Logistics",
            "title": "Junior Backend Engineer",
            "employment_type": "FULL_TIME",
            "start_date": "2023-03",
            "is_current": True,
            "confidence": 96,
            "source_text": "Junior Backend Engineer, Verdant Logistics",
            "achievements": [
                {
                    "text": "Built REST endpoints in FastAPI for the shipment tracking service.",
                    "confidence": 93,
                    "source_text": "Built REST endpoints in FastAPI",
                }
            ],
        }
    ],
    "projects": [
        {
            "name": "ledgerline",
            "project_type": "PERSONAL",
            "confidence": 90,
            "technologies": [{"name": "Python", "confidence": 92}],
        }
    ],
    "education": [
        {
            "institution": "University of Lisbon",
            "degree": "BSc",
            "field_of_study": "Computer Science",
            "start_date": "2019",
            "end_date": "2022",
            "confidence": 94,
            "source_text": "BSc Computer Science, University of Lisbon, 2019 - 2022",
        }
    ],
}


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
    storage: InMemoryStorage,
    dispatcher: RecordingDispatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    with serve_jwks(factory) as jwks_url:
        monkeypatch.setenv("JIP_DATABASE_URL", clean_database_url)
        monkeypatch.setenv("JIP_AUTH_ISSUER", ISSUER)
        monkeypatch.setenv("JIP_AUTH_JWKS_URL", jwks_url)
        monkeypatch.setenv("JIP_AUTH_AUTHORIZED_PARTIES", AUTHORIZED_PARTY)

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()

        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", clean_database_url)
        command.upgrade(config, "head")

        from jip_api.main import create_app

        app = create_app()
        # Storage and the queue are the two network boundaries this suite
        # substitutes; everything else is the production wiring.
        app.dependency_overrides[get_storage] = lambda: storage
        app.dependency_overrides[get_dispatcher] = lambda: dispatcher

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory, subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def upload(
    client: TestClient,
    factory: TokenFactory,
    subject: str = ALICE,
    *,
    data: bytes | None = None,
    filename: str = "resume.pdf",
    content_type: str = PDF_TYPE,
) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/import",
        headers=auth(factory, subject),
        files={"file": (filename, data or pdf_bytes(RESUME_LINES), content_type)},
    )
    assert response.status_code == 202, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


def parse_sections(response: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """`PARSE_RESPONSE` split the way the parser now asks for it.

    DEV-017 made a resume parse four calls, one per section, so a fake provider
    needs four responses where it needed one. `FakeLLMProvider` replays in
    request order, which is `RESUME_SECTION_PROMPTS`.
    """
    source = PARSE_RESPONSE if response is None else response
    return [
        {"skills": source.get("skills", [])},
        {"experiences": source.get("experiences", [])},
        {"projects": source.get("projects", [])},
        {"education": source.get("education", [])},
    ]


def run_pipeline(
    storage: InMemoryStorage,
    job_id: str,
    responses: list[Any] | None = None,
    ocr: Any = None,
) -> Any:
    """Drive the pipeline directly, as the worker would.

    A separate session, because the worker gets one — which is also what makes
    the commit-per-step behaviour observable.

    `ocr` is what `run_resume_import` resolves from `get_ocr_engine()`. Left as
    `None` here by default, which is exactly what a machine without Tesseract
    installed gets, and therefore what most of these tests should exercise.
    """
    provider = FakeLLMProvider(responses if responses is not None else parse_sections())
    router = build_router(
        resume_parse_model="test-model",
        resume_parse_max_output_tokens=8000,
        resume_parse_effort=None,
    )
    session = new_session()
    try:
        job = session.get(ProcessingJob, uuid.UUID(job_id))
        assert job is not None
        try:
            return pipeline_uc.run_import(
                session,
                storage,
                provider,
                router,
                job=job,
                max_input_chars=60_000,
                max_attempts=1,
                ocr=ocr,
            )
        except AIError as error:
            session.rollback()
            jobs_uc.mark_failed(session, job, error)
            session.commit()
            raise
    finally:
        session.close()


# --- upload -------------------------------------------------------------------


def test_import_returns_the_documented_async_contract(
    client: TestClient, factory: TokenFactory
) -> None:
    data = upload(client, factory)

    assert set(data) == {"source_document_id", "processing_job_id", "status"}
    assert data["status"] == ProcessingJobStatus.PENDING


def test_the_file_is_stored_outside_the_database(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """docs/04-system-architecture.md: uploaded files never go in PostgreSQL."""
    data = upload(client, factory)

    assert len(storage.objects) == 1
    key = next(iter(storage.objects))
    assert data["source_document_id"] in key
    assert key.startswith("users/")


def test_the_work_is_queued(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    data = upload(client, factory)

    assert dispatcher.calls == [
        ("jip_worker.tasks.resumes.run_resume_import", (data["processing_job_id"],))
    ]


@pytest.mark.parametrize(
    ("filename", "content_type", "data"),
    [
        ("resume.txt", "text/plain", b"just text, plenty of it, over and over" * 5),
        ("resume.pdf", PDF_TYPE, b"MZ\x90\x00 an executable renamed to .pdf" * 5),
        ("resume.exe", PDF_TYPE, b"%PDF-1.7 with the wrong extension" * 5),
    ],
    ids=["unsupported-type", "content-mismatch", "extension-mismatch"],
)
def test_unsupported_uploads_are_rejected(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    filename: str,
    content_type: str,
    data: bytes,
) -> None:
    response = client.post(
        f"{BASE}/import",
        headers=auth(factory, ALICE),
        files={"file": (filename, data, content_type)},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "UPLOAD_REJECTED"
    assert storage.objects == {}, "a rejected upload must not be stored"


def test_a_queue_outage_keeps_the_upload(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    dispatcher: RecordingDispatcher,
) -> None:
    """GOAL.md: failures must not destroy user work.

    The file is stored and the job records a retriable failure, so the user can
    try again without re-uploading.
    """
    dispatcher.fail = True

    data = upload(client, factory)

    assert len(storage.objects) == 1
    job = client.get(
        f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE)
    ).json()["data"]
    assert job["status"] == ProcessingJobStatus.FAILED
    assert job["is_retriable"] is True


def test_supported_formats_are_published(client: TestClient) -> None:
    """Served from the same table upload validation uses, so the browser's
    accept filter cannot drift from what the API takes."""
    formats = client.get(f"{BASE}/supported-formats").json()["data"]

    assert PDF_TYPE in formats
    assert len(formats) == 2


# --- the pipeline -------------------------------------------------------------


def test_the_pipeline_extracts_parses_and_stores(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    data = upload(client, factory)

    result = run_pipeline(storage, data["processing_job_id"])

    # Top-level candidates only: two skills, one role, one project, one degree.
    # The achievement and the project technology hang off their parents.
    assert result.candidate_count == 5
    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]

    assert review["document"]["status"] == "PARSED"
    assert review["job"]["status"] == ProcessingJobStatus.COMPLETED
    assert review["extraction"]["version"] == 1
    # The set of four, since DEV-017. Each `ai_runs` row still names the
    # section prompt that produced it — asserted in `test_ai_runs_are_recorded`.
    assert review["extraction"]["prompt_version"] == "resume_sections_v1"


class FakeOcrEngine:
    """Reads whatever it was told to read, and remembers being asked.

    Tesseract is a system binary and is not installed on most machines that run
    this suite, so the real one cannot be a condition of the chain being
    tested. What matters at this level is not how well a page is recognised —
    `tests/accuracy` measures that against the real engine — but that the
    string it produces travels the whole way: through the resume gate, through
    the parser, into candidates, onto the review payload, and that where it
    came from is recorded beside it.
    """

    name = "fake"

    def __init__(self, text: str, confidence: float = 91.5) -> None:
        self.text = text
        self.confidence = confidence
        self.pages: list[bytes] = []

    def read(self, pages: Any, *, languages: str) -> OcrResult:
        # Drained on purpose: the iterable is the rasteriser, and a test that
        # never consumed it would pass without a page ever being rendered.
        self.pages = list(pages)
        return OcrResult(pages=(OcrPage(text=self.text, confidence=self.confidence),))


def test_a_scanned_resume_reaches_the_review_screen(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """Phase 14, acceptance criterion 1, and the only test that covers the chain.

    Everything else about OCR is measured in isolation: the engine reads a page,
    the metrics say how well. None of it establishes that a document with no
    text layer survives upload, storage, the queue, extraction, the resume gate,
    the parser and the review endpoint — which is the thing a user actually
    does.

    Nothing in the pipeline treats OCR text differently once it exists; that was
    the point of putting the whole feature behind one branch. This is the test
    that says so out loud, and would fail if a later change stopped threading
    the engine through.
    """
    data = upload(client, factory, data=pdf_without_text_layer())
    engine = FakeOcrEngine("\n".join(RESUME_LINES))

    result = run_pipeline(storage, data["processing_job_id"], ocr=engine)

    # The pages were really rendered rather than an empty generator handed over.
    assert engine.pages, "the rasteriser was never drained"
    assert engine.pages[0].startswith(b"\x89PNG")

    # And the same five candidates a text-layer resume produces.
    assert result.candidate_count == 5

    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]

    assert review["document"]["status"] == "PARSED"
    assert review["job"]["status"] == ProcessingJobStatus.COMPLETED
    assert review["extraction"]["items"], "a review screen with nothing on it"


def test_the_review_payload_says_the_text_came_from_a_scan(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """Provenance survives the whole journey, not just the extraction step.

    Slice 2 wrote these two columns and slice 4 decided what the screen does
    with them. This is the join between: the value the pipeline stored is the value
    the endpoint serves, so the review screen is deciding on a fact rather than
    on a default.
    """
    data = upload(client, factory, data=pdf_without_text_layer())

    run_pipeline(
        storage,
        data["processing_job_id"],
        ocr=FakeOcrEngine("\n".join(RESUME_LINES), confidence=88.25),
    )

    document = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]["document"]

    assert document["text_source"] == "OCR"
    assert document["ocr_confidence"] == 88.25


def test_a_text_layer_is_recorded_as_one_even_with_an_engine_available(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """The other half, without which the test above proves only that a column exists.

    A confidence of null rather than 100 is the distinction the column was added
    for: a text layer has no confidence, it is not confident. Anything reading
    this later to ask "which documents were we unsure about" gets a different
    and correct answer because of it.
    """
    data = upload(client, factory)
    engine = FakeOcrEngine("\n".join(RESUME_LINES))

    run_pipeline(storage, data["processing_job_id"], ocr=engine)

    document = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]["document"]

    assert engine.pages == [], "a readable text layer must never reach the engine"
    assert document["text_source"] == "TEXT_LAYER"
    assert document["ocr_confidence"] is None


def test_every_candidate_type_is_reviewable(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """All six approve destinations must reach the review screen."""
    data = upload(client, factory)
    run_pipeline(storage, data["processing_job_id"])

    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]
    types = {item["candidate_type"] for item in review["extraction"]["items"]}

    assert types == {
        "SKILL",
        "EXPERIENCE",
        "EXPERIENCE_ACHIEVEMENT",
        "PROJECT",
        "PROJECT_SKILL",
        "EDUCATION",
    }


def test_children_know_their_parent(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    data = upload(client, factory)
    run_pipeline(storage, data["processing_job_id"])

    items = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]["extraction"]["items"]

    achievement = next(i for i in items if i["candidate_type"] == "EXPERIENCE_ACHIEVEMENT")
    experience = next(i for i in items if i["candidate_type"] == "EXPERIENCE")

    assert achievement["parent_item_id"] == experience["id"]


def test_ai_runs_are_recorded(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage, clean_database_url: str
) -> None:
    """docs/09-mvp-roadmap.md gates AI features on a run trace.

    One row per section since DEV-017, each naming its own prompt. That is what
    lets the extraction record the set without losing which template produced
    which half of the answer.
    """
    data = upload(client, factory)
    run_pipeline(storage, data["processing_job_id"])

    engine = sqlalchemy.create_engine(clean_database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                sqlalchemy.text(
                    "SELECT operation, provider, model, prompt_version, status, input_hash "
                    "FROM ai_runs ORDER BY created_at, prompt_version"
                )
            ).all()
    finally:
        engine.dispose()

    assert {row.prompt_version for row in rows} == {
        "resume_skills_v1",
        "resume_experiences_v1",
        "resume_projects_v1",
        "resume_education_v1",
    }
    assert all(row.operation == "RESUME_PARSE" for row in rows)
    assert all(row.provider == "fake" for row in rows)
    assert all(row.status == "SUCCEEDED" for row in rows)

    # Each section is hashed over its own prompt and rendering, so two sections
    # of one document are not mistaken for a repeat of the same call.
    assert len({row.input_hash for row in rows}) == len(rows)

    row = rows[0]
    assert len(row.input_hash) == 64


def test_review_answers_while_processing_is_still_running(
    client: TestClient, factory: TokenFactory
) -> None:
    """The frontend polls this. A 404 until ready is indistinguishable from a
    document that does not exist."""
    data = upload(client, factory)

    response = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    )

    assert response.status_code == 200
    assert response.json()["data"]["extraction"] is None


# --- failure and retry --------------------------------------------------------


def test_extraction_failure_preserves_the_document(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    data = upload(client, factory, data=pdf_without_text_layer())

    with pytest.raises(AIError) as caught:
        run_pipeline(storage, data["processing_job_id"])
    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE

    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]

    assert review["document"]["status"] == "FAILED"
    assert "scan" in review["document"]["extraction_error"]
    assert len(storage.objects) == 1, "the uploaded file must survive a failed parse"


def test_a_document_with_no_text_is_not_offered_a_retry(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """Retrying will not put a text layer into a scan."""
    data = upload(client, factory, data=pdf_without_text_layer())
    with pytest.raises(AIError):
        run_pipeline(storage, data["processing_job_id"])

    job = client.get(
        f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE)
    ).json()["data"]

    assert job["status"] == ProcessingJobStatus.FAILED
    assert job["is_retriable"] is False

    retry = client.post(
        f"/api/v1/processing-jobs/{data['processing_job_id']}/retry", headers=auth(factory, ALICE)
    )
    assert retry.status_code == 409


# --- the dead-letter view (Phase 11) -------------------------------------------


def test_a_failure_can_be_found_without_knowing_its_id(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """The half of retry flows Phase 11 carried as missing.

    Until this endpoint existed a failed job was reachable only by its id, so
    the only person who ever saw one was somebody already watching the screen it
    belonged to at the moment it broke.
    """
    data = upload(client, factory, data=pdf_without_text_layer())
    with pytest.raises(AIError):
        run_pipeline(storage, data["processing_job_id"])

    failures = client.get("/api/v1/processing-jobs/failures", headers=auth(factory, ALICE)).json()[
        "data"
    ]

    assert [row["id"] for row in failures] == [data["processing_job_id"]]


def test_a_permanent_failure_is_reported_as_finished(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """A PDF with no text layer stays a PDF with no text layer.

    The row appears in the list and is marked as over, so a screen can show it
    without offering a button that would 409.
    """
    data = upload(client, factory, data=pdf_without_text_layer())
    with pytest.raises(AIError):
        run_pipeline(storage, data["processing_job_id"])

    row = client.get("/api/v1/processing-jobs/failures", headers=auth(factory, ALICE)).json()[
        "data"
    ][0]

    assert row["is_dead"] is True
    assert row["can_be_retried"] is False


def test_a_failure_carries_the_name_of_what_it_was_reading(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """A UUID is not something a person can act on."""
    data = upload(client, factory, data=pdf_without_text_layer())
    with pytest.raises(AIError):
        run_pipeline(storage, data["processing_job_id"])

    row = client.get("/api/v1/processing-jobs/failures", headers=auth(factory, ALICE)).json()[
        "data"
    ][0]

    assert row["entity_label"]
    assert row["entity_label"].endswith(".pdf")


def test_an_account_with_nothing_broken_gets_an_empty_list(
    client: TestClient, factory: TokenFactory
) -> None:
    """Not an error, and not a 404. Nothing has failed."""
    response = client.get("/api/v1/processing-jobs/failures", headers=auth(factory, ALICE))

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_failures_are_scoped_to_the_caller(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    data = upload(client, factory, data=pdf_without_text_layer())
    with pytest.raises(AIError):
        run_pipeline(storage, data["processing_job_id"])

    assert (
        client.get("/api/v1/processing-jobs/failures", headers=auth(factory, BOB)).json()["data"]
        == []
    )


def test_the_failures_route_rejects_an_anonymous_caller(client: TestClient) -> None:
    assert client.get("/api/v1/processing-jobs/failures").status_code == 401


def test_a_parse_failure_is_retriable_and_reuses_the_extracted_text(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    dispatcher: RecordingDispatcher,
) -> None:
    """A retry resumes from the step that failed.

    Re-extracting text that was already recovered is work a retry should not
    have to repeat, and it is what makes an AI outage cheap to recover from.
    """
    data = upload(client, factory)

    with pytest.raises(AIError):
        run_pipeline(
            storage,
            data["processing_job_id"],
            responses=[AIError(AIFailureCode.PROVIDER_ERROR, "provider down")],
        )

    job = client.get(
        f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE)
    ).json()["data"]
    assert job["is_retriable"] is True

    retry = client.post(
        f"/api/v1/processing-jobs/{data['processing_job_id']}/retry", headers=auth(factory, ALICE)
    )
    assert retry.status_code == 200
    assert retry.json()["data"]["status"] == ProcessingJobStatus.PENDING
    assert len(dispatcher.calls) == 2

    # Delete the stored object: if the retry needed to download again it would
    # now fail, which proves the cached text is what was used.
    storage.objects.clear()
    run_pipeline(storage, data["processing_job_id"])

    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]
    assert review["extraction"] is not None


def test_a_second_parse_creates_a_new_version(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """docs/03-domain-model.md: extraction output is versioned, not overwritten.

    Version 1 stays exactly as the user reviewed it.
    """
    data = upload(client, factory)
    run_pipeline(storage, data["processing_job_id"])

    session = new_session()
    try:
        job = session.get(ProcessingJob, uuid.UUID(data["processing_job_id"]))
        assert job is not None
        job.status = ProcessingJobStatus.PENDING
        session.commit()
    finally:
        session.close()

    run_pipeline(storage, data["processing_job_id"])

    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]
    assert review["extraction"]["version"] == 2


# --- signed access ------------------------------------------------------------


def test_the_download_url_is_signed_and_temporary(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    data = upload(client, factory)

    payload = client.get(
        f"{BASE}/imports/{data['source_document_id']}/file", headers=auth(factory, ALICE)
    ).json()["data"]

    assert "X-Amz-Signature" in payload["url"]
    assert payload["expires_in_seconds"] > 0
    assert storage.signed[0][1] == payload["expires_in_seconds"]


# --- ownership ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/extraction", "/file", "/confirm"],
)
def test_another_user_cannot_reach_the_document(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage, path: str
) -> None:
    """docs/11-engineering-standards.md, security tests: user A must not be able
    to download user B's resume."""
    data = upload(client, factory, ALICE)
    run_pipeline(storage, data["processing_job_id"])

    url = f"{BASE}/imports/{data['source_document_id']}{path}"
    if path == "/confirm":
        body = {"decisions": [{"item_id": str(uuid.uuid4()), "action": "IGNORE"}]}
        response = client.post(url, headers=auth(factory, BOB), json=body)
    else:
        response = client.get(url, headers=auth(factory, BOB))

    assert response.status_code == 404


def test_another_user_cannot_read_or_retry_the_job(
    client: TestClient, factory: TokenFactory
) -> None:
    data = upload(client, factory, ALICE)
    job_url = f"/api/v1/processing-jobs/{data['processing_job_id']}"

    assert client.get(job_url, headers=auth(factory, BOB)).status_code == 404
    assert client.post(f"{job_url}/retry", headers=auth(factory, BOB)).status_code == 404


def test_the_import_list_is_scoped_to_the_caller(client: TestClient, factory: TokenFactory) -> None:
    upload(client, factory, ALICE)

    assert len(client.get(f"{BASE}/imports", headers=auth(factory, ALICE)).json()["data"]) == 1
    assert client.get(f"{BASE}/imports", headers=auth(factory, BOB)).json()["data"] == []


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get(f"{BASE}/imports").status_code == 401
    assert (
        client.post(
            f"{BASE}/import", files={"file": ("r.pdf", pdf_bytes(RESUME_LINES), PDF_TYPE)}
        ).status_code
        == 401
    )


# --- the worker task ----------------------------------------------------------
#
# The task itself, not just the pipeline underneath it. Its whole job is to turn
# any outcome into a recorded job state: an exception escaping here would land
# in RQ's failed registry, where the user polling the job never sees it.


def worker_task(
    monkeypatch: pytest.MonkeyPatch,
    storage: InMemoryStorage,
    responses: list[Any],
) -> Any:
    """Run the worker task with its infrastructure factories substituted."""
    from jip_worker.tasks import resumes as worker

    monkeypatch.setattr(worker, "get_object_storage", lambda: storage)
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeLLMProvider(responses))
    monkeypatch.setattr(
        worker,
        "get_model_router",
        lambda: build_router(
            resume_parse_model="test-model",
            resume_parse_max_output_tokens=8000,
            resume_parse_effort=None,
        ),
    )
    return worker.run_resume_import


def test_the_worker_task_completes_an_import(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = upload(client, factory)

    result = worker_task(monkeypatch, storage, parse_sections())(data["processing_job_id"])

    assert result["status"] == "COMPLETED"
    assert result["candidates"] == 5


def test_the_worker_task_records_a_failure_instead_of_raising(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = upload(client, factory)
    error = AIError(AIFailureCode.RATE_LIMIT, "slow down")

    result = worker_task(monkeypatch, storage, [error, error, error])(data["processing_job_id"])

    assert result["status"] == "FAILED"
    assert result["error_code"] == "RATE_LIMIT"

    job = client.get(
        f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE)
    ).json()["data"]
    assert job["status"] == ProcessingJobStatus.FAILED
    assert job["is_retriable"] is True


def test_the_worker_task_survives_an_unexpected_error(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bug must still land on the job, with a generic message.

    docs/10-api-contracts.md keeps internal exception detail out of client
    responses, so the user sees that it failed, not how.
    """
    data = upload(client, factory)
    task = worker_task(monkeypatch, storage, [])

    from jip_worker.tasks import resumes as worker

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("a genuine bug with sensitive/path/detail")

    monkeypatch.setattr(worker, "run_import", explode)
    result = task(data["processing_job_id"])

    assert result["status"] == "FAILED"
    job = client.get(
        f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE)
    ).json()["data"]
    assert "sensitive/path/detail" not in str(job["error_message"])


def test_a_duplicate_delivery_does_not_reprocess(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queues deliver at least once.

    Doing the work again would mint a second extraction version and a second
    review screen for one upload.
    """
    data = upload(client, factory)
    task = worker_task(monkeypatch, storage, parse_sections())

    assert task(data["processing_job_id"])["status"] == "COMPLETED"
    # No second response is queued: the fake would raise if it were called.
    assert task(data["processing_job_id"])["status"] == ProcessingJobStatus.COMPLETED

    review = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory, ALICE)
    ).json()["data"]
    assert review["extraction"]["version"] == 1


def test_a_missing_job_is_reported_not_raised(
    storage: InMemoryStorage, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    task = worker_task(monkeypatch, storage, [])

    assert task(str(uuid.uuid4()))["status"] == "MISSING"


# --- stalled jobs ---------------------------------------------------------------


def _age_job(job_id: str, seconds: int) -> None:
    """Backdate a job so the reaper's threshold is already past.

    Faster and more honest than sleeping: what is under test is the decision,
    not the clock.
    """
    session = new_session()
    try:
        job = session.get(ProcessingJob, uuid.UUID(job_id))
        assert job is not None
        job.created_at = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=seconds)
        session.commit()
    finally:
        session.close()


def test_a_job_that_never_started_becomes_actionable(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """DEV-013. The worker died before writing a status, so the row sat PENDING
    with no retry, no cancel, and nothing to age it out — "Waiting to start"
    forever, recoverable only by deleting the row in SQL.
    """
    data = upload(client, factory)
    url = f"/api/v1/processing-jobs/{data['processing_job_id']}"

    assert client.get(url, headers=auth(factory, ALICE)).json()["data"]["status"] == "PENDING"

    _age_job(data["processing_job_id"], 3600)
    job = client.get(url, headers=auth(factory, ALICE)).json()["data"]

    assert job["status"] == ProcessingJobStatus.FAILED
    assert job["error_code"] == "STALLED"
    assert job["is_retriable"] is True
    assert "Nothing was lost" in job["error_message"]


def test_a_reaped_job_can_actually_be_retried(
    client: TestClient,
    factory: TokenFactory,
    storage: InMemoryStorage,
    dispatcher: RecordingDispatcher,
) -> None:
    """The point of the whole issue. A retry that returns 200 without enqueuing
    anything would put the job straight back into the state it was rescued
    from."""
    data = upload(client, factory)
    _age_job(data["processing_job_id"], 3600)
    client.get(f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE))

    before = len(dispatcher.calls)
    response = client.post(
        f"/api/v1/processing-jobs/{data['processing_job_id']}/retry", headers=auth(factory, ALICE)
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == ProcessingJobStatus.PENDING
    assert len(dispatcher.calls) == before + 1, "the retry enqueued nothing"


def test_a_recently_queued_job_is_left_alone(client: TestClient, factory: TokenFactory) -> None:
    """Queued behind other work is not the same as dead."""
    data = upload(client, factory)

    job = client.get(
        f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE)
    ).json()["data"]

    assert job["status"] == "PENDING"


def test_reaping_releases_the_document(
    client: TestClient, factory: TokenFactory, storage: InMemoryStorage
) -> None:
    """Otherwise the job reports failed while its document still says it is
    being worked on, and the screen shows a spinner beside a retry button."""
    data = upload(client, factory)
    _age_job(data["processing_job_id"], 3600)

    client.get(f"/api/v1/processing-jobs/{data['processing_job_id']}", headers=auth(factory, ALICE))

    session = new_session()
    try:
        document = session.get(SourceDocument, uuid.UUID(data["source_document_id"]))
        assert document is not None
        assert document.status is DocumentStatus.FAILED
    finally:
        session.close()
