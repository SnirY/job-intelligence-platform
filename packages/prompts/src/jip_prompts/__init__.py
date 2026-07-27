"""The prompt registry.

``docs/04-system-architecture.md`` gives prompts their own package, and
``docs/05-ai-and-matching.md`` requires them to be centrally managed and
versioned. Separating them from ``jip_ai`` keeps the mechanism (registry,
rendering, versioning) apart from the content, so a prompt change is a diff in
one file rather than a change inside the integration layer.

Names carry their version — ``resume_parser_v1``. Editing a prompt's text means
registering a new name, because the old version is recorded on every ``AIRun``,
every ``DocumentExtraction``, and every ``JobAnalysis`` produced by it, and
those must keep meaning what they meant.
"""

from jip_ai.prompts import PromptRegistry, PromptTemplate
from jip_prompts.job_analysis import JOB_ANALYSIS_V1
from jip_prompts.job_parser import JOB_PARSER_V1
from jip_prompts.match_explainer import MATCH_EXPLAINER_V1
from jip_prompts.resume_parser import RESUME_PARSER_V1

REGISTRY = PromptRegistry()
REGISTRY.register(RESUME_PARSER_V1)
REGISTRY.register(JOB_PARSER_V1)
REGISTRY.register(JOB_ANALYSIS_V1)
REGISTRY.register(MATCH_EXPLAINER_V1)

RESUME_PARSER_LATEST = RESUME_PARSER_V1.name
"""The version new extractions use.

Named so the pipeline does not hard-code ``"resume_parser_v1"`` in a dozen
places, and so introducing v2 is a one-line change that leaves stored v1
extractions readable.
"""

JOB_PARSER_LATEST = JOB_PARSER_V1.name
JOB_ANALYSIS_LATEST = JOB_ANALYSIS_V1.name
MATCH_EXPLAINER_LATEST = MATCH_EXPLAINER_V1.name
"""The versions new analyses use. Both are recorded on every ``JobAnalysis``,
separately, because the two steps version independently."""


def get_prompt(name: str) -> PromptTemplate:
    """Look up a registered prompt by versioned name."""
    return REGISTRY.get(name)


__all__ = [
    "JOB_ANALYSIS_LATEST",
    "JOB_ANALYSIS_V1",
    "JOB_PARSER_LATEST",
    "JOB_PARSER_V1",
    "MATCH_EXPLAINER_LATEST",
    "MATCH_EXPLAINER_V1",
    "REGISTRY",
    "RESUME_PARSER_LATEST",
    "RESUME_PARSER_V1",
    "get_prompt",
]

__version__ = "0.1.0"
