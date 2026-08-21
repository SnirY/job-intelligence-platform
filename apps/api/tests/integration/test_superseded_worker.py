"""A worker that finishes after the reaper has given up on it.

`active-task.md` recorded the gap as *"nothing recovers a job whose worker died
mid-write"*. Reading the pipelines says that half is already safe: both wrap the
persist and the status change in one terminal commit, so a process that dies
anywhere inside writes nothing at all.

The case that was not safe is the one where the worker does **not** die.

The reaper decides about a worker it cannot see. A hung process and a dead one
look identical from outside, so the threshold has to choose — and when it
chooses wrong, the worker eventually wakes up and finishes. `mark_completed`
used to assign COMPLETED unconditionally, which meant that worker would write
its results over a failure the user had already been shown, and if they had
retried on the strength of it the posting would be analysed twice.

These need a real database because the fence is a conditional UPDATE, and the
thing being tested is what two sessions do to one row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jip_ai import ModelRouter, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.api.dependencies import get_dispatcher
from jip_api.application.jobs.analysis_pipeline import run_analysis
from jip_api.application.processing import jobs as jobs_uc
from jip_api.domain.jobs.analysis import JobAnalysis
from jip_api.domain.jobs.models import Job, JobProcessingStatus
from jip_api.domain.processing.models import ProcessingJob, ProcessingJobStatus
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
JOBS = "/api/v1/jobs"
ALICE = "user_alice"

POSTING = (
    "Senior Backend Engineer at Verdant Logistics.\n\n"
    "Requirements:\n"
    "- 5+ years of backend engineering experience\n"
    "- Strong Python\n"
)

PARSE_RESPONSE: dict[str, Any] = {
    "summary": "Senior backend role.",
    "requirements": [
        {
            "normalized_text": "Python",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "CORE",
            "explicitness": "EXPLICIT",
            "source_text": "Strong Python",
            "confidence": 95,
            "skill_name": "Python",
        },
    ],
    "responsibilities": [],
    "years_experience_min": 5,
}

ANALYSIS_RESPONSE: dict[str, Any] = {
    "role_family": "BACKEND",
    "role_family_confidence": 92,
    "role_family_reasoning": "Server-side services in Python.",
    "seniority": "SENIOR",
    "seniority_confidence": 88,
    "seniority_reasoning": "Asks for five years.",
    "summary": "A senior backend role.",
}


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
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
        app.dependency_overrides[get_dispatcher] = lambda: dispatcher

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=ALICE)}"}


def queued_analysis(client: TestClient, factory: TokenFactory) -> tuple[str, str]:
    """A job with an analysis enqueued but not yet run."""
    created = client.post(
        JOBS,
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": POSTING,
        },
    )
    assert created.status_code == 201, created.text
    job_id: str = created.json()["data"]["id"]

    started = client.post(f"{JOBS}/{job_id}/analysis", headers=auth(factory))
    assert started.status_code == 202, started.text
    return job_id, started.json()["data"]["processing_job_id"]


def router() -> ModelRouter:
    return build_router(
        resume_parse_model="fake-model",
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )


class ReapingProvider(FakeLLMProvider):
    """A provider that lets the reaper act while the worker is mid-run.

    The stall the reaper is guessing about happens *inside* a model call, so
    that is where this simulates it: after the last response is handed back and
    before the pipeline reaches its terminal commit, a separate session marks
    the job failed exactly as `reap_if_stalled` would.
    """

    def __init__(self, responses: list[dict[str, Any]], *, reap: uuid.UUID) -> None:
        super().__init__(responses)
        self._reap = reap
        self._calls = 0

    def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
        result = super().generate_structured(*args, **kwargs)
        self._calls += 1
        if self._calls == 2:
            other = new_session()
            try:
                row = other.get(ProcessingJob, self._reap)
                assert row is not None
                row.status = ProcessingJobStatus.FAILED
                row.error_code = "STALLED"
                row.is_retriable = True
                other.commit()
            finally:
                other.close()
        return result


def test_a_worker_cannot_complete_a_job_the_reaper_already_failed(
    client: TestClient, factory: TokenFactory
) -> None:
    """The fence, end to end.

    Without it the row reads COMPLETED after the user has been told it failed,
    and the analysis lands attached to a job that says it never ran.
    """
    _job_id, processing_id = queued_analysis(client, factory)

    session = new_session()
    try:
        processing = session.get(ProcessingJob, uuid.UUID(processing_id))
        assert processing is not None

        with pytest.raises(jobs_uc.JobSupersededError):
            run_analysis(
                session,
                ReapingProvider([PARSE_RESPONSE, ANALYSIS_RESPONSE], reap=uuid.UUID(processing_id)),
                router(),
                job=processing,
                max_input_chars=60_000,
                max_attempts=1,
            )
        session.rollback()
    finally:
        session.close()

    check = new_session()
    try:
        row = check.get(ProcessingJob, uuid.UUID(processing_id))
        assert row is not None
        assert row.status is ProcessingJobStatus.FAILED
        assert row.error_code == "STALLED"
    finally:
        check.close()


def test_the_discarded_work_is_not_left_behind(client: TestClient, factory: TokenFactory) -> None:
    """Nothing half-written survives.

    The analysis, its requirements and the job's ANALYZED status are all inside
    the one commit the fence prevents, so refusing it has to leave the database
    exactly as it was.
    """
    job_id, processing_id = queued_analysis(client, factory)

    session = new_session()
    try:
        processing = session.get(ProcessingJob, uuid.UUID(processing_id))
        assert processing is not None
        with pytest.raises(jobs_uc.JobSupersededError):
            run_analysis(
                session,
                ReapingProvider([PARSE_RESPONSE, ANALYSIS_RESPONSE], reap=uuid.UUID(processing_id)),
                router(),
                job=processing,
                max_input_chars=60_000,
                max_attempts=1,
            )
        session.rollback()
    finally:
        session.close()

    check = new_session()
    try:
        analyses = check.query(JobAnalysis).filter(JobAnalysis.job_id == uuid.UUID(job_id)).all()
        assert analyses == []

        target = check.get(Job, uuid.UUID(job_id))
        assert target is not None
        assert target.status is not JobProcessingStatus.ANALYZED
    finally:
        check.close()


def test_the_screen_still_offers_a_way_forward(client: TestClient, factory: TokenFactory) -> None:
    """A reaped job is retriable, and refusing the late worker must not change
    that. Otherwise the fence would trade a wrong success for a dead end."""
    _job_id, processing_id = queued_analysis(client, factory)

    session = new_session()
    try:
        processing = session.get(ProcessingJob, uuid.UUID(processing_id))
        assert processing is not None
        with pytest.raises(jobs_uc.JobSupersededError):
            run_analysis(
                session,
                ReapingProvider([PARSE_RESPONSE, ANALYSIS_RESPONSE], reap=uuid.UUID(processing_id)),
                router(),
                job=processing,
                max_input_chars=60_000,
                max_attempts=1,
            )
        session.rollback()
    finally:
        session.close()

    response = client.get(f"/api/v1/processing-jobs/{processing_id}", headers=auth(factory))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "FAILED"
    assert data["is_retriable"] is True


def test_an_uninterrupted_run_still_completes(client: TestClient, factory: TokenFactory) -> None:
    """The fence must not cost the ordinary path anything.

    Worth its own test because a conditional write that never matches is a
    silent way to break every job at once.
    """
    job_id, processing_id = queued_analysis(client, factory)

    session = new_session()
    try:
        processing = session.get(ProcessingJob, uuid.UUID(processing_id))
        assert processing is not None
        run_analysis(
            session,
            FakeLLMProvider([PARSE_RESPONSE, ANALYSIS_RESPONSE]),
            router(),
            job=processing,
            max_input_chars=60_000,
            max_attempts=1,
        )
    finally:
        session.close()

    check = new_session()
    try:
        row = check.get(ProcessingJob, uuid.UUID(processing_id))
        assert row is not None
        assert row.status is ProcessingJobStatus.COMPLETED
        assert row.finished_at is not None

        target = check.get(Job, uuid.UUID(job_id))
        assert target is not None
        assert target.status is JobProcessingStatus.ANALYZED
    finally:
        check.close()
