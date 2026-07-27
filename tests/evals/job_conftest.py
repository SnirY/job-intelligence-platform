"""Loading and running the job-parsing evaluation fixtures.

Kept apart from ``conftest.py`` so the two suites cannot collide. The resume
conftest parametrises anything asking for ``case``; job evals ask for
``job_case``, and their fixtures live in a subdirectory the resume glob does not
reach.

Same two modes as the resume evals: offline replays a recorded response through
the fake provider, live sends the posting to the configured provider. The
expectations are identical either way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jip_ai import LLMProvider, build_router
from jip_api.application.jobs.analysis_services import (
    JobAnalysisOutcome,
    JobAnalyzerService,
    JobParseOutcome,
    JobParsingService,
)

JOB_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "jobs"


@dataclass(frozen=True, slots=True)
class JobEvalCase:
    """One posting and what a correct reading of it must contain."""

    path: Path
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def job_text(self) -> str:
        return str(self.data["job_text"])

    @property
    def recorded_parse(self) -> dict[str, Any]:
        output: dict[str, Any] = self.data["recorded_parse"]
        return output

    @property
    def recorded_analysis(self) -> dict[str, Any]:
        output: dict[str, Any] = self.data["recorded_analysis"]
        return output

    def expect(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def load_job_cases() -> list[JobEvalCase]:
    """Every job fixture on disk, sorted for a stable failure order."""
    return [
        JobEvalCase(path=path, data=json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(JOB_FIXTURE_DIR.glob("*.json"))
    ]


JOB_CASES = load_job_cases()


def _router(model: str) -> Any:
    return build_router(
        resume_parse_model=model,
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
        job_parse_model=model,
        job_analysis_model=model,
    )


def parse_job(
    provider: LLMProvider, case: JobEvalCase, *, model: str = "eval-model"
) -> JobParseOutcome:
    """Run the real parsing service against ``provider``.

    The whole path — prompt rendering, structured parsing, schema validation,
    business validation — not just the model call, because most of what these
    fixtures protect lives in the code around it.
    """
    service = JobParsingService(provider, _router(model), max_input_chars=60_000, max_attempts=1)
    return service.parse(case.job_text)


def analyze_job(
    provider: LLMProvider,
    case: JobEvalCase,
    parse: JobParseOutcome,
    *,
    model: str = "eval-model",
) -> JobAnalysisOutcome:
    """Run the real analyser over an already-parsed posting."""
    service = JobAnalyzerService(provider, _router(model), max_input_chars=60_000, max_attempts=1)
    return service.analyze(case.job_text, parse.validated)
