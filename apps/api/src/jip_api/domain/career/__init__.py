"""Career domain: the professional source of truth.

Everything here is user-owned and manually maintained in Phase 2. Later phases
add AI-extracted data beside it, which is why verification state is recorded
from the start rather than assumed.
"""

from jip_api.domain.career.models import (
    CareerProfile,
    Seniority,
    TargetRole,
    VerificationStatus,
)

__all__ = ["CareerProfile", "Seniority", "TargetRole", "VerificationStatus"]
