"""Model registry.

Importing this module imports every ORM model module, which is what populates
``Base.metadata``. Alembic autogenerate and any ``create_all`` need that
metadata to be complete; a model that no one imports is invisible to both, and
the symptom is a migration that silently omits a table.

Add every new model module here.
"""

from jip_api.domain.career import history as career_history
from jip_api.domain.career import models as career_models
from jip_api.domain.career import skills as career_skills
from jip_api.domain.documents import models as document_models
from jip_api.domain.users import models as user_models

__all__ = [
    "career_history",
    "career_models",
    "career_skills",
    "document_models",
    "user_models",
]
