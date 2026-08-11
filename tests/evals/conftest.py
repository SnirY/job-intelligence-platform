"""Shared fixtures for the evaluation suite.

Two modes over one set of expectations: offline replays a recorded response
through the fake provider, live sends the resume to the configured provider.
The assertions are the same either way, which is what makes the offline run a
real check rather than a rehearsal.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jip_ai import LLMProvider, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.documents.upload import PDF
from jip_api.application.resumes.parsing import ResumeParseOutcome, ResumeParsingService

FIXTURE_DIR = Path(__file__).parent / "fixtures"
RUN_LIVE = os.environ.get("JIP_RUN_AI_EVALS") == "1"


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One resume and what a correct parse of it must contain."""

    path: Path
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def resume_text(self) -> str:
        return str(self.data["resume_text"])

    @property
    def recorded_output(self) -> dict[str, Any]:
        output: dict[str, Any] = self.data["recorded_output"]
        return output

    @property
    def recorded_sections(self) -> list[dict[str, Any]]:
        """The recorded answer split the way the parser now asks for it.

        DEV-017 made resume parsing four calls, one per section, so the fake
        provider needs four responses where it needed one. Derived from the
        single recorded output rather than re-recorded: the fixtures describe
        what a model said about a resume, and that is unchanged by which call
        each half of it arrived in. Re-recording would have meant regenerating
        six fixtures to test a plumbing change.

        The order matches `RESUME_SECTION_PROMPTS`, because `FakeLLMProvider`
        replays in sequence and nothing else pairs a response with its request.
        """
        output = self.recorded_output
        return [
            {"skills": output.get("skills", [])},
            {"experiences": output.get("experiences", [])},
            {"projects": output.get("projects", [])},
            {"education": output.get("education", [])},
        ]

    def expect(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def load_cases() -> list[EvalCase]:
    """Every fixture on disk, sorted so failures are reported in a stable order."""
    return [
        EvalCase(path=path, data=json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(FIXTURE_DIR.glob("*.json"))
    ]


CASES = load_cases()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parameterise over whichever fixture set a test asks for.

    Two suites, two names. Job evals ask for ``job_case`` and their fixtures
    live in a subdirectory the resume glob above does not reach, so adding one
    cannot silently change what the resume evals run against.
    """
    if "case" in metafunc.fixturenames:
        metafunc.parametrize("case", CASES, ids=[c.path.stem for c in CASES])

    if "job_case" in metafunc.fixturenames:
        from .job_conftest import JOB_CASES

        metafunc.parametrize("job_case", JOB_CASES, ids=[c.path.stem for c in JOB_CASES])


@pytest.fixture(scope="session")
def offline_provider_factory() -> Any:
    """Build a fake provider primed with one fixture's recorded response.

    Four responses since DEV-017, one per section. See `recorded_sections`.
    """

    def build(case: EvalCase) -> FakeLLMProvider:
        return FakeLLMProvider(case.recorded_sections)

    return build


@pytest.fixture(scope="session")
def offline_job_provider_factory() -> Any:
    """Build a fake provider primed with a job fixture's two recorded responses.

    Two, in order, because a job analysis is two calls: the parse and the
    interpretation of it.
    """
    from .job_conftest import JobEvalCase

    def build(case: JobEvalCase) -> FakeLLMProvider:
        return FakeLLMProvider([case.recorded_parse, case.recorded_analysis])

    return build


@pytest.fixture(scope="session")
def live_provider() -> Iterator[LLMProvider]:
    """The configured provider, or a skip.

    ``docs/11-engineering-standards.md`` forbids live model calls in the normal
    suite, so this is opt-in twice over: the marker and the environment
    variable both have to be set.
    """
    if not RUN_LIVE:
        pytest.skip("Set JIP_RUN_AI_EVALS=1 to run evaluations against a live model.")

    from jip_api.infrastructure.ai import build_model_router, build_provider
    from jip_config import get_settings

    settings = get_settings()
    if not settings.ai_configured:
        pytest.skip("JIP_AI_API_KEY is not set.")

    _ = build_model_router(settings)
    yield build_provider(settings)


def parse(
    provider: LLMProvider, case: EvalCase, *, model: str = "eval-model"
) -> ResumeParseOutcome:
    """Run the real parsing service against ``provider``.

    The whole path — prompt rendering, structured parsing, schema validation,
    business validation — not just the model call, because most of what these
    fixtures protect lives in the code around it.
    """
    router = build_router(
        resume_parse_model=model,
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )
    service = ResumeParsingService(provider, router, max_input_chars=60_000, max_attempts=1)
    return service.parse(case.resume_text, content_type=PDF)
