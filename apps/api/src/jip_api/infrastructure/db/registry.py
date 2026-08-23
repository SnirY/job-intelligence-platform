"""Model registry.

Importing this module imports every ORM model module, which is what populates
``Base.metadata``. Alembic autogenerate and any ``create_all`` need that
metadata to be complete; a model that no one imports is invisible to both, and
the symptom is a migration that silently omits a table.

Add every new model module here.
"""

from jip_api.domain.ai import models as ai_models
from jip_api.domain.applications import models as application_models
from jip_api.domain.career import history as career_history
from jip_api.domain.career import models as career_models
from jip_api.domain.career import skills as career_skills
from jip_api.domain.discovery import models as discovery_models
from jip_api.domain.documents import models as document_models
from jip_api.domain.jobs import analysis as job_analysis_models
from jip_api.domain.jobs import models as job_models
from jip_api.domain.jobs import saved_views as saved_view_models
from jip_api.domain.matching import models as matching_models
from jip_api.domain.processing import models as processing_models
from jip_api.domain.resumes import models as resume_models
from jip_api.domain.resumes import tailoring as resume_tailoring_models
from jip_api.domain.users import models as user_models

__all__ = [
    "ai_models",
    "application_models",
    "career_history",
    "career_models",
    "career_skills",
    "discovery_models",
    "document_models",
    "job_analysis_models",
    "job_models",
    "matching_models",
    "processing_models",
    "resume_models",
    "resume_tailoring_models",
    "saved_view_models",
    "user_models",
]
