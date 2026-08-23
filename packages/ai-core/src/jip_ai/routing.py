"""Which model runs which operation.

``docs/05-ai-and-matching.md``: use stronger models only where necessary, and
make the routing configuration-driven. Configuration-driven is the part that
matters — a model id hard-coded next to a prompt cannot be changed without a
deploy, and cost tuning then never happens.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from jip_ai.provider import TokenUsage


class AIOperation(enum.StrEnum):
    """Routable operations.

    ``docs/10-api-contracts.md`` lists SEMANTIC_MATCH, RESUME_STRATEGY, and
    RESUME_REWRITE as well; each arrives with the phase that can run it.
    """

    RESUME_PARSE = "RESUME_PARSE"

    JOB_PARSE = "JOB_PARSE"
    """Reading a posting into requirements and responsibilities. Extraction."""

    JOB_ANALYSIS = "JOB_ANALYSIS"
    """Interpreting a parsed posting: role family and seniority. Judgement.

    Separate from JOB_PARSE because they are different tasks with different
    failure modes, and because routing them together would force one model
    choice on both — extraction wants faithfulness, interpretation wants
    reasoning.
    """

    MATCH_EXPLAIN = "MATCH_EXPLAIN"
    """Putting a finished match into words. Explanation only.

    The score, the statuses, and the recommendation are all decided
    deterministically before this runs — ``docs/05-ai-and-matching.md`` keeps
    final scoring away from AI, so this operation exists to describe a result
    and never to produce one.
    """

    RESUME_STRATEGY = "RESUME_STRATEGY"
    """Planning how to tailor a resume. Produces a plan, never resume text."""

    COVER_LETTER = "COVER_LETTER"
    """Drafting a cover letter for one job.

    Its own operation rather than a mode of RESUME_REWRITE. A rewrite is
    constrained by an existing line and may only re-say it; a cover letter has
    no original, so every number in it has to come from the profile or not
    appear. Different failure mode, different token ceiling, and worth being
    able to route and price separately.
    """

    RESUME_REWRITE = "RESUME_REWRITE"
    """Proposing changes to individual resume lines.

    Separate from RESUME_STRATEGY because ``docs/09-mvp-roadmap.md`` forbids
    one call that rewrites a document: the plan is shown to the user before
    any line changes, and each change is validated and accepted on its own.
    """


class ModelTier(enum.StrEnum):
    """Capability bands, so routing is expressed in intent rather than in model ids."""

    FAST = "FAST"
    BALANCED = "BALANCED"
    STRONG = "STRONG"


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD per million tokens.

    Estimated cost is stored on every ``AIRun`` so the bill is attributable per
    operation rather than arriving as one monthly number.
    """

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0

    def estimate(self, usage: TokenUsage) -> float:
        """Cost of one call, in USD."""
        million = 1_000_000
        return (
            usage.input_tokens * self.input_per_million
            + usage.output_tokens * self.output_per_million
            + usage.cached_input_tokens * self.cached_input_per_million
        ) / million


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """The decision for one operation."""

    operation: AIOperation
    model: str
    max_output_tokens: int
    effort: str | None = None
    pricing: ModelPricing | None = None


class ModelRouter:
    """Resolves an operation to a model.

    Deliberately a class rather than a dict lookup: the routing table is
    supplied by configuration, and the router is where a missing entry becomes a
    loud error instead of a silent fallback to whatever model is cheapest.
    """

    def __init__(self, routes: dict[AIOperation, ModelRoute]) -> None:
        self._routes = dict(routes)

    def route(self, operation: AIOperation) -> ModelRoute:
        try:
            return self._routes[operation]
        except KeyError as exc:
            raise ValueError(f"No model configured for operation {operation}.") from exc

    def operations(self) -> frozenset[AIOperation]:
        return frozenset(self._routes)


# Published rates at the time of writing. Wrong prices give wrong cost
# estimates, never wrong behaviour: nothing routes or retries on them.
PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(5.00, 25.00, cached_input_per_million=0.50),
    "claude-sonnet-5": ModelPricing(3.00, 15.00, cached_input_per_million=0.30),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00, cached_input_per_million=0.10),
}


def build_router(
    *,
    resume_parse_model: str,
    resume_parse_max_output_tokens: int,
    resume_parse_effort: str | None,
    job_parse_model: str | None = None,
    job_parse_max_output_tokens: int = 16000,
    job_parse_effort: str | None = None,
    job_analysis_model: str | None = None,
    job_analysis_max_output_tokens: int = 4000,
    job_analysis_effort: str | None = None,
    match_explain_model: str | None = None,
    match_explain_max_output_tokens: int = 1000,
    match_explain_effort: str | None = None,
    resume_strategy_model: str | None = None,
    resume_strategy_max_output_tokens: int = 3000,
    resume_strategy_effort: str | None = None,
    resume_rewrite_model: str | None = None,
    resume_rewrite_max_output_tokens: int = 8000,
    resume_rewrite_effort: str | None = None,
    cover_letter_model: str | None = None,
    cover_letter_max_output_tokens: int = 2000,
    cover_letter_effort: str | None = None,
) -> ModelRouter:
    """Assemble the routing table from settings.

    Resume parsing is an extraction task, which ``docs/05-ai-and-matching.md``
    would normally send to a fast model. It is configured toward a stronger one
    because the invariant here is *hallucinated facts = 0* — a cheaper model
    that occasionally invents a job title costs far more than the tokens saved.
    The value is configuration, so that judgement can be revisited with data.

    The job operations default to the resume model when unset, so adding them
    did not silently change what an existing deployment runs. Their token
    ceilings differ because their outputs do: a parse returns every requirement
    in a posting, an analysis returns a handful of fields and its reasoning.
    """
    routes = {
        AIOperation.RESUME_PARSE: ModelRoute(
            operation=AIOperation.RESUME_PARSE,
            model=resume_parse_model,
            max_output_tokens=resume_parse_max_output_tokens,
            effort=resume_parse_effort,
            pricing=PRICING.get(resume_parse_model),
        ),
    }

    for operation, model, tokens, effort in (
        (AIOperation.JOB_PARSE, job_parse_model, job_parse_max_output_tokens, job_parse_effort),
        (
            AIOperation.JOB_ANALYSIS,
            job_analysis_model,
            job_analysis_max_output_tokens,
            job_analysis_effort,
        ),
        (
            AIOperation.MATCH_EXPLAIN,
            match_explain_model,
            match_explain_max_output_tokens,
            match_explain_effort,
        ),
        (
            AIOperation.COVER_LETTER,
            cover_letter_model,
            cover_letter_max_output_tokens,
            cover_letter_effort,
        ),
        (
            AIOperation.RESUME_STRATEGY,
            resume_strategy_model,
            resume_strategy_max_output_tokens,
            resume_strategy_effort,
        ),
        (
            AIOperation.RESUME_REWRITE,
            resume_rewrite_model,
            resume_rewrite_max_output_tokens,
            resume_rewrite_effort,
        ),
    ):
        resolved = model or resume_parse_model
        routes[operation] = ModelRoute(
            operation=operation,
            model=resolved,
            max_output_tokens=tokens,
            effort=effort,
            pricing=PRICING.get(resolved),
        )

    return ModelRouter(routes)
