"""Does the provider actually accept our response schemas?

DEV-017 is the gap this closes. Structured outputs compile the JSON schema into
a grammar, and the API refuses one whose compiled form is too large:

```text
400 invalid_request_error: The compiled grammar is too large, which would cause
performance issues.
```

**No other test in this repository can catch that.** The offline evaluations
replay a recorded response through a fake provider, so the schema is never sent
anywhere and never compiled. `resume_parse` shipped in that state and had never
worked against a real model at any point.

There are six schemas now. Each was checked by hand once, which is a manual step
nobody is reminded to repeat — so this is the reminder, in the only form that
can work: one cheap call per schema against the live API.

Marked `live_ai` and skipped by default, because
`docs/11-engineering-standards.md` forbids live model calls in the normal suite.
Run it after touching any schema:

```bash
JIP_RUN_AI_EVALS=1 JIP_AI_API_KEY=sk-ant-... pytest tests/evals -m live_ai
```

The cost is one minimal completion per schema. What is under test is whether the
request is *accepted*, not what comes back, so `max_output_tokens` is as small
as the API allows.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import pytest

from jip_ai import AIError, LLMProvider, StructuredRequest
from jip_api.application.jobs.analysis_schema import (
    job_analysis_json_schema,
    job_parse_json_schema,
)
from jip_api.application.matching.explain import match_explanation_json_schema
from jip_api.application.resumes.schema import (
    SECTION_MODELS,
    resume_parse_json_schema,
    section_json_schema,
)
from jip_api.application.resumes.tailoring_schema import (
    resume_rewrite_json_schema,
    resume_strategy_json_schema,
)

SCHEMAS: dict[str, Any] = {
    "job_parse": job_parse_json_schema,
    "job_analysis": job_analysis_json_schema,
    "match_explain": match_explanation_json_schema,
    "resume_strategy": resume_strategy_json_schema,
    "resume_rewrite": resume_rewrite_json_schema,
    # The four resume sections, which replaced the combined parse in DEV-017.
    # These are the ones a future edit is most likely to grow back past the
    # limit, since they are what the limit already caught once.
    **{name: partial(section_json_schema, name) for name in SECTION_MODELS},
}
"""Every schema that must compile.

``resume_parse`` is deliberately absent, and still is after DEV-017: the
combined schema does not compile and is no longer sent. It has its own test
below, which asserts the known failure rather than pretending otherwise — a skip
would let the day it starts compiling pass unnoticed, and with it the chance to
collapse four calls back into one.
"""


def _probe(schema: dict[str, Any]) -> StructuredRequest:
    """The smallest request that still makes the API compile the grammar."""
    return StructuredRequest(
        system="Reply with the minimal valid object for the schema.",
        user="Reply now.",
        json_schema=schema,
        max_output_tokens=16,
    )


@pytest.mark.live_ai
@pytest.mark.parametrize("name", sorted(SCHEMAS), ids=sorted(SCHEMAS))
def test_the_schema_compiles(name: str, live_provider: LLMProvider) -> None:
    """A schema the provider refuses makes its whole feature unusable, and
    nothing else in the suite would notice."""
    try:
        live_provider.generate_structured(_probe(SCHEMAS[name]()), model="claude-sonnet-5")
    except AIError as error:
        detail = (error.details or "").lower()
        if "grammar is too large" in detail:
            pytest.fail(
                f"{name} no longer compiles: the grammar is too large. "
                "Flatten it or split the operation — see DEV-017. Do not turn "
                "the constraint off, which is the mitigation that already had "
                "to be applied once."
            )
        # Any other failure is about this run, not about the schema: a truncated
        # answer at 16 tokens is the expected outcome and means it compiled.
        if "too large" in detail:
            raise


@pytest.mark.live_ai
def test_resume_parse_still_does_not_compile(live_provider: LLMProvider) -> None:
    """The known-bad case, asserted rather than skipped.

    DEV-017 is closed by splitting the parse into four calls, not by this schema
    becoming acceptable — it is still too large and is no longer sent anywhere.
    The assertion stays because it is the only thing that would report a raised
    provider limit, which is the one fact that would justify collapsing four
    calls back into one. Left as a skip, that day would arrive unnoticed.

    Takes ``live_provider`` rather than building its own, because that fixture
    is the single gate on ``JIP_RUN_AI_EVALS``. Checking ``ai_configured``
    directly looks equivalent and is not: a key sits in the repository root
    ``.env``, so the test would bill a call on an ordinary run.
    """
    with pytest.raises(AIError) as caught:
        live_provider.generate_structured(
            _probe(resume_parse_json_schema()), model="claude-sonnet-5"
        )

    assert "too large" in (caught.value.details or "").lower(), (
        "resume_parse now compiles — the provider limit has moved, and the "
        "four-call split in parsing.py could be reconsidered"
    )
