"""AI run tracing.

The AI *integration* lives in ``packages/ai-core``; what belongs to the domain
is the record that a call happened, what it cost, and whether it worked.
"""

from jip_api.domain.ai.models import AIRun, AIRunStatus

__all__ = ["AIRun", "AIRunStatus"]
