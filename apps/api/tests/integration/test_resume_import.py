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


def run_pipeline(
    storage: InMemoryStorage,
    job_id: str,
    responses: list[Any] | None = None,
) -> Any:
    """Drive the pipeline directly, as the worker would.

    A separate session, because the worker gets one — which is also what makes
    the commit-per-step behaviour observable.
    """
    provider = FakeLLMProvider(responses if responses is not None else [PARSE_RESPONSE])
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
    assert review["extraction"]["prompt_version"] == "resume_parser_v1"


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
    """docs/09-mvp-roadmap.md gates AI features on a run trace."""
    data = upload(client, factory)
    run_pipeline(storage, data["processing_job_id"])

    engine = sqlalchemy.create_engine(clean_database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                sqlalchemy.text(
                    "SELECT operation, provider, model, prompt_version, status, input_hash "
                    "FROM ai_runs"
                )
            ).one()
    finally:
        engine.dispose()

    assert row.operation == "RESUME_PARSE"
    assert row.provider == "fake"
    assert row.prompt_version == "resume_parser_v1"
    assert row.status == "SUCCEEDED"
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

    result = worker_task(monkeypatch, storage, [PARSE_RESPONSE])(data["processing_job_id"])

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
    task = worker_task(monkeypatch, storage, [PARSE_RESPONSE])

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
