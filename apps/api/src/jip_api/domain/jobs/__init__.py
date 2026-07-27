"""Jobs domain.

A job the user is considering, the untouched record of where it came from, and
the versioned interpretation of what it asks for. The analysis lives in its own
tables so an inference can never overwrite what a person typed or what the
posting said.
"""

from jip_api.domain.jobs.analysis import (
    AnalyzedSeniority,
    JobAnalysis,
    JobRequirement,
    JobResponsibility,
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
    RoleFamily,
    to_target_seniority,
)
from jip_api.domain.jobs.models import (
    Job,
    JobImport,
    JobImportMethod,
    JobProcessingStatus,
    WorkMode,
    normalize_title,
)
from jip_api.domain.jobs.urls import normalize_url

__all__ = [
    "AnalyzedSeniority",
    "Job",
    "JobAnalysis",
    "JobImport",
    "JobImportMethod",
    "JobProcessingStatus",
    "JobRequirement",
    "JobResponsibility",
    "RequirementExplicitness",
    "RequirementImportance",
    "RequirementType",
    "RoleFamily",
    "WorkMode",
    "normalize_title",
    "normalize_url",
    "to_target_seniority",
]
