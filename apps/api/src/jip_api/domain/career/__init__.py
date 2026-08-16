"""Career domain: the professional source of truth.

Everything user-owned here is manually maintained in Phase 2. Later phases add
AI-extracted data beside it, which is why verification state and source are
recorded from the start rather than inferred later.

The canonical ``Skill`` catalogue and its aliases are the exception: they are
global, shared by every user, and must never be scoped by ``user_id``.
"""

from jip_api.domain.career.history import (
    Certification,
    Education,
    EmploymentType,
    Experience,
    ExperienceAchievement,
    ExperienceSkill,
    Project,
    ProjectSkill,
    ProjectStatus,
    ProjectType,
)
from jip_api.domain.career.models import CareerProfile, Seniority, TargetRole, VerificationStatus
from jip_api.domain.career.skills import (
    Proficiency,
    Skill,
    SkillAlias,
    SkillCategory,
    SkillSource,
    UserSkill,
    normalize_skill_name,
)

__all__ = [
    "CareerProfile",
    "Certification",
    "Education",
    "EmploymentType",
    "Experience",
    "ExperienceAchievement",
    "ExperienceSkill",
    "Proficiency",
    "Project",
    "ProjectSkill",
    "ProjectStatus",
    "ProjectType",
    "Seniority",
    "Skill",
    "SkillAlias",
    "SkillCategory",
    "SkillSource",
    "TargetRole",
    "UserSkill",
    "VerificationStatus",
    "normalize_skill_name",
]
