"""AI integration core.

An integration layer, not a domain (``docs/04-system-architecture.md``). It
knows about providers, prompts, schemas, retries, and traces; it knows nothing
about careers, resumes, or jobs. Domain meaning lives in ``jip_api``, and the
prompts themselves live in ``jip_prompts``.
"""

from jip_ai.failures import AIError, AIFailureCode
from jip_ai.prompts import PromptRegistry, PromptTemplate
from jip_ai.provider import LLMProvider, StructuredRequest, StructuredResult, TokenUsage
from jip_ai.retry import run_with_retry
from jip_ai.routing import (
    PRICING,
    AIOperation,
    ModelPricing,
    ModelRoute,
    ModelRouter,
    ModelTier,
    build_router,
)
from jip_ai.structured import (
    parse_structured_output,
    sanitize_json_schema,
    truncate_for_prompt,
)
from jip_ai.tracing import AIRunTrace, compute_input_hash, timed

__all__ = [
    "PRICING",
    "AIError",
    "AIFailureCode",
    "AIOperation",
    "AIRunTrace",
    "LLMProvider",
    "ModelPricing",
    "ModelRoute",
    "ModelRouter",
    "ModelTier",
    "PromptRegistry",
    "PromptTemplate",
    "StructuredRequest",
    "StructuredResult",
    "TokenUsage",
    "build_router",
    "compute_input_hash",
    "parse_structured_output",
    "run_with_retry",
    "sanitize_json_schema",
    "timed",
    "truncate_for_prompt",
]

__version__ = "0.1.0"
